"""Self-service TOTP, recovery, passkeys, sessions and administrator account creation."""

import base64
import io
import json
import os
import re
import time
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.models import User, LoginSession, now
from app.auth_models import TotpDevice, Passkey, RecoveryCode, ExternalIdentity
from app.security import (
    database,
    identity,
    verify_password,
    hash_password,
    digest,
    revoke,
)
from app.auth_service import (
    challenge,
    consume,
    recent,
    event,
    verify_factor,
    enabled_totp,
    new_recovery,
    complete_login,
    issue_session,
)
from app.system_config import config, encrypt, decrypt, password_policy
from app import access_control as ac

router = APIRouter(prefix="/api/v1/auth", tags=["Hitelesítés és biztonság"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Proof(Input):
    password: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=128)


class Token(Input):
    token: str = Field(min_length=32, max_length=128)


class MfaProof(Token):
    code: str = Field(min_length=1, max_length=128)


class WebProof(Token):
    credential: dict


class WebRegister(WebProof):
    name: str = Field(min_length=1, max_length=120)


def throttle(request, db, key, per_client=False):
    """Configurable attempt limit; see app.security.limit_login.

    Keys that do not name a user or a challenge must pass per_client=True,
    otherwise one client could exhaust the shared counter for everyone.
    """
    from app import api
    from app.security import rate_configuration

    token = rate_configuration.set(config(db, "security"))
    try:
        api.limit_login(request, key, per_client=per_client)
    finally:
        rate_configuration.reset(token)


def failure_limit(request, db, key, record=False):
    """Failure-only, per client address budget (app.security.limit_failures)."""
    from app.security import limit_failures, rate_configuration

    token = rate_configuration.set(config(db, "security"))
    try:
        limit_failures(request, key, record)
    finally:
        rate_configuration.reset(token)


def user_for(db, id):
    u = db.get(User, id, populate_existing=True, with_for_update=True)
    if not u or not u.active:
        raise HTTPException(401, "A fiók nem használható.")
    return u


def validate_client_context(credential):
    try:
        encoded = credential["response"]["clientDataJSON"]
        if len(encoded) > 16384:
            raise ValueError("Oversized client data")
        value = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        if (
            value.get("crossOrigin", False) is not False
            or value.get("topOrigin", rp()[1]) != rp()[1]
        ):
            raise ValueError("Cross-origin ceremony")
    except Exception:
        raise ValueError("Invalid WebAuthn client context") from None


def admin_target(db, id):
    user = db.get(User, id, populate_existing=True, with_for_update=True)
    if not user:
        raise HTTPException(404, "A felhasználó nem található.")
    return user


def rp():
    from urllib.parse import urlparse

    origin = os.getenv("APP_ORIGIN", "https://dev.pinfo.hu").rstrip("/")
    u = urlparse(origin)
    if u.scheme != "https" or not u.hostname or u.path:
        raise HTTPException(
            503, "A passkey használatához szabályos HTTPS APP_ORIGIN szükséges."
        )
    return u.hostname, origin


@router.get("/methods")
def methods(db: Session = Depends(database)):
    p = config(db, "auth")
    return {k: p[k] for k in ["password", "google", "passkey", "registration"]} | {
        "branding": config(db, "general")
    }


@router.get("/security")
def security(who=Depends(identity), db: Session = Depends(database)):
    return {
        "username": who.user.username,
        "email": who.user.email,
        "email_verified": who.user.email_verified,
        "must_change_password": who.user.must_change_password,
        "mfa_enabled": enabled_totp(db, who.user.id),
        "totp_devices": [
            {
                "name": "Hitelesítőalkalmazás (TOTP)",
                "created_at": db.get(TotpDevice, who.user.id).created_at,
            }
        ]
        if enabled_totp(db, who.user.id)
        else [],
        "mfa_policy": config(db, "mfa"),
        "recent": bool(
            who.session.reauthenticated_at
            and who.session.reauthenticated_at > now() - timedelta(minutes=5)
        ),
        "passkeys": [
            {
                "id": x.id,
                "name": x.name,
                "created_at": x.created_at,
                "last_used_at": x.last_used_at,
            }
            for x in db.scalars(select(Passkey).where(Passkey.user_id == who.user.id))
        ],
        "google_linked": bool(
            db.scalar(
                select(ExternalIdentity.id).where(
                    ExternalIdentity.user_id == who.user.id,
                    ExternalIdentity.provider == "google",
                )
            )
        ),
        "recovery_remaining": len(
            list(
                db.scalars(
                    select(RecoveryCode.code_hash).where(
                        RecoveryCode.user_id == who.user.id,
                        RecoveryCode.used_at.is_(None),
                    )
                )
            )
        ),
    }


@router.post("/reauth")
def reauth(
    body: Proof,
    request: Request,
    who=Depends(identity),
    db: Session = Depends(database),
):
    throttle(request, db, "reauth:" + str(who.user.id))
    user = user_for(db, who.user.id)
    if not config(db, "auth")["password"] or not verify_password(
        body.password, user.password_hash
    ):
        raise HTTPException(403, "A jelszavas újraazonosítás sikertelen.")
    from app.auth_service import needs_mfa

    if needs_mfa(db, user) and not verify_factor(db, user, body.code):
        raise HTTPException(403, "A második faktor hibás.")
    who.session.reauthenticated_at = now()
    who.session.mfa_verified = needs_mfa(db, user)
    event(db, user, "reauth")
    db.commit()
    return {"verified": True}


def totp_setup(db, user, session_hash=None):
    import pyotp
    import qrcode
    import qrcode.image.svg

    if not config(db, "mfa")["enabled"] and not user.mfa_reset_required:
        from app.auth_service import required_mfa

        if not required_mfa(db, user):
            raise HTTPException(403, "Új TOTP-eszköz aktiválása nincs engedélyezve.")
    existing = db.get(TotpDevice, user.id, with_for_update=True)
    replacing = bool(existing and existing.enabled)
    if replacing and not session_hash:
        raise HTTPException(409, "A második faktor már aktív.")
    secret = pyotp.random_base32()
    encoded = encrypt(secret)
    setup_token = None
    if replacing:
        setup_token = challenge(
            db, "totp_replace", user.id, {"secret": encoded, "session": session_hash}
        )
    elif existing:
        existing.secret = encoded
        existing.created_at = now()
    else:
        db.add(TotpDevice(user_id=user.id, secret=encoded))
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.username, issuer_name=config(db, "general")["display_name"]
    )
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    event(db, user, "totp_setup")
    db.commit()
    return {
        "secret": secret,
        "uri": uri,
        "qr_svg": buffer.getvalue().decode(),
        "setup_token": setup_token,
    }


def confirm_totp(db, user, code, setup_token=None, session_hash=None):
    import pyotp

    device = db.get(TotpDevice, user.id, with_for_update=True, populate_existing=True)
    replacement = consume(db, setup_token, ["totp_replace"]) if setup_token else None
    if replacement and (
        replacement.user_id != user.id or replacement.payload["session"] != session_hash
    ):
        raise HTTPException(403, "Másik munkamenet TOTP-cseréje.")
    if not device or device.enabled and not replacement:
        raise HTTPException(409, "Nincs aktiválásra váró eszköz.")
    encoded = replacement.payload["secret"] if replacement else device.secret
    current_counter = int(time.time()) // 30
    matched = next(
        (
            step
            for step in [current_counter, current_counter - 1, current_counter + 1]
            if secrets.compare_digest(pyotp.TOTP(decrypt(encoded)).at(step * 30), code)
        ),
        None,
    )
    if (
        not replacement and device.created_at < now() - timedelta(minutes=10)
    ) or matched is None:
        event(db, user, "mfa_failed")
        db.commit()
        raise HTTPException(403, "Hibás ellenőrző kód.")
    if replacement:
        device.secret = encoded
        device.created_at = now()
    device.enabled = True
    device.last_counter = matched
    user.mfa_reset_required = False
    codes = new_recovery(db, user)
    event(db, user, "totp_replaced" if replacement else "totp_enabled")
    return codes


@router.post("/totp/setup")
def setup(who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    return totp_setup(db, who.user, who.session.token_hash)


class TotpConfirmation(Proof):
    setup_token: str | None = Field(default=None, min_length=32, max_length=128)


@router.post("/totp/confirm")
def confirm(
    body: TotpConfirmation,
    request: Request,
    who=Depends(identity),
    db: Session = Depends(database),
):
    throttle(request, db, "totp:" + str(who.user.id))
    recent(who, db)
    user = user_for(db, who.user.id)
    codes = confirm_totp(db, user, body.code, body.setup_token, who.session.token_hash)
    db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id,
            LoginSession.token_hash != who.session.token_hash,
        )
    )
    who.session.mfa_verified = True
    who.session.reauthenticated_at = now()
    db.commit()
    return {"recovery_codes": codes}


@router.post("/mfa/setup")
def pending_setup(body: Token, request: Request, db: Session = Depends(database)):
    throttle(request, db, "mfa:" + digest(body.token))
    c = consume(db, body.token, ["mfa_login"], use=False)
    user = user_for(db, c.user_id)
    if enabled_totp(db, user.id):
        raise HTTPException(409, "A második faktor már aktív.")
    return totp_setup(db, user)


@router.post("/mfa/complete")
def pending_complete(
    body: MfaProof,
    request: Request,
    response: Response,
    db: Session = Depends(database),
):
    throttle(request, db, "mfa:" + digest(body.token))
    c = consume(db, body.token, ["mfa_login"], use=False)
    # A fresh challenge comes with every password login, so the per-token
    # counter alone would allow unlimited code guesses: also limit failed
    # codes per user and client address (SECURITY-01).
    failure_limit(request, db, "mfa:user:" + str(c.user_id))
    user = user_for(db, c.user_id)
    if not config(db, "auth").get(c.payload["method"]):
        raise HTTPException(403, "Ez a bejelentkezési mód időközben letiltásra került.")
    codes = None
    if not enabled_totp(db, user.id):
        codes = confirm_totp(db, user, body.code)
    elif not verify_factor(db, user, body.code):
        failure_limit(request, db, "mfa:user:" + str(user.id), record=True)
        raise HTTPException(403, "A második faktor hibás.")
    c.used = True
    result = issue_session(db, user, request, response, c.payload["method"], True)
    return result | ({"recovery_codes": codes} if codes else {})


@router.post("/totp/disable")
def disable_totp(who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    from app.auth_service import required_mfa

    if required_mfa(db, who.user):
        raise HTTPException(
            409, "Szerepköri szabály miatt a második faktor nem kapcsolható ki."
        )
    device = db.get(TotpDevice, who.user.id)
    if device:
        db.delete(device)
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == who.user.id))
    event(db, who.user, "totp_disabled")
    revoke(db, who.user.id)
    db.commit()
    return {"login_required": True}


@router.post("/recovery/rotate")
def rotate_recovery(who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    if not enabled_totp(db, who.user.id):
        raise HTTPException(409, "Előbb aktiváld a TOTP-t.")
    result = new_recovery(db, who.user)
    event(db, who.user, "recovery_rotated")
    db.commit()
    return {"recovery_codes": result}


@router.get("/sessions")
def sessions(who=Depends(identity), db: Session = Depends(database)):
    lifetime = timedelta(hours=config(db, "security")["session_hours"])
    return [
        {
            "id": digest("session-view:" + s.token_hash),
            "current": s.token_hash == who.session.token_hash,
            "method": s.auth_method,
            "mfa": s.mfa_verified,
            "created_at": s.created_at,
            "expires_at": min(
                s.expires_at,
                s.created_at + lifetime,
            ),
        }
        for s in db.scalars(
            select(LoginSession)
            .where(
                LoginSession.user_id == who.user.id,
                LoginSession.expires_at > now(),
                LoginSession.created_at > now() - lifetime,
            )
            .order_by(LoginSession.created_at.desc())
        )
    ]


@router.delete("/sessions/{id}")
def delete_session(id: str, who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    row = next(
        (
            s
            for s in db.scalars(
                select(LoginSession).where(LoginSession.user_id == who.user.id)
            )
            if digest("session-view:" + s.token_hash) == id
        ),
        None,
    )
    if not row:
        raise HTTPException(404, "A munkamenet nem található.")
    db.delete(row)
    event(db, who.user, "session_revoked")
    db.commit()
    return {"revoked": True}


@router.post("/passkeys/register/options")
def register_options(who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    if not config(db, "auth")["passkey"]:
        raise HTTPException(403, "A passkey nincs engedélyezve.")
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )

    hostname, _ = rp()
    options = generate_registration_options(
        rp_id=hostname,
        rp_name=config(db, "general")["display_name"],
        user_id=str(who.user.id).encode(),
        user_name=who.user.username,
        user_display_name=who.user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(
                id=base64.urlsafe_b64decode(
                    p.credential_id + "=" * (-len(p.credential_id) % 4)
                )
            )
            for p in db.scalars(select(Passkey).where(Passkey.user_id == who.user.id))
        ],
    )
    token = challenge(
        db,
        "passkey_register",
        who.user.id,
        {
            "challenge": base64.urlsafe_b64encode(options.challenge).decode(),
            "session": who.session.token_hash,
        },
    )
    db.commit()
    return {"token": token, "options": json.loads(options_to_json(options))}


@router.post("/passkeys/register/verify")
def register_verify(
    body: WebRegister, who=Depends(identity), db: Session = Depends(database)
):
    recent(who, db)
    if not config(db, "auth")["passkey"]:
        raise HTTPException(403, "A passkey nincs engedélyezve.")
    c = consume(db, body.token, ["passkey_register"])
    if c.user_id != who.user.id or c.payload["session"] != who.session.token_hash:
        raise HTTPException(403, "Másik munkamenet hitelesítési kérése.")
    from webauthn import verify_registration_response

    host, origin = rp()
    try:
        validate_client_context(body.credential)
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=base64.urlsafe_b64decode(c.payload["challenge"]),
            expected_rp_id=host,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception:
        event(db, who.user, "passkey_failed")
        db.commit()
        raise HTTPException(
            403, "A passkey regisztráció ellenőrzése sikertelen."
        ) from None
    id = base64.urlsafe_b64encode(verified.credential_id).decode().rstrip("=")
    db.add(
        Passkey(
            user_id=who.user.id,
            rp_id=host,
            credential_id=id,
            credential_hash=digest(id),
            public_key=base64.b64encode(verified.credential_public_key).decode(),
            sign_count=verified.sign_count,
            name=body.name.strip(),
        )
    )
    event(db, who.user, "passkey_registered")
    db.commit()
    return {"registered": True}


class PasskeyOptions(Input):
    reauth: bool = False


@router.post("/passkeys/login/options")
def login_options(
    body: PasskeyOptions, request: Request, db: Session = Depends(database)
):
    throttle(request, db, "passkey-begin", per_client=True)
    if not config(db, "auth")["passkey"]:
        raise HTTPException(403, "A passkey nincs engedélyezve.")
    who = identity(request, db) if body.reauth else None
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement

    host, _ = rp()
    options = generate_authentication_options(
        rp_id=host, user_verification=UserVerificationRequirement.REQUIRED
    )
    token = challenge(
        db,
        "passkey_login",
        who.user.id if who else None,
        {
            "challenge": base64.urlsafe_b64encode(options.challenge).decode(),
            "session": who.session.token_hash if who else None,
        },
    )
    db.commit()
    return {"token": token, "options": json.loads(options_to_json(options))}


@router.post("/passkeys/login/verify")
def login_verify(
    body: WebProof,
    request: Request,
    response: Response,
    db: Session = Depends(database),
):
    throttle(request, db, "passkey:" + digest(body.token))
    if not config(db, "auth")["passkey"]:
        raise HTTPException(403, "A passkey nincs engedélyezve.")
    c = consume(db, body.token, ["passkey_login"])
    id = str(body.credential.get("id", ""))
    p = db.scalar(
        select(Passkey).where(Passkey.credential_hash == digest(id)).with_for_update()
    )
    if not p or p.credential_id != id or p.rp_id != rp()[0]:
        db.commit()
        raise HTTPException(403, "Ismeretlen passkey.")
    user = user_for(db, p.user_id)
    from webauthn import verify_authentication_response

    host, origin = rp()
    try:
        validate_client_context(body.credential)
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=base64.urlsafe_b64decode(c.payload["challenge"]),
            expected_rp_id=host,
            expected_origin=origin,
            credential_public_key=base64.b64decode(p.public_key),
            credential_current_sign_count=p.sign_count,
            require_user_verification=True,
        )
        handle = body.credential.get("response", {}).get("userHandle")
        if (
            handle
            and base64.urlsafe_b64decode(handle + "=" * (-len(handle) % 4))
            != str(user.id).encode()
        ):
            raise ValueError("User handle mismatch")
    except Exception:
        event(db, user, "passkey_failed")
        db.commit()
        raise HTTPException(
            403, "A passkey hitelesítés ellenőrzése sikertelen."
        ) from None
    p.sign_count = verified.new_sign_count
    p.last_used_at = now()
    if c.user_id:
        who = identity(request, db)
        if (
            user.id != c.user_id
            or who.user.id != user.id
            or c.payload["session"] != who.session.token_hash
        ):
            raise HTTPException(403, "Másik fiók passkey adata.")
        from app.auth_service import needs_mfa

        if user.mfa_reset_required or (
            not config(db, "mfa")["passkey_mfa"] and needs_mfa(db, user)
        ):
            raise HTTPException(
                403, "Az újraazonosításhoz a szabályzat TOTP-kódot kér."
            )
        who.session.reauthenticated_at = now()
        who.session.mfa_verified = True
        event(db, user, "reauth_passkey")
        db.commit()
        return {"verified": True}
    return complete_login(db, user, request, response, "passkey", uv=True)


@router.delete("/passkeys/{id}")
def delete_passkey(id: int, who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    p = db.get(Passkey, id)
    if not p or p.user_id != who.user.id:
        raise HTTPException(404, "A passkey nem található.")
    from app.settings_api import ensure_admin_methods

    policy = config(db, "auth")
    if (
        not policy["password"]
        and not (
            policy["google"]
            and db.scalar(
                select(ExternalIdentity.id).where(
                    ExternalIdentity.user_id == who.user.id
                )
            )
        )
        and not (
            policy["passkey"]
            and db.scalar(
                select(Passkey.id).where(
                    Passkey.user_id == who.user.id, Passkey.id != id
                )
            )
        )
    ):
        raise HTTPException(
            409, "Előbb állíts be másik használható bejelentkezési módot."
        )
    ensure_admin_methods(db, config(db, "auth"), exclude_passkey=id)
    db.delete(p)
    event(db, who.user, "passkey_deleted")
    db.commit()
    return {"deleted": True}


class Username(Input):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,79}$")


@router.put("/username")
def username(body: Username, who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    who.user.username = body.username
    event(db, who.user, "username_changed")
    db.commit()
    return {"username": body.username}


class SystemUser(Username):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    active: bool = True
    roles: list[int] = Field(default_factory=list, max_length=30)


@router.post("/system-users")
def create_system_user(
    body: SystemUser, who=Depends(identity), db: Session = Depends(database)
):
    ac.need(who, "system.users.manage")
    recent(who, db)
    if (
        not body.name.strip()
        or body.email
        and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email)
    ):
        raise HTTPException(422, "Érvénytelen név vagy e-mail.")
    password_policy(db, body.password)
    from app.access_api import validate_roles, apply_user_access, UserAccessInput

    access = UserAccessInput(roles=body.roles)
    validate_roles(db, who, access, None)
    user = User(
        name=body.name.strip(),
        username=body.username,
        email=body.email.casefold() if body.email else None,
        password_hash=hash_password(body.password),
        active=body.active,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    apply_user_access(db, user, access, None, who.user.id)
    event(db, who.user, "system_user_create", user_id=user.id, username=user.username)
    db.commit()
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "active": user.active,
    }


class ResetPassword(Input):
    password: str = Field(min_length=12, max_length=128)
    reason: str = Field(min_length=10, max_length=500)


@router.post("/system-users/{id}/reset-password")
def reset_password(
    id: int, body: ResetPassword, who=Depends(identity), db: Session = Depends(database)
):
    ac.protected_admin(who)
    recent(who, db)
    user = admin_target(db, id)
    if user.id == who.user.id:
        raise HTTPException(409, "Saját jelszóhoz a jelszócsere funkciót használd.")
    password_policy(db, body.password)
    user.password_hash = hash_password(body.password)
    user.must_change_password = True
    revoke(db, user.id)
    event(db, who.user, "admin_password_reset", user_id=user.id, reason=body.reason)
    db.commit()
    return {"reset": True, "must_change_password": True}


class RecoveryRequest(Input):
    user_id: int
    reason: str = Field(min_length=20, max_length=500)


@router.post("/admin-recovery/request")
def recovery_request(
    body: RecoveryRequest, who=Depends(identity), db: Session = Depends(database)
):
    ac.protected_admin(who)
    recent(who, db, require_mfa=True)
    user = admin_target(db, body.user_id)
    token = challenge(
        db,
        "admin_recovery",
        user.id,
        {"requester": who.user.id, "reason": body.reason},
        minutes=60,
    )
    event(db, who.user, "recovery_requested", user_id=user.id, reason=body.reason)
    db.commit()
    return {
        "approval_token": token,
        "message": "Egy másik, frissen több faktorral azonosított superadmin jóváhagyása szükséges.",
    }


@router.post("/admin-recovery/approve")
def recovery_approve(
    body: Token, who=Depends(identity), db: Session = Depends(database)
):
    ac.protected_admin(who)
    recent(who, db, require_mfa=True)
    c = consume(db, body.token, ["admin_recovery"])
    requester = db.get(User, c.payload["requester"])
    if (
        not requester
        or not requester.active
        or not requester.superadmin
        or who.user.id in [requester.id, c.user_id]
    ):
        raise HTTPException(403, "Független, aktív superadmin jóváhagyása szükséges.")
    user = admin_target(db, c.user_id)
    device = db.get(TotpDevice, user.id)
    if device:
        db.delete(device)
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    user.mfa_reset_required = True
    revoke(db, user.id)
    event(
        db,
        who.user,
        "recovery_approved",
        user_id=user.id,
        requester_id=requester.id,
        reason=c.payload["reason"],
    )
    db.commit()
    return {"recovery_approved": True, "enrollment_required": True}
