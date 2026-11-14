import fcntl
import hashlib
import hmac
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
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

# scrypt parameters are part of the stored hash contract: changing them would
# invalidate existing passwords. One derivation needs 128 * r * N = 128 MiB.
SCRYPT_N = 131072
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 268435456


class HashCapacityError(HTTPException):
    """All password-hash slots are busy; the client should retry shortly."""

    def __init__(self, retry_after=5):
        super().__init__(
            503,
            "A szerver most túlterhelt. Próbáld újra néhány másodperc múlva.",
            headers={"Retry-After": str(retry_after)},
        )


def _hash_slots():
    return max(1, int(os.getenv("SCRYPT_CONCURRENCY", "2")))


def _hash_queue_timeout():
    return max(0.0, float(os.getenv("SCRYPT_QUEUE_TIMEOUT", "5")))


def _hash_lock_dir():
    return os.getenv(
        "SCRYPT_LOCK_DIR", os.path.join(tempfile.gettempdir(), "adatdusito-scrypt")
    )


@contextmanager
def hash_slot():
    """Bound concurrent scrypt work across threads AND processes.

    Each slot is an advisory flock() on its own file. flock() conflicts between
    separate open file descriptions, so threads of one Uvicorn worker and
    several worker processes (``--workers`` / WEB_CONCURRENCY) sharing the
    container's temp directory all compete for the same SCRYPT_CONCURRENCY
    slots. The kernel releases a slot automatically if a process dies.
    """
    slots = _hash_slots()
    deadline = time.monotonic() + _hash_queue_timeout()
    directory = _hash_lock_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    while True:
        for index in range(slots):
            fd = os.open(
                os.path.join(directory, f"slot-{index}.lock"),
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            return
        if time.monotonic() >= deadline:
            raise HashCapacityError()
        time.sleep(0.02)


def _scrypt(password, salt):
    with hash_slot():
        return hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            maxmem=SCRYPT_MAXMEM,
        )


def hash_password(password):
    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password, encoded):
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt)
    except (ValueError, TypeError, AttributeError):
        return False
    # Malformed hashes are rejected before taking a slot; capacity errors propagate.
    try:
        actual = _scrypt(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual.hex(), expected)


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
