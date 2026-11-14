"""Opt-in email-verified onboarding; no synthetic trial/subscription entitlement."""

import os
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from redis import Redis
from app.security import database, hash_password
from app.models import User, Tenant, Membership
from app.auth_service import challenge, consume, event
from app.auth_api import throttle
from app.system_config import config, password_policy
from app.mail_service import transport

router = APIRouter(prefix="/api/v1/auth/register", tags=["E-mailes regisztráció"])


def quota(request):
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    from app.security import digest

    peer = digest(request.client.host if request.client else "unknown")
    try:
        r = Redis.from_url(
            os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
        )
        for key, maximum in [
            (f"registration:day:{day}", 100),
            (f"registration:peer:{day}:{peer}", 10),
        ]:
            n = r.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],172800) end; return n",
                1,
                key,
            )
            if n > maximum:
                raise HTTPException(
                    429, "A regisztrációs keret átmenetileg elfogyott. Próbáld később."
                )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            503, "A regisztráció visszaélésvédelme átmenetileg nem érhető el."
        ) from None


class Register(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    workspace: str = Field(min_length=1, max_length=120)


@router.post("")
def register(body: Register, request: Request, db: Session = Depends(database)):
    if not config(db, "auth")["registration"]:
        raise HTTPException(403, "A nyilvános regisztráció nincs engedélyezve.")
    email = body.email.strip().casefold()
    throttle(request, db, "register:" + email)
    quota(request)
    if (
        not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
        or not body.name.strip()
        or not body.workspace.strip()
    ):
        raise HTTPException(422, "Érvénytelen regisztrációs adatok.")
    password_policy(db, body.password)
    # Generic result for existing accounts: no enumeration, no automatic account merge.
    password_hash = hash_password(body.password)
    if not db.scalar(select(User.id).where(User.email == email)):
        token = challenge(
            db,
            "registration",
            payload={
                "email": email,
                "name": body.name.strip(),
                "workspace": body.workspace.strip(),
                "password_hash": password_hash,
            },
            minutes=60,
        )
        origin = os.getenv("APP_ORIGIN", "https://dev.pinfo.hu").rstrip("/")
        transport(
            db,
            email,
            "Adatdúsító – e-mail ellenőrzése",
            f"A regisztráció megerősítése: {origin}/#register={token}\n\nA link 60 percig érvényes. Ha nem te kezdeményezted, hagyd figyelmen kívül.",
        )
        db.commit()
    return {
        "message": "Ha a címhez új regisztráció indítható, elküldtük az ellenőrző levelet."
    }


class Confirm(BaseModel):
    token: str = Field(min_length=32, max_length=128)


@router.post("/confirm")
def confirm(body: Confirm, request: Request, db: Session = Depends(database)):
    if not config(db, "auth")["registration"]:
        raise HTTPException(403, "A regisztráció nincs engedélyezve.")
    throttle(request, db, "register-confirm")
    c = consume(db, body.token, ["registration"])
    if db.scalar(select(User.id).where(User.email == c.payload["email"])):
        raise HTTPException(409, "A fiók már létezik. Jelentkezz be.")
    user = User(
        email=c.payload["email"],
        email_verified=True,
        name=c.payload["name"],
        password_hash=c.payload["password_hash"],
    )
    db.add(user)
    db.flush()
    tenant = Tenant(
        name=c.payload["workspace"], onboarding_state="pending_subscription"
    )
    db.add(tenant)
    db.flush()
    db.add(
        Membership(
            user_id=user.id, tenant_id=tenant.id, role="tenant_admin", active=True
        )
    )
    from app.access_api import apply_user_access, UserAccessInput
    from app.access_models import AccessRole

    role = db.scalar(
        select(AccessRole.id).where(
            AccessRole.owner == "template", AccessRole.code == "tenant_admin"
        )
    )
    apply_user_access(db, user, UserAccessInput(roles=[role]), tenant.id, user.id)
    # Remove the password hash from consumed short-lived challenge payload immediately.
    c.payload = {"email": user.email, "user_id": user.id}
    event(db, user, "registration_verified", tenant_id=tenant.id)
    db.commit()
    return {
        "created": True,
        "message": "E-mail ellenőrizve, munkaterület létrehozva. Az előfizetés beállításáig a feldolgozási funkciók nem aktívak.",
    }
