"""DEPENDENCY-01: Starlette/FastAPI request handling the upgrade must fix or keep.

GHSA-86qp-5c8j-p5mr / GHSA-jp82-jpqv-5vv3: Starlette < 1.0.1 / 1.3.0 rebuilt
request.url from the Host header and the path without validation. The
CODEX 09 session gate (security.identity) decides which paths a restricted
session (forced password change or pending MFA) may use, so a forged Host
header let such a session reach other endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import User
from conftest import login

PASSWORD = "Test-password-2026!"


@pytest.fixture
def restricted(environment):
    """A session that may only use the password-change/MFA safe paths."""
    client, engine, *_ = environment
    with Session(engine) as db:
        db.get(User, 1).must_change_password = True
        db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "root@example.hu", "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client


@pytest.mark.parametrize(
    "host",
    [
        "testserver/api/v1/auth/me?",
        "testserver/api/v1/auth/me#",
        "testserver/api/v1/auth/password?x=",
    ],
)
def test_forged_host_header_cannot_unlock_a_restricted_session(restricted, host):
    assert restricted.get("/api/v1/system/status").status_code == 403
    r = restricted.get("/api/v1/system/status", headers={"host": host})
    assert r.status_code in (400, 403), (host, r.status_code)


def test_restricted_session_still_reaches_its_safe_paths(restricted):
    assert restricted.get("/api/v1/auth/me").status_code == 200


def test_urlencoded_form_field_limit_is_enforced(imports_client):
    """GHSA-82w8-qh3p-5jfq: max_fields was ignored for urlencoded bodies."""
    body = "&".join(f"f{i}=1" for i in range(5000))
    r = imports_client.post(
        "/api/v1/imports/runs",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400, r.status_code


@pytest.fixture
def imports_client(environment):
    client = environment[0]
    login(client)
    return client


def test_json_body_requires_json_content_type(environment):
    """FastAPI >= 0.132 (strict_content_type): JSON bodies need application/json.

    The frontend always sends it (frontend/src/main.tsx api()); a text/plain
    body - the kind a cross-site form can send without CORS preflight - is now
    refused before reaching the endpoint.
    """
    import json

    client = environment[0]
    payload = json.dumps({"email": "root@example.hu", "password": PASSWORD})
    ok = client.post("/api/v1/auth/login", content=payload, headers={"Content-Type": "application/json"})
    assert ok.status_code == 200, ok.text
    plain = client.post("/api/v1/auth/login", content=payload, headers={"Content-Type": "text/plain"})
    assert plain.status_code == 422


def test_openapi_and_docs_stay_behind_login(environment):
    client = environment[0]
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/api/v1/openapi.json").status_code == 401
    login(client)
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200 and "/api/v1/auth/login" in schema.json()["paths"]
    assert client.get("/api/v1/docs").status_code == 200


def test_security_headers_and_origin_check_unchanged(environment):
    client = environment[0]
    r = client.get("/api/health/live")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "root@example.hu", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
