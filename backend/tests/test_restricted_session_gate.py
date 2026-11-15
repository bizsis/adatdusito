"""SECURITY-02: the restricted-session gate must not depend on request.url.

A session with a forced password change or a pending second factor may only
use security.RESTRICTED_SAFE_PATHS. These tests attack the gate with forged
Host / forwarding headers and encoded paths, and prove that it keeps working
even if request.url is completely wrong.
"""

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.datastructures import URL
from starlette.requests import Request

from app import security
from app.main import app
from app.models import User
from app.security import RESTRICTED_SAFE_PATHS, route_path
from conftest import login
from test_auth09 import encryption_key, update  # noqa: F401

PASSWORD = "Test-password-2026!"
RESTRICTED_MESSAGE = "A folytatáshoz jelszócsere vagy második faktor beállítása szükséges."

FORGED_HEADERS = [
    {"host": "testserver/api/v1/auth/me?"},
    {"host": "testserver/api/v1/auth/me#"},
    {"host": "testserver/api/v1/auth/password?x="},
    {"host": "testserver:443/api/v1/auth/me?"},
    {"x-forwarded-host": "testserver/api/v1/auth/me?"},
    {"x-forwarded-proto": "https://testserver/api/v1/auth/me?"},
    {"x-forwarded-prefix": "/api/v1/auth/me"},
    {"x-original-url": "/api/v1/auth/me"},
    {"x-rewrite-url": "/api/v1/auth/me"},
    {"host": "testserver/api/v1/auth/me?", "x-forwarded-host": "evil/api/v1/auth/me#"},
]


def password_change_session(environment):
    client, engine, *_ = environment
    with Session(engine) as db:
        db.get(User, 1).must_change_password = True
        db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "root@example.hu", "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client


def mfa_pending_session(environment):
    """An existing session that becomes restricted when MFA is made mandatory."""
    client = environment[0]
    login(client)
    role = next(r["id"] for r in client.get("/api/v1/access/roles").json() if r["code"] == "superadmin")
    update(client, "mfa", {"enabled": True, "required_roles": [role], "passkey_mfa": True})
    assert client.get("/api/v1/auth/me").json()["mfa_required"]
    return client


@pytest.fixture(params=["password-change", "mfa-pending"])
def restricted(request, environment):
    make = password_change_session if request.param == "password-change" else mfa_pending_session
    return make(environment)


def assert_refused(response):
    assert response.status_code == 403, (response.status_code, response.text[:200])
    assert response.json()["error"]["message"] == RESTRICTED_MESSAGE


def plain_get_routes():
    # FastAPI >= 0.139 includes routers lazily, so read them from the schema.
    for path, operations in app.openapi()["paths"].items():
        if "get" in operations and "{" not in path:
            yield path


# --- unit: route_path ------------------------------------------------------


def scope(path, root_path="", host=b"testserver"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("utf-8", "surrogateescape"),
            "root_path": root_path,
            "query_string": b"",
            "headers": [(b"host", host)],
            "server": ("testserver", 443),
        }
    )


def test_route_path_ignores_host_and_matches_starlette_routing():
    from starlette._utils import get_route_path

    forged = scope("/api/v1/system/status", host=b"testserver/api/v1/auth/me?")
    assert route_path(forged) == "/api/v1/system/status"
    for path, root in [
        ("/api/v1/auth/me", ""),
        ("/prefix/api/v1/auth/me", "/prefix"),
        ("/prefixed/api/v1/auth/me", "/prefix"),  # not a real mount boundary
        ("/api/v1/auth/me/", ""),
    ]:
        assert route_path(scope(path, root)) == get_route_path(scope(path, root).scope)


@pytest.mark.parametrize(
    "path, root",
    [
        ("", ""),
        ("api/v1/auth/me", ""),  # relative target
        ("/prefix", "/prefix"),
        ("/api/v1/auth/me\x00", ""),
        ("/api/v1/auth/me?x", ""),  # decoded %3F
        ("/api/v1/auth/me#x", ""),  # decoded %23
    ],
)
def test_route_path_fails_closed_on_ambiguous_targets(path, root):
    assert route_path(scope(path, root)) not in RESTRICTED_SAFE_PATHS


def test_route_path_strips_mount_prefix_like_the_router():
    assert route_path(scope("/prefix/api/v1/auth/me", "/prefix")) == "/api/v1/auth/me"


# --- end to end ------------------------------------------------------------


def test_restricted_session_reaches_only_its_safe_routes(restricted):
    assert restricted.get("/api/v1/auth/me").status_code == 200
    assert restricted.get("/api/v1/auth/security").status_code == 200
    for path in ["/api/v1/system/status", "/api/v1/users", "/api/v1/tenants", "/api/v1/system/settings"]:
        assert_refused(restricted.get(path))


@pytest.mark.parametrize("headers", FORGED_HEADERS, ids=lambda h: ",".join(f"{k}={v}" for k, v in h.items()))
def test_forged_host_and_forwarding_headers_never_unlock(restricted, headers):
    for path in ["/api/v1/system/status", "/api/v1/users", "/api/v1/system/settings"]:
        response = restricted.get(path, headers=headers)
        assert response.status_code in (400, 403), (path, headers, response.status_code)


def test_no_identity_route_is_reachable_with_forged_host(restricted):
    """Every parameterless GET route: never more than an anonymous client gets."""
    anonymous = TestClient(app, base_url="https://testserver")
    checked = 0
    for path in plain_get_routes():
        if path in RESTRICTED_SAFE_PATHS:
            continue
        anonymous_status = anonymous.get(path).status_code
        status = restricted.get(path, headers={"host": "testserver/api/v1/auth/me?"}).status_code
        if anonymous_status != 200:
            assert status != 200, path
        checked += 1
    assert checked > 20


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me%2F..%2F..%2Fsystem%2Fstatus",
        "/api/v1/auth/me/../system/status",
        "/api/v1/auth/%6De",
        "/api/v1/auth/me%3F/../../system/status",
        "/api/v1/auth/me%23",
        "/api/v1//system/status",
        "/API/v1/system/status",
    ],
)
def test_escaped_and_odd_paths_never_unlock(restricted, path):
    response = restricted.get(path, follow_redirects=False)
    assert response.status_code != 200 or response.request.url.path in RESTRICTED_SAFE_PATHS


def test_gate_is_independent_of_request_url(restricted, monkeypatch):
    """Even if request.url claimed a safe path, the scope path decides."""
    monkeypatch.setattr(Request, "url", property(lambda self: URL("https://testserver/api/v1/auth/me")))
    assert_refused(restricted.get("/api/v1/system/status"))
    assert restricted.get("/api/v1/auth/me").status_code == 200


def test_password_change_session_can_finish_and_is_then_unrestricted(environment):
    client = password_change_session(environment)
    assert_refused(client.get("/api/v1/system/status"))
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "password": "Brand-new-password-2026!"},
    )
    assert r.status_code == 204, r.text
    client.headers.pop("X-CSRF-Token", None)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "root@example.hu", "password": "Brand-new-password-2026!"},
    )
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert client.get("/api/v1/system/status").status_code in (200, 503)


def test_mfa_pending_session_can_enrol_and_then_gets_an_unrestricted_session(environment):
    client = mfa_pending_session(environment)
    assert_refused(client.get("/api/v1/users", headers={"host": "testserver/api/v1/auth/me?"}))
    # The gate lets the session reach TOTP setup (the endpoint itself may then
    # ask for re-authentication, which is not the restricted-session refusal).
    r = client.post("/api/v1/auth/totp/setup")
    assert r.status_code == 200 or r.json()["error"]["message"] != RESTRICTED_MESSAGE
    # Enrolment through the pending-login flow yields a full session.
    pending = client.post("/api/v1/auth/login", json={"email": "root@example.hu", "password": PASSWORD}).json()
    assert pending["enrollment_required"]
    r = client.post("/api/v1/auth/mfa/setup", json={"token": pending["mfa_token"]})
    assert r.status_code == 200, r.text
    code = pyotp.TOTP(r.json()["secret"]).now()
    r = client.post("/api/v1/auth/mfa/complete", json={"token": pending["mfa_token"], "code": code})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert client.get("/api/v1/users").status_code == 200


def test_passkey_login_options_stay_available_to_restricted_sessions(restricted):
    from test_auth09 import enable

    login_client = restricted
    # The route is public (no identity) but listed as safe for reauth ceremonies.
    assert "/api/v1/auth/passkeys/login/options" in RESTRICTED_SAFE_PATHS
    r = login_client.post("/api/v1/auth/passkeys/login/options", json={})
    assert r.status_code in (200, 403)  # 403 only when passkeys are disabled by policy
    if r.status_code == 403:
        assert "passkey" in r.json()["error"]["message"].lower()
