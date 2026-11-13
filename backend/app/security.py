import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from redis import Redis
from app.db import engine
from app.models import (
    Audit,
    LoginSession,
    Membership,
    RolePermission,
    Tenant,
    User,
    now,
)

COOKIE = "adatdusito_session"


def hash_password(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=131072, r=8, p=1, maxmem=268435456
    )
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password, encoded):
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=131072,
            r=8,
            p=1,
            maxmem=268435456,
        )
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hmac.new(token.encode(), b"adatdusito-csrf-v1", hashlib.sha256).hexdigest()


def database():
    with Session(engine()) as db:
        yield db


def limit_login(request: Request, email: str):
    # Trust only the socket peer, never arbitrary forwarded headers. The frontend
    # proxy is shared; the broad peer bucket is therefore intentionally generous.
    try:
        redis = Redis.from_url(
            os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
        )
        keys = [
            (f"login:account:{digest(email)}", 10),
            (
                f"login:peer:{digest(request.client.host if request.client else 'unknown')}",
                300,
            ),
        ]
        for key, maximum in keys:
            # Atomic increment+expiry; survives multiple API workers.
            count = redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],900) end; return n",
                1,
                key,
            )
            if count > maximum:
                raise HTTPException(
                    429,
                    "Túl sok belépési kísérlet. Próbáld újra 15 perc múlva.",
                    headers={"Retry-After": "900"},
                )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "A bejelentkezés átmenetileg nem elérhető.")


@dataclass
class Identity:
    user: User
    session: LoginSession
    role: str | None
    permissions: set[str]
    token: str


def identity(request: Request, db: Session = Depends(database)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(token)) if len(token) == 64 else None
    if not session or session.expires_at <= now():
        raise HTTPException(401, "Bejelentkezés szükséges.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "A munkamenet érvénytelen.")
    role = "superadmin" if user.superadmin else None
    if session.tenant_id is not None:
        tenant = db.get(Tenant, session.tenant_id)
        member = db.get(Membership, (session.tenant_id, user.id))
        if (
            not tenant
            or not tenant.active
            or (not user.superadmin and (not member or not member.active))
        ):
            # The user can still log out or select another valid membership.
            session.tenant_id = None
            db.commit()
            member = None
        if not user.superadmin:
            role = member.role if member and session.tenant_id else None
    permissions = (
        set(
            db.scalars(
                select(RolePermission.permission).where(RolePermission.role == role)
            )
        )
        if role
        else set()
    )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", "").encode(), csrf_for(token).encode()
        ):
            raise HTTPException(403, "Érvénytelen CSRF-token.")
    return Identity(user, session, role, permissions, token)


def require(permission):
    def check(who: Identity = Depends(identity)):
        if permission not in who.permissions:
            raise HTTPException(403, "Nincs jogosultság ehhez a művelethez.")
        return who

    return check


def scope(who, tenant_id):
    if not who.user.superadmin and who.session.tenant_id != tenant_id:
        raise HTTPException(404, "Az ügyfél nem található.")


def audit(db, who, action, target, tenant_id=None, **details):
    db.add(
        Audit(
            actor_id=who.user.id if who else None,
            tenant_id=tenant_id,
            action=action,
            target=str(target),
            details=details,
        )
    )


def revoke(db, user_id):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
