"""Structured settings: actual live behavior, redacted secrets and lockout checks."""

import re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import User, Setting, Tenant
from app.auth_models import Passkey, ExternalIdentity, Configuration, SecretSetting
from app.access_models import AccessRole
from app.security import database, require, audit, digest
from app.auth_service import recent
from app.auth_api import throttle
from app.system_config import (
    config,
    store,
    get_secret,
    put_secret,
    cipher,
    validate_timezone,
)
from app import access_control as ac
from app import mail_service

router = APIRouter(prefix="/api/v1/system/settings", tags=["Rendszerbeállítások"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class General(Input):
    display_name: str = Field(min_length=1, max_length=80)
    system_name: str = Field(min_length=1, max_length=120)
    language: str = "hu"
    timezone: str = "Europe/Budapest"
    environment: str = "development"


class Auth(Input):
    password: bool = True
    google: bool = False
    passkey: bool = False
    google_client_id: str = Field(default="", max_length=254)
    google_client_secret: str | None = Field(default=None, max_length=2000)
    registration: bool = False


class Mfa(Input):
    enabled: bool = True
    required_roles: list[int] = Field(default_factory=list, max_length=1000)
    passkey_mfa: bool = True


class Security(Input):
    session_hours: int = Field(default=8, ge=1, le=24)
    login_attempts: int = Field(default=10, ge=3, le=20)
    login_window_minutes: int = Field(default=15, ge=5, le=60)
    password_min_length: int = Field(default=12, ge=12, le=64)
    invite_ttl_hours: int = Field(default=48, ge=1, le=168)


class Smtp(Input):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    security: str
    username: str = Field(default="", max_length=254)
    password: str | None = Field(default=None, max_length=2000)
    from_email: str = Field(max_length=254)
    from_name: str = Field(default="Adatdúsító", max_length=120)


class TestSmtp(Input):
    config: Smtp | None = None
    recipient: str | None = Field(default=None, max_length=254)


def ensure_admin_methods(db, p, exclude_passkey=None, exclude_identity=None):
    from app.models import Role

    db.scalar(select(Role).where(Role.code == "superadmin").with_for_update())
    verified = db.get(Configuration, "google_verified")
    google_valid = (
        bool(
            verified
            and verified.value.get("client_id") == p["google_client_id"]
            and verified.value.get("secret_hash")
            == digest(get_secret(db, "google.client_secret"))
        )
        if p["google"]
        else False
    )
    from app.auth_api import rp

    hostname = rp()[0] if p["passkey"] else None
    for u in db.scalars(
        select(User).where(User.superadmin.is_(True), User.active.is_(True))
    ):
        password = p["password"] and bool(u.password_hash)
        keys = p["passkey"] and db.scalar(
            select(Passkey.id).where(
                Passkey.user_id == u.id,
                Passkey.rp_id == hostname,
                Passkey.id != exclude_passkey if exclude_passkey is not None else True,
            )
        )
        google = (
            p["google"]
            and google_valid
            and db.scalar(
                select(ExternalIdentity.id).where(
                    ExternalIdentity.user_id == u.id,
                    ExternalIdentity.provider == "google",
                    ExternalIdentity.id != exclude_identity
                    if exclude_identity is not None
                    else True,
                )
            )
        )
        if not (password or keys or google):
            raise HTTPException(
                409,
                "A változtatás kizárna egy aktív superadmint. Előbb állíts be neki másik használható bejelentkezési módot.",
            )


def candidate_smtp(db, body):
    value = body.model_dump(exclude={"password"})
    if (
        body.security not in ["tls", "starttls"]
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.from_email)
        or any(c in body.from_name for c in "\r\n")
    ):
        raise HTTPException(422, "Érvénytelen levelezési beállítás.")
    current = mail_service.smtp_config(db)
    if (
        body.password is None
        and body.username
        and current["password"]
        and any(
            value[k] != current[k] for k in ["host", "port", "security", "username"]
        )
    ):
        raise HTTPException(
            422,
            "Másik SMTP-kiszolgálóhoz, porthoz vagy felhasználóhoz az új jelszót is meg kell adni; a tárolt titkot nem küldjük másik célra.",
        )
    value["password"] = (
        body.password if body.password is not None else current["password"]
    )
    if body.username and not value["password"]:
        raise HTTPException(422, "Az SMTP-felhasználóhoz jelszó szükséges.")
    value["source"] = "database"
    return value


@router.get("")
def read(who=Depends(require("system.settings.read")), db: Session = Depends(database)):
    a = config(db, "auth")
    # No secret decryption needed to display status, including when a key is missing.
    smtp_row = db.get(Configuration, "smtp")
    if smtp_row:
        smtp = {
            **smtp_row.value,
            "source": "database",
            "password_set": bool(db.get(SecretSetting, "smtp.password")),
        }
    else:
        smtp = {k: v for k, v in mail_service.smtp_config().items() if k != "password"}
        smtp["password_set"] = bool(mail_service.smtp_config()["password"])
    return {
        "general": config(db, "general"),
        "smtp": smtp,
        "auth": a
        | {"google_secret_set": bool(db.get(SecretSetting, "google.client_secret"))},
        "mfa": config(db, "mfa"),
        "security": config(db, "security"),
        "roles": [
            {
                "id": r.id,
                "name": r.name,
                "owner": r.owner,
                "protected": r.protected,
                "tenant_name": db.get(Tenant, int(r.owner.split(":")[1])).name
                if r.owner.startswith("tenant:")
                and db.get(Tenant, int(r.owner.split(":")[1]))
                else None,
            }
            for r in db.scalars(
                select(AccessRole).order_by(AccessRole.owner, AccessRole.name)
            )
            if not r.owner.startswith("tenant:")
            or ac.system_tenant_scope(db, who.user, int(r.owner.split(":")[1]))
        ],
    }


def log_change(db, who, group, before, after):
    audit(db, who, "settings09." + group, group, before=before, after=after)
    db.commit()


@router.put("/general")
def general(
    body: General,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    recent(who, db)
    if (
        body.language != "hu"
        or body.environment not in ["development", "production"]
        or not body.display_name.strip()
        or not body.system_name.strip()
    ):
        raise HTTPException(422, "Érvénytelen megjelenítési beállítás.")
    validate_timezone(body.timezone)
    before = config(db, "general")
    data = body.model_dump()
    store(db, "general", data)
    old = db.get(Setting, "display_name")
    if old:
        old.value = body.display_name
    else:
        db.add(Setting(key="display_name", value=body.display_name))
    log_change(db, who, "general", before, data)
    return data


@router.put("/smtp")
def smtp(
    body: Smtp,
    request: Request,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    recent(who, db)
    throttle(request, db, "smtp:" + str(who.user.id))
    cipher()  # validate external key before testing or overwriting anything
    value = candidate_smtp(db, body)
    mail_service.transport(db, candidate=value)
    before = {
        k: v for k, v in mail_service.public_smtp(db).items() if k != "password_set"
    }
    password = value.pop("password")
    if password:
        put_secret(db, "smtp.password", password)
    else:
        previous_secret = db.get(SecretSetting, "smtp.password")
        if previous_secret:
            db.delete(previous_secret)
    value.pop("source", None)
    store(db, "smtp", value)
    log_change(
        db, who, "smtp", before, value | {"password_changed": body.password is not None}
    )
    return {
        "saved": True,
        "message": "Ellenőrzött SMTP-beállítás mentve, újraindítás nélkül érvényes.",
    }


@router.post("/smtp/test")
def smtp_test(
    body: TestSmtp,
    request: Request,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    recent(who, db)
    throttle(request, db, "smtp:" + str(who.user.id))
    if body.recipient and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.recipient):
        raise HTTPException(422, "Érvénytelen címzett.")
    candidate = (
        candidate_smtp(db, body.config) if body.config else mail_service.smtp_config(db)
    )
    # Tests always use the public-target policy, even for environment defaults.
    result = mail_service.transport(
        db,
        body.recipient,
        "Adatdúsító – SMTP-teszt",
        "Ez egy üzemeltető által indított tesztlevél.",
        candidate=candidate,
    )
    audit(db, who, "settings09.smtp_test", "smtp", accepted=result["smtp_accepted"])
    db.commit()
    return result


@router.put("/auth")
def auth(
    body: Auth,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    ac.protected_admin(who)
    recent(who, db)
    # Serialize changes with protected-account transitions through the existing singleton.
    from app.models import Role

    db.scalar(select(Role).where(Role.code == "superadmin").with_for_update())
    before = config(db, "auth")
    data = body.model_dump(exclude={"google_client_secret"})
    if body.google:
        if not body.google_client_id.endswith(".apps.googleusercontent.com") or not (
            body.google_client_secret or get_secret(db, "google.client_secret")
        ):
            raise HTTPException(
                422, "A Google OIDC kliensazonosító és titok szükséges."
            )
        cipher()
    if body.registration:
        cipher()
        smtp = mail_service.smtp_config(db)
        if not smtp["host"] or not smtp["from_email"]:
            raise HTTPException(422, "Nyilvános regisztrációhoz működő SMTP szükséges.")
        mail_service.transport(db, candidate=smtp)
    if not data["password"] and (
        data["google_client_id"] != before["google_client_id"]
        or body.google_client_secret is not None
    ):
        for administrator in db.scalars(
            select(User).where(User.active.is_(True), User.superadmin.is_(True))
        ):
            if not (
                data["passkey"]
                and db.scalar(
                    select(Passkey.id).where(Passkey.user_id == administrator.id)
                )
            ):
                raise HTTPException(
                    409,
                    "Google-kliens módosításakor előbb engedélyezd a jelszavas tartalék bejelentkezést, vagy állíts be passkeyt minden superadminnak.",
                )
    ensure_admin_methods(db, data)
    if body.google_client_secret is not None:
        put_secret(db, "google.client_secret", body.google_client_secret)
    store(db, "auth", data)
    log_change(
        db,
        who,
        "auth",
        before,
        data | {"google_secret_changed": body.google_client_secret is not None},
    )
    return data


@router.put("/mfa")
def mfa(
    body: Mfa,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    ac.protected_admin(who)
    recent(who, db)
    from app.models import Role

    db.scalar(select(Role).where(Role.code == "superadmin").with_for_update())
    if body.required_roles:
        cipher()
        if not body.enabled:
            raise HTTPException(
                422, "Kötelező második faktor mellett az aktiválás nem tiltható le."
            )
    if set(body.required_roles) - set(db.scalars(select(AccessRole.id))):
        raise HTTPException(422, "Ismeretlen szerepkör.")
    before = config(db, "mfa")
    store(db, "mfa", body.model_dump())
    log_change(db, who, "mfa", before, body.model_dump())
    return body.model_dump()


@router.put("/security")
def security(
    body: Security,
    who=Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    ac.protected_admin(who)
    recent(who, db)
    before = config(db, "security")
    store(db, "security", body.model_dump())
    log_change(db, who, "security", before, body.model_dump())
    return body.model_dump()
