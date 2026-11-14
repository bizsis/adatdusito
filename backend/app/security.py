import fcntl
import hashlib
import hmac
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import ip_address, ip_network
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
# Security policy (system_config "security") for the current request; set by
# app.auth_api.throttle() and the password login.
rate_configuration = ContextVar("rate_configuration", default={})

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


DEFAULT_TRUSTED_PROXIES = "127.0.0.0/8,::1/128,172.16.0.0/12"


@lru_cache(maxsize=8)
def _networks(spec):
    return tuple(
        ip_network(part.strip(), strict=False) for part in spec.split(",") if part.strip()
    )


def _ip(value):
    address = ip_address(value.strip())
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address


def client_ip(request: Request):
    """Real client address behind the reverse-proxy chain.

    Forwarded headers are only honoured when the socket peer is a trusted proxy
    (TRUSTED_PROXY_CIDRS; default loopback + Docker's 172.16.0.0/12). The
    X-Forwarded-For chain is then walked from the right, skipping trusted hops;
    the first untrusted address is the client. Entries left of it are
    client-controlled and ignored, so a spoofed header cannot pick the bucket.
    """
    peer = request.client.host if request.client else ""
    try:
        candidate = _ip(peer)
    except ValueError:
        return peer or "unknown"
    trusted = _networks(os.getenv("TRUSTED_PROXY_CIDRS", DEFAULT_TRUSTED_PROXIES))

    def is_trusted(address):
        return any(address in network for network in trusted)

    if not is_trusted(candidate):
        return str(candidate)
    chain = [
        part
        for header in request.headers.getlist("x-forwarded-for")
        for part in header.split(",")
        if part.strip()
    ]
    if not chain and request.headers.get("x-real-ip"):
        chain = [request.headers["x-real-ip"]]
    for raw in reversed(chain):
        try:
            candidate = _ip(raw)
        except ValueError:
            break  # Malformed hop: stop at the last trusted address.
        if not is_trusted(candidate):
            break
    return str(candidate)


LOGIN_WINDOW = 900
_HIT = (
    "local n=redis.call('INCR',KEYS[1]); "
    "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
)


def _redis():
    return Redis.from_url(
        os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
    )


def _hit(redis, key, ttl=LOGIN_WINDOW):
    # Atomic increment+expiry; survives multiple API workers.
    return int(redis.eval(_HIT, 1, key, ttl))


def _too_many(retry_after=LOGIN_WINDOW):
    return HTTPException(
        429,
        "Túl sok belépési kísérlet. Próbáld újra később.",
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def _remaining(redis, key, default):
    """Seconds until the counter expires, for Retry-After."""
    try:
        ttl = int(redis.ttl(key))
    except Exception:
        return default
    return ttl if ttl > 0 else default


def _policy():
    """Configured attempts/window (system settings "security"), with defaults."""
    policy = rate_configuration.get()
    attempts = int(policy.get("login_attempts", 10))
    window = int(policy.get("login_window_minutes", 15)) * 60
    return attempts, window


def limit_login(request: Request, email: str, per_client: bool = False):
    """Generic attempt throttle for auth flows other than password login.

    ``email`` is the subject key (user id, challenge token, ...). Subjects that
    are not specific to a user or token (e.g. "passkey-begin") must use
    ``per_client=True``: a shared key would let anyone exhaust it and deny the
    flow to every user. Limits follow the configurable security policy.
    """
    attempts, window = _policy()
    try:
        redis = _redis()
        ip = client_ip(request)
        subject = f"{email}|{ip}" if per_client else email
        keys = [
            (f"login:account:{digest(subject)}", attempts),
            (f"login:peer:{digest(ip)}", max(300, attempts * 30)),
        ]
        for key, maximum in keys:
            if _hit(redis, key, window) > maximum:
                raise _too_many(_remaining(redis, key, window))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "A bejelentkezés átmenetileg nem elérhető.")


def limit_failures(request: Request, key: str, record: bool = False):
    """Failure-only budget per subject and client address.

    Call with record=False before verifying a secret (refuses once the budget
    is spent, so the guess is never evaluated) and with record=True after a
    failed verification. Successful attempts are free, so a legitimate user is
    not throttled by their own logins. Uses the configurable policy.
    """
    attempts, window = _policy()
    counter = f"login:fail:subject:{digest(key + '|' + client_ip(request))}"
    try:
        redis = _redis()
        if record:
            _hit(redis, counter, window)
        elif int(redis.get(counter) or 0) >= attempts:
            raise _too_many(_remaining(redis, counter, window))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "A bejelentkezés átmenetileg nem elérhető.")


class LoginGuard:
    """Progressive, risk-based password-login protection.

    Counters (policy window, default 15 minutes; Redis, shared by all workers):
    - account+IP attempts (policy login_attempts, default 10): the main brute-force brake. Only the attacker's own
      address is blocked, so a remote attacker cannot lock the owner out.
      Cleared on successful login.
    - IP attempts / IP failures: one address spraying many accounts.
    - account failures from all addresses (distributed guessing). This never
      produces an account-wide denial: any global "refuse this account" switch
      could be tripped by an attacker and would lock the owner out of every
      new network (mobile, travel, expired KNOWN_TTL). Instead the per-address
      attempt budget for addresses never used successfully with this account
      shrinks as the attack grows: 10 normally, 3 from ACCOUNT_ELEVATED
      failures, 1 per hour (SEVERE_WINDOW) from ACCOUNT_SEVERE failures.
      The owner's first correct attempt from a new address therefore always
      gets through (unless that address itself is throttled by the per-IP
      counters, e.g. shared with an attacker behind CGNAT); known addresses
      ("known" email+IP pairs, 30 days) keep the normal budget of 10.

    Trade-off: an attacker controlling many addresses can still make one
    guess per address per window during a severe attack. That cost is bounded
    by the per-IP counters (300 attempts / 30 failures), the scrypt slot limit
    and the 12-character minimum password length; availability for the
    legitimate owner is preferred over a hard account lock. Stronger
    protection against large botnets requires a second factor, not a lock.
    """

    PAIR_LIMIT = 10
    PAIR_LIMIT_ELEVATED = 3
    PAIR_LIMIT_SEVERE = 1
    IP_ATTEMPTS = 300
    IP_FAILURES = 30
    ACCOUNT_ELEVATED = 20
    ACCOUNT_SEVERE = 100
    SEVERE_WINDOW = 3600
    KNOWN_TTL = 30 * 24 * 3600

    def __init__(self, redis, email, ip, attempts=None, window=None):
        self.redis = redis
        # Configurable security policy (CODEX 09 settings: login_attempts 3-20,
        # login_window_minutes 5-60); class constants are the defaults.
        if attempts is not None:
            self.PAIR_LIMIT = int(attempts)
            self.PAIR_LIMIT_ELEVATED = min(self.PAIR_LIMIT_ELEVATED, self.PAIR_LIMIT)
            self.IP_ATTEMPTS = max(self.IP_ATTEMPTS, self.PAIR_LIMIT * 30)
        self.window = int(window) if window else LOGIN_WINDOW
        self.severe_window = max(self.SEVERE_WINDOW, self.window)
        account, address = digest(email), digest(ip)
        self.pair = f"login:pair:{digest(account + '|' + address)}"
        self.known = f"login:known:{digest(account + '|' + address)}"
        self.account = f"login:fail:account:{account}"
        self.ip_failures = f"login:fail:peer:{address}"
        self.ip_attempts = f"login:peer:{address}"

    def _block(self, key):
        ttl = self.redis.ttl(key)
        raise _too_many(ttl if ttl and ttl > 0 else self.window)

    def _safely(self, operation):
        try:
            return operation()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "A bejelentkezés átmenetileg nem elérhető.")

    def check(self):
        def run():
            r = self.redis
            known = r.get(self.known) is not None
            failures = int(r.get(self.account) or 0)
            if _hit(r, self.ip_attempts, self.window) > self.IP_ATTEMPTS:
                self._block(self.ip_attempts)
            if int(r.get(self.ip_failures) or 0) >= self.IP_FAILURES:
                self._block(self.ip_failures)
            limit = self.pair_limit(known, failures)
            # A severe attack also stretches a fresh unknown address's window,
            # so each attacking address gets one guess per hour, not per 15 min.
            severe = limit == self.PAIR_LIMIT_SEVERE and not known
            window = self.severe_window if severe else self.window
            if _hit(r, self.pair, window) > limit:
                self._block(self.pair)

        self._safely(run)

    def pair_limit(self, known, failures):
        if known or failures < self.ACCOUNT_ELEVATED:
            return self.PAIR_LIMIT
        if failures < self.ACCOUNT_SEVERE:
            return self.PAIR_LIMIT_ELEVATED
        return self.PAIR_LIMIT_SEVERE

    def failure(self):
        def run():
            _hit(self.redis, self.account, self.window)
            _hit(self.redis, self.ip_failures, self.window)

        self._safely(run)

    def success(self):
        # Only this address's counter is cleared: the account-wide and
        # per-IP failure counters describe other actors and must survive.
        def run():
            self.redis.delete(self.pair)
            self.redis.set(self.known, "1", ex=self.KNOWN_TTL)

        self._safely(run)


def login_guard(request: Request, subject: str):
    """LoginGuard for the password login, using the current security policy.

    ``subject`` identifies the account (``user:<id>`` when it exists, so email
    and username logins share counters; otherwise the normalized identifier).
    """
    attempts, window = _policy()
    try:
        redis = _redis()
    except Exception:
        raise HTTPException(503, "A bejelentkezés átmenetileg nem elérhető.")
    return LoginGuard(redis, subject, client_ip(request), attempts, window)


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
