"""Shared authentication ceremony checks. Authorization remains CODEX 08 RBAC."""

import secrets
import time
import hmac
from datetime import timedelta
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select, delete, or_
from app.models import LoginSession, Membership, now
from app.auth_models import AuthChallenge, TotpDevice, RecoveryCode
from app import access_control as ac
from app.system_config import config, decrypt
from app.security import digest, csrf_for, COOKIE, audit


def challenge(db, purpose, user_id=None, payload=None, minutes=5):
    token = secrets.token_urlsafe(32)
    db.execute(
        delete(AuthChallenge).where(
            AuthChallenge.expires_at < now() - timedelta(days=1)
        )
    )
    db.add(
        AuthChallenge(
            token_hash=digest(token),
            purpose=purpose,
            user_id=user_id,
            payload=payload or {},
            expires_at=now() + timedelta(minutes=minutes),
        )
    )
    db.flush()
    return token


def consume(db, token, purposes, use=True):
    row = db.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.token_hash == digest(token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or row.used or row.expires_at <= now() or row.purpose not in purposes:
        raise HTTPException(
            400, "A hitelesítési kérés lejárt vagy már felhasznált. Indítsd újra."
        )
    if use:
        row.used = True
    return row


def enabled_totp(db, user_id):
    device = db.get(TotpDevice, user_id)
    return bool(device and device.enabled)


def required_mfa(db, user):
    p = config(db, "mfa")
    if user.mfa_reset_required:
        return True
    ids = set(p["required_roles"])
    if not ids:
        return False
    from app.access_models import AccessBinding, AccessRole, ResourceAccess

    if user.superadmin:
        return (
            db.scalar(
                select(AccessRole.id).where(
                    AccessRole.code == "superadmin", AccessRole.protected.is_(True)
                )
            )
            in ids
        )
    system = ac.is_system(db, user)
    for ctx, role_id in db.execute(
        select(AccessBinding.context, AccessBinding.role_id).where(
            AccessBinding.user_id == user.id, AccessBinding.role_id.in_(ids)
        )
    ):
        if system and ctx == "system":
            return True
        if (
            not system
            and ctx.startswith("tenant:")
            and ac.can_access(db, user, int(ctx.split(":")[1]))
        ):
            return True
    if system:
        return False
    # Only unconverted legacy memberships need fallback; managed rows were checked above.
    for m in db.scalars(
        select(Membership)
        .outerjoin(
            ResourceAccess,
            (ResourceAccess.user_id == Membership.user_id)
            & (ResourceAccess.tenant_id == Membership.tenant_id),
        )
        .where(
            Membership.user_id == user.id,
            Membership.active.is_(True),
            or_(
                ResourceAccess.user_id.is_(None),
                ResourceAccess.roles_managed.is_(False),
            ),
        )
    ):
        if ac.can_access(db, user, m.tenant_id) and any(
            r.id in ids for r in ac.roles_for(db, user, m.tenant_id)
        ):
            return True
    return False


def needs_mfa(db, user):
    return enabled_totp(db, user.id) or required_mfa(db, user)


def event(db, user, action, **details):
    target = details.pop("target_id", details.get("user_id", user.id))
    audit(db, SimpleNamespace(user=user), "auth09." + action, target, **details)


def recent(who, db, require_mfa=False):
    t = who.session.reauthenticated_at
    if (
        not t
        or t < now() - timedelta(minutes=5)
        or (needs_mfa(db, who.user) or require_mfa)
        and not who.session.mfa_verified
    ):
        raise HTTPException(
            403,
            "Friss újraazonosítás szükséges a Biztonság oldalon (jelszó és beállított második faktor, vagy ellenőrzött passkey).",
        )


def verify_factor(db, user, code):
    import pyotp

    device = db.get(TotpDevice, user.id, populate_existing=True, with_for_update=True)
    if device and device.enabled and code.isdigit() and len(code) == 6:
        counter = int(time.time()) // 30
        totp = pyotp.TOTP(decrypt(device.secret))
        for step in [counter, counter - 1, counter + 1]:
            if step > device.last_counter and hmac.compare_digest(
                totp.at(step * 30), code
            ):
                device.last_counter = step
                return True
    row = db.get(
        RecoveryCode,
        (user.id, digest(code.replace("-", "").strip().upper())),
        with_for_update=True,
        populate_existing=True,
    )
    if row and row.used_at is None:
        row.used_at = now()
        event(db, user, "recovery_used")
        return True
    event(db, user, "mfa_failed")
    db.commit()
    return False


def new_recovery(db, user):
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [secrets.token_hex(10).upper() for _ in range(10)]
    for c in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=digest(c)))
    return codes


def issue_session(db, user, request, response, method="password", mfa=False):
    if not user.active:
        raise HTTPException(401, "A fiók nem használható.")
    from app.api import memberships

    choices = memberships(db, user.id)
    tenant_id = (
        choices[0]["tenant_id"]
        if len(choices) == 1 and not ac.is_system(db, user)
        else None
    )
    token = secrets.token_hex(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
    hours = config(db, "security")["session_hours"]
    db.add(
        LoginSession(
            token_hash=digest(token),
            user_id=user.id,
            tenant_id=tenant_id,
            expires_at=now() + timedelta(hours=hours),
            auth_method=method,
            mfa_verified=mfa,
            reauthenticated_at=now(),
        )
    )
    audit(
        db,
        SimpleNamespace(user=user),
        "auth.login",
        user.id,
        tenant_id,
        method=method,
        mfa=mfa,
    )
    db.commit()
    import os

    response.set_cookie(
        COOKIE,
        token,
        max_age=hours * 3600,
        secure=os.getenv("COOKIE_SECURE", "true").lower() != "false",
        httponly=True,
        samesite="strict",
        path="/",
    )
    return {"csrf_token": csrf_for(token)}


def complete_login(db, user, request, response, method, uv=False):
    accepted = uv and config(db, "mfa")["passkey_mfa"] and not user.mfa_reset_required
    if needs_mfa(db, user) and not accepted:
        token = challenge(db, "mfa_login", user.id, {"method": method})
        db.commit()
        return {
            "mfa_required": True,
            "enrollment_required": not enabled_totp(db, user.id),
            "mfa_token": token,
        }
    return issue_session(db, user, request, response, method, accepted)
