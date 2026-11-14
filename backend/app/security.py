import hashlib
import hmac
import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session
from redis import Redis
from app.db import engine
from app.models import (
    Audit,
    LoginSession,
    User,
    now,
)

COOKIE = "adatdusito_session"
rate_configuration = ContextVar("rate_configuration", default={})


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
        policy = rate_configuration.get()
        attempts = policy.get("login_attempts", 10)
        window = policy.get("login_window_minutes", 15) * 60
        keys = [
            (f"login:account:{digest(email)}", attempts),
            (
                f"login:peer:{digest(request.client.host if request.client else 'unknown')}",
                max(300, attempts * 30),
            ),
        ]
        for key, maximum in keys:
            # Atomic increment+expiry; survives multiple API workers.
            count = redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                1,
                key,
                window,
            )
            if count > maximum:
                raise HTTPException(
                    429,
                    "Túl sok belépési kísérlet. Próbáld újra a korlátozási idő lejárta után.",
                    headers={"Retry-After": str(window)},
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
    roles: list = field(default_factory=list)
    permission_sources: dict = field(default_factory=dict)
    system: bool = False
    full_resources: bool = True


def identity(request: Request, db: Session = Depends(database)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(token)) if len(token) == 64 else None
    if not session or session.expires_at <= now():
        raise HTTPException(401, "Bejelentkezés szükséges.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "A munkamenet érvénytelen.")
    from app.system_config import config
    from app.auth_service import needs_mfa
    from datetime import timedelta

    policy = config(db, "security")
    if session.created_at + timedelta(hours=policy["session_hours"]) <= now():
        raise HTTPException(401, "A munkamenet lejárt.")
    mfa_pending = needs_mfa(db, user) and not session.mfa_verified
    restricted = mfa_pending or user.must_change_password
    safe_paths = {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/password",
        "/api/v1/auth/security",
        "/api/v1/auth/reauth",
        "/api/v1/auth/totp/setup",
        "/api/v1/auth/totp/confirm",
        "/api/v1/auth/passkeys/login/options",
        "/api/v1/auth/passkeys/login/verify",
    }
    if restricted and request.url.path not in safe_paths:
        raise HTTPException(
            403, "A folytatáshoz jelszócsere vagy második faktor beállítása szükséges."
        )
    from app.access_control import (
        can_access,
        effective,
        roles_for,
        is_system,
        full_resources,
    )

    if session.tenant_id is not None and not can_access(db, user, session.tenant_id):
        session.tenant_id = None
        db.commit()
    permissions, sources = effective(db, user, session.tenant_id)
    if restricted:
        permissions = set()
    if session.tenant_id is not None:
        from app.models import Tenant

        tenant = db.get(Tenant, session.tenant_id)
        if tenant and tenant.onboarding_state == "pending_subscription":
            permissions &= {
                "reference.read",
                "tenants.read",
                "companies.read",
                "webshops.read",
            }
            for code, source in sources.items():
                if code not in permissions:
                    source.update(allowed=False, scope="pending_subscription")
    roles = roles_for(db, user, session.tenant_id)
    role = (
        "superadmin"
        if user.superadmin
        else (roles[0].legacy_code or roles[0].code)
        if roles
        else None
    )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", "").encode(), csrf_for(token).encode()
        ):
            raise HTTPException(403, "Érvénytelen CSRF-token.")
    result = Identity(user, session, role, permissions, token)
    result.mfa_required = mfa_pending
    result.roles = [{"id": r.id, "code": r.code, "name": r.name} for r in roles]
    result.permission_sources = sources
    result.system = is_system(db, user)
    result.full_resources = full_resources(db, result)
    return result


def require(permission):
    def check(who: Identity = Depends(identity)):
        if permission not in who.permissions:
            raise HTTPException(403, "Nincs jogosultság ehhez a művelethez.")
        if (
            who.session.tenant_id is not None
            and not who.full_resources
            and (
                permission.startswith(("imports.", "products."))
                or permission in {"exports.profile", "audit.read"}
            )
        ):
            raise HTTPException(
                403,
                "A jelenlegi adatok még nem kapcsolódnak céghez/webáruházhoz; teljes ügyfél-hozzáférés szükséges.",
            )
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
