"""SECURITY-01/3: progressive login protection and real client IP detection."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import api, security
from app.main import app
from app.security import LoginGuard, client_ip

VICTIM = "root@example.hu"
PASSWORD = "Test-password-2026!"


class FakeRedis:
    """In-memory Redis subset with a controllable clock (eval = INCR+EXPIRE)."""

    def __init__(self):
        self.clock = 0.0
        self.data = {}
        self.expiry = {}

    def _alive(self, key):
        if key in self.expiry and self.expiry[key] <= self.clock:
            self.data.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.data

    def eval(self, script, numkeys, key, ttl):
        value = int(self.data[key]) + 1 if self._alive(key) else 1
        self.data[key] = value
        if value == 1:
            self.expiry[key] = self.clock + int(ttl)
        return value

    def get(self, key):
        return self.data[key] if self._alive(key) else None

    def set(self, key, value, ex=None):
        self.data[key] = value
        if ex:
            self.expiry[key] = self.clock + ex

    def delete(self, key):
        self.data.pop(key, None)
        self.expiry.pop(key, None)

    def ttl(self, key):
        if not self._alive(key):
            return -2
        return int(self.expiry[key] - self.clock) if key in self.expiry else -1

    def advance(self, seconds):
        self.clock += seconds


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(security, "_redis", lambda: fake)
    return fake


def attempt(redis, ip, ok=False, email=VICTIM):
    """One guarded login attempt; returns the HTTP status it would produce."""
    guard = LoginGuard(redis, email, ip)
    try:
        guard.check()
    except HTTPException as error:
        return error.status_code
    if ok:
        guard.success()
        return 200
    guard.failure()
    return 401


def request(peer, *headers):
    return Request(
        {
            "type": "http",
            "client": (peer, 40000),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        }
    )


# --- real client IP -------------------------------------------------------


def test_untrusted_peer_cannot_spoof_forwarded_headers(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    spoof = request("203.0.113.7", ("X-Forwarded-For", "1.1.1.1"), ("X-Real-IP", "1.1.1.1"))
    assert client_ip(spoof) == "203.0.113.7"


def test_trusted_proxy_chain_yields_rightmost_untrusted_address(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    # Outer Nginx appends $remote_addr to a client-supplied header.
    assert client_ip(request("172.28.10.3", ("X-Forwarded-For", "6.6.6.6, 198.51.100.4"))) == "198.51.100.4"
    # An extra trusted hop (e.g. Docker gateway) on the right is skipped.
    chain = ("X-Forwarded-For", "6.6.6.6, 198.51.100.4, 172.28.10.1")
    assert client_ip(request("172.28.10.3", chain)) == "198.51.100.4"
    assert client_ip(request("127.0.0.1", ("X-Real-IP", "198.51.100.9"))) == "198.51.100.9"
    assert client_ip(request("::ffff:172.28.10.3", ("X-Forwarded-For", "198.51.100.4"))) == "198.51.100.4"


def test_malformed_or_missing_headers_fall_back_to_last_trusted_hop(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert client_ip(request("172.28.10.3")) == "172.28.10.3"
    assert client_ip(request("172.28.10.3", ("X-Forwarded-For", "6.6.6.6, not-an-ip"))) == "172.28.10.3"
    assert client_ip(Request({"type": "http", "client": None, "headers": []})) == "unknown"


def test_trusted_proxies_are_configurable(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.9.0.0/16")
    assert client_ip(request("172.28.10.3", ("X-Forwarded-For", "198.51.100.4"))) == "172.28.10.3"
    assert client_ip(request("10.9.1.1", ("X-Forwarded-For", "198.51.100.4"))) == "198.51.100.4"


# --- guard behaviour ------------------------------------------------------


def test_email_ip_pair_is_blocked_after_ten_attempts(redis):
    assert [attempt(redis, "198.51.100.1") for _ in range(10)] == [401] * 10
    assert attempt(redis, "198.51.100.1") == 429
    assert attempt(redis, "198.51.100.1", ok=True) == 429


def test_targeted_attack_cannot_lock_out_the_owner(redis):
    for _ in range(200):
        attempt(redis, "203.0.113.66")
    # Owner on a never-seen address still gets in.
    assert attempt(redis, "198.51.100.20", ok=True) == 200


def test_success_clears_only_the_pair_counter(redis):
    for _ in range(9):
        attempt(redis, "198.51.100.1")
    assert attempt(redis, "198.51.100.1", ok=True) == 200
    assert [attempt(redis, "198.51.100.1") for _ in range(10)] == [401] * 10
    assert attempt(redis, "198.51.100.1") == 429
    # Account-wide failures from that address are retained (9 + 10).
    assert int(redis.get(LoginGuard(redis, VICTIM, "x").account)) == 19


def test_distributed_guessing_escalates_but_known_address_keeps_working(redis):
    assert attempt(redis, "198.51.100.20", ok=True) == 200  # owner's usual address
    statuses = []
    for i in range(60):
        ip = f"203.0.{i // 250}.{i % 250 + 1}"
        statuses += [attempt(redis, ip) for _ in range(5)]
    # Before 20 failures every address may try freely; afterwards only 3 tries.
    assert statuses[:20] == [401] * 20
    assert statuses[20:25] == [401, 401, 401, 429, 429]
    failures = int(redis.get(LoginGuard(redis, VICTIM, "x").account))
    assert failures >= LoginGuard.ACCOUNT_SEVERE
    # 100+ failures: a fresh address gets a single attempt per hour ...
    assert attempt(redis, "198.51.100.99") == 401
    assert attempt(redis, "198.51.100.99") == 429
    assert attempt(redis, "198.51.100.99", ok=True) == 429
    # The fresh address's window is stretched to one hour while the attack lasts.
    assert redis.ttl(LoginGuard(redis, VICTIM, "198.51.100.99").pair) == 3600
    # Once the account-wide counter expires (attack over), normal limits return.
    redis.advance(901)
    assert attempt(redis, "198.51.100.99", ok=True) == 200
    # ... while the known address keeps its normal budget.
    assert [attempt(redis, "198.51.100.20") for _ in range(9)] == [401] * 9
    assert attempt(redis, "198.51.100.20", ok=True) == 200


def distributed_attack(redis, failures=150):
    """Many attacker addresses, a few guesses each, until `failures` accumulate."""
    done = 0
    for i in range(failures * 2):  # bounded: a fresh address always gets >= 1 try
        if done >= failures:
            break
        ip = f"203.{i // 62500}.{i // 250 % 250}.{i % 250 + 1}"
        for _ in range(3):
            if attempt(redis, ip) == 401:
                done += 1
    assert done >= failures, "fresh attacker addresses were refused outright"
    return int(redis.get(LoginGuard(redis, VICTIM, "x").account))


def test_regression_owner_logs_in_from_unseen_address_after_100_distributed_failures(redis):
    """Vezér review on PR #1: no account-wide denial for never-seen addresses."""
    assert distributed_attack(redis) >= 100
    # Never-seen address, no prior success, correct password on first try.
    assert attempt(redis, "198.51.100.77", ok=True) == 200
    # And again from another unseen network (e.g. mobile), without waiting.
    assert attempt(redis, "2001:db8::1234", ok=True) == 200


def test_attack_volume_never_blocks_a_fresh_address_outright(redis):
    distributed_attack(redis, failures=1000)
    for n in range(20):
        assert attempt(redis, f"198.51.{100 + n}.7", ok=True) == 200


def test_single_address_spraying_many_accounts_is_blocked(redis):
    for i in range(30):
        assert attempt(redis, "203.0.113.5", email=f"user{i}@example.hu") == 401
    assert attempt(redis, "203.0.113.5", email="new@example.hu") == 429
    assert attempt(redis, "198.51.100.1", email="new@example.hu") == 401


def test_retry_after_reports_remaining_window(redis):
    for _ in range(10):
        attempt(redis, "198.51.100.1")
    redis.advance(600)
    with pytest.raises(HTTPException) as error:
        LoginGuard(redis, VICTIM, "198.51.100.1").check()
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "300"


def test_redis_outage_fails_closed(monkeypatch):
    class Broken:
        def __getattr__(self, name):
            raise ConnectionError("down")

    with pytest.raises(HTTPException) as error:
        LoginGuard(Broken(), VICTIM, "198.51.100.1").check()
    assert error.value.status_code == 503
    monkeypatch.setattr(security, "_redis", lambda: (_ for _ in ()).throw(OSError()))
    with pytest.raises(HTTPException) as error:
        security.login_guard(request("198.51.100.1"), VICTIM)
    assert error.value.status_code == 503


# --- end to end through the API ------------------------------------------


def from_address(ip):
    # Requests arrive from the frontend Nginx container with the outer proxy's header.
    client = TestClient(app, base_url="https://testserver", client=("172.28.10.3", 50000))
    client.headers["X-Forwarded-For"] = ip
    return client


def post_login(client, password):
    return client.post("/api/v1/auth/login", json={"email": VICTIM, "password": password})


def test_api_targeted_lockout_does_not_affect_owner(environment, redis, monkeypatch):
    monkeypatch.setattr(api, "login_guard", security.login_guard)
    attacker = from_address("203.0.113.66")
    codes = [post_login(attacker, "wrong-password").status_code for _ in range(12)]
    assert codes == [401] * 10 + [429] * 2
    blocked = post_login(attacker, PASSWORD)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert post_login(from_address("198.51.100.20"), PASSWORD).status_code == 200


def test_api_spoofed_forwarded_header_does_not_bypass_limit(environment, redis, monkeypatch):
    monkeypatch.setattr(api, "login_guard", security.login_guard)
    attacker = from_address("203.0.113.66")
    codes = []
    for i in range(12):
        attacker.headers["X-Forwarded-For"] = f"10.0.0.{i}, 203.0.113.66"
        codes.append(post_login(attacker, "wrong-password").status_code)
    assert codes[-1] == 429


def test_api_owner_logs_in_from_unseen_address_during_severe_attack(environment, redis, monkeypatch):
    monkeypatch.setattr(api, "login_guard", security.login_guard)
    for _ in range(150):  # 150 distributed failures already recorded for the account
        security._hit(redis, LoginGuard(redis, VICTIM, "x").account)
    # Severe mode is active: a fresh attacker address gets exactly one guess.
    attacker = from_address("203.0.113.200")
    assert post_login(attacker, "wrong-password").status_code == 401
    assert post_login(attacker, "wrong-password").status_code == 429
    # The owner's first attempt from a never-seen network succeeds.
    owner = from_address("198.51.100.77")
    response = post_login(owner, PASSWORD)
    assert response.status_code == 200 and response.json()["csrf_token"]
