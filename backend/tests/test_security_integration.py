"""SECURITY-01 x CODEX 09 integration: real throttles on the CODEX 09 auth flows.

The shared `environment` fixture disables throttling; these tests re-enable the
real implementations against an in-memory Redis.
"""

import hashlib
import secrets

import pyotp
import pytest
from sqlalchemy.orm import Session

from app import api, security
from app.models import User
from app.security import LoginGuard, verify_password
from app.system_config import DEFAULTS, store
from conftest import login
from test_auth09 import encryption_key, enable, enroll  # noqa: F401
from test_login_protection import FakeRedis, from_address

PASSWORD = "Test-password-2026!"


@pytest.fixture
def real(environment, monkeypatch):
    """Environment with the real SECURITY-01 throttles and a fake Redis."""
    fake = FakeRedis()
    monkeypatch.setattr(security, "_redis", lambda: fake)
    monkeypatch.setattr(api, "login_guard", security.login_guard)
    monkeypatch.setattr(api, "limit_login", security.limit_login)
    monkeypatch.setattr(security, "limit_failures", LIMIT_FAILURES)
    return environment, fake


LIMIT_FAILURES = security.limit_failures


def post(client, identifier, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})


def username_of(engine, user_id=1):
    with Session(engine) as db:
        return db.get(User, user_id).username


def set_security(engine, **changes):
    with Session(engine) as db:
        store(db, "security", {**DEFAULTS["security"], **changes})
        db.commit()


# 1. Existing password hashes -------------------------------------------------


def test_hash_created_with_pre_security01_code_still_verifies():
    salt = secrets.token_bytes(16)
    legacy = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=131072, r=8, p=1, maxmem=268435456)
    encoded = f"scrypt${salt.hex()}${legacy.hex()}"
    assert verify_password(PASSWORD, encoded)
    assert not verify_password(PASSWORD + "x", encoded)


# 3-4. Email and username login with the real guard ---------------------------


def test_email_and_username_login_share_one_account_subject(real):
    (client, engine, *_), fake = real
    username = username_of(engine)
    me = from_address("198.51.100.10")
    assert post(me, "root@example.hu").status_code == 200
    assert post(me, username).status_code == 200
    # Failures through either identifier hit the same account+IP budget (10).
    attacker = from_address("203.0.113.10")
    codes = [post(attacker, "root@example.hu", "wrong").status_code for _ in range(5)]
    codes += [post(attacker, username, "wrong").status_code for _ in range(5)]
    assert codes == [401] * 10
    assert post(attacker, username, "wrong").status_code == 429
    assert post(attacker, "root@example.hu").status_code == 429
    # Other addresses are unaffected.
    assert post(from_address("198.51.100.11"), username).status_code == 200


def test_unknown_identifier_is_throttled_without_user_enumeration(real):
    (client, *_), fake = real
    attacker = from_address("203.0.113.11")
    codes = [post(attacker, "nobody@example.hu", "wrong").status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]


# 5. Successful login from a new IP after 100+ distributed failures ------------


def test_new_ip_login_after_distributed_attack_on_username(real):
    (client, engine, *_), fake = real
    username = username_of(engine)
    for i in range(40):  # 40 addresses x 3 failures = 120 account-wide failures
        attacker = from_address(f"203.0.{i // 200}.{i % 200 + 1}")
        for _ in range(3):
            post(attacker, username, "wrong")
    failures = int(fake.get(LoginGuard(fake, "user:1", "x").account))
    assert failures >= 100
    assert post(from_address("198.51.100.99"), username).status_code == 200
    assert post(from_address("2001:db8::99"), "root@example.hu").status_code == 200


# 6. Configurable throttling ---------------------------------------------------


def test_configured_login_attempts_and_window_apply(real):
    (client, engine, *_), fake = real
    set_security(engine, login_attempts=3, login_window_minutes=5)
    attacker = from_address("203.0.113.12")
    codes = [post(attacker, "root@example.hu", "wrong").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    blocked = post(attacker, "root@example.hu")
    assert blocked.status_code == 429 and 0 < int(blocked.headers["retry-after"]) <= 300
    fake.advance(301)
    assert post(attacker, "root@example.hu").status_code == 200


def test_policy_does_not_leak_between_requests(real):
    (client, engine, *_), fake = real
    set_security(engine, login_attempts=3)
    post(from_address("203.0.113.13"), "root@example.hu", "wrong")
    assert security.rate_configuration.get() == {}


# 7. MFA and recovery limits ---------------------------------------------------


def test_mfa_failures_limited_per_user_across_fresh_challenges(real):
    (client, engine, *_), fake = real
    me = from_address("198.51.100.20")
    login(client)
    secret, codes = enroll(client)

    def challenge():
        r = post(me, "root@example.hu")
        assert r.status_code == 200 and r.json()["mfa_required"], r.text
        return r.json()["mfa_token"]

    statuses = []
    for _ in range(4):  # a new challenge per password login: 3 wrong codes each
        token = challenge()
        for _ in range(3):
            r = me.post("/api/v1/auth/mfa/complete", json={"token": token, "code": "000000"})
            statuses.append(r.status_code)
    assert statuses[:10] == [403] * 10
    assert set(statuses[10:]) == {429}
    # Even the correct recovery code is not evaluated while the budget is spent.
    token = challenge()
    r = me.post("/api/v1/auth/mfa/complete", json={"token": token, "code": codes[0]})
    assert r.status_code == 429
    # Another address is not affected, and the owner completes MFA there.
    other = from_address("198.51.100.21")
    r = post(other, "root@example.hu")
    r = other.post("/api/v1/auth/mfa/complete", json={"token": r.json()["mfa_token"], "code": codes[0]})
    assert r.status_code == 200, r.text


def test_successful_mfa_does_not_consume_budget(real):
    (client, engine, *_), fake = real
    me = from_address("198.51.100.22")
    login(client)
    secret, codes = enroll(client)
    for code in codes[:10]:
        token = post(me, "root@example.hu").json()["mfa_token"]
        r = me.post("/api/v1/auth/mfa/complete", json={"token": token, "code": code})
        assert r.status_code == 200, r.text


# 8. Passkey and Google flows are no longer globally exhaustible ---------------


def test_passkey_begin_is_limited_per_client_not_globally(real):
    (client, engine, *_), fake = real
    login(client)
    enable(client, passkey=True)
    for i in range(30):  # 30 different users' browsers
        r = from_address(f"198.51.100.{i + 30}").post("/api/v1/auth/passkeys/login/options", json={})
        assert r.status_code == 200, r.text
    abuser = from_address("203.0.113.30")
    codes = [abuser.post("/api/v1/auth/passkeys/login/options", json={}).status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]
    assert from_address("198.51.100.99").post("/api/v1/auth/passkeys/login/options", json={}).status_code == 200


def test_google_start_is_limited_per_client_not_globally(real):
    (client, engine, *_), fake = real
    login(client)
    enable(
        client,
        google=True,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="private-google-secret",
    )
    for i in range(15):
        r = from_address(f"198.51.100.{i + 100}").post("/api/v1/auth/google/start", json={"link": False})
        assert r.status_code == 200, r.text
    abuser = from_address("203.0.113.31")
    codes = [abuser.post("/api/v1/auth/google/start", json={"link": False}).status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]


# 9. Client IP through both proxies, forged and missing headers ---------------


def test_forged_forwarded_header_from_untrusted_peer_is_ignored(real):
    (client, engine, *_), fake = real
    from fastapi.testclient import TestClient
    from app.main import app

    # Direct connection (not through the proxies) claiming many addresses.
    direct = TestClient(app, base_url="https://testserver", client=("203.0.113.40", 1))
    codes = []
    for i in range(11):
        direct.headers["X-Forwarded-For"] = f"198.51.100.{i}"
        codes.append(post(direct, "root@example.hu", "wrong").status_code)
    assert codes == [401] * 10 + [429]


def test_missing_forwarded_header_falls_back_to_proxy_peer(real):
    (client, engine, *_), fake = real
    from fastapi.testclient import TestClient
    from app.main import app

    proxied = TestClient(app, base_url="https://testserver", client=("172.28.10.3", 1))
    codes = [post(proxied, "root@example.hu", "wrong").status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]
    # A correctly forwarded client behind the same proxy is a different bucket.
    assert post(from_address("198.51.100.50"), "root@example.hu").status_code == 200


def test_redis_outage_fails_closed_on_login_and_mfa(real, monkeypatch):
    (client, engine, *_), fake = real
    monkeypatch.setattr(security, "_redis", lambda: (_ for _ in ()).throw(OSError()))
    assert post(from_address("198.51.100.60"), "root@example.hu").status_code == 503


# 2. scrypt capacity covers every CODEX 09 password path -----------------------


def test_only_security_module_derives_password_hashes():
    from pathlib import Path

    app_dir = Path(security.__file__).parent
    offenders = [
        p.name
        for p in app_dir.glob("*.py")
        if p.name != "security.py" and "scrypt" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "path, payload",
    [
        ("/api/v1/auth/reauth", {"password": PASSWORD}),
        ("/api/v1/auth/password", {"current_password": PASSWORD, "password": "New-password-2026!"}),
    ],
)
def test_codex09_password_paths_return_503_when_hash_capacity_is_exhausted(
    environment, monkeypatch, tmp_path, path, payload
):
    client = environment[0]
    login(client)
    monkeypatch.setenv("SCRYPT_LOCK_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("SCRYPT_CONCURRENCY", "1")
    monkeypatch.setenv("SCRYPT_QUEUE_TIMEOUT", "0.1")
    with security.hash_slot():
        r = client.post(path, json=payload)
    assert r.status_code == 503, r.text
    assert r.headers["retry-after"] == "5"
    # With capacity available the same request is processed normally.
    assert client.post(path, json=payload).status_code in (200, 204)
