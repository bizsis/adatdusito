import pytest
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Audit, LoginSession, Membership, User, now
from app.security import hash_password, verify_password
from conftest import login


def test_login_success_failure_cookie_and_logout(environment):
    client, engine, _, _ = environment
    response = client.post(
        "/api/v1/auth/login", json={"email": "root@example.hu", "password": "incorrect"}
    )
    assert response.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
    response = login(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "superadmin" and "password_hash" not in str(me)
    with Session(engine) as db:
        session = db.scalar(select(LoginSession))
        assert session.token_hash != client.cookies.get("adatdusito_session")
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_unknown_and_disabled_user_get_generic_login_error(environment):
    client, engine, _, _ = environment
    with Session(engine) as db:
        db.get(User, 3).active = False
        db.commit()
    messages = []
    for email in ["missing@example.hu", "processor@example.hu"]:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Test-password-2026!"},
        )
        assert response.status_code == 401
        messages.append(response.json())
    assert messages[0] == messages[1]


def test_csrf_and_origin_protection(environment):
    client, *_ = environment
    login(client)
    assert (
        client.post(
            "/api/v1/tenants", json={"name": "Új"}, headers={"X-CSRF-Token": ""}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/tenants",
            json={"name": "Új"},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "root@example.hu", "password": "Test-password-2026!"},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/tenants", json={"name": "Új"}).status_code == 201


@pytest.mark.parametrize("email", ["processor@example.hu", "reviewer@example.hu"])
def test_roles_read_reference_but_cannot_administer(environment, email):
    client, *_ = environment
    login(client, email)
    assert client.get("/api/v1/reference/categories").status_code == 200
    assert client.get("/api/v1/users").status_code == 403
    assert client.post("/api/v1/tenants", json={"name": "Forbidden"}).status_code == 403
    assert client.get("/api/v1/tenants/1/members").status_code == 403
    assert (
        client.put(
            "/api/v1/settings/admin_notice", json={"value": "Forbidden"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/audit").status_code == 403


def test_tenant_admin_scoped_users_and_tenants(environment):
    client, engine, *_ = environment
    login(client, "admin@example.hu")
    assert [t["id"] for t in client.get("/api/v1/tenants").json()["items"]] == [1]
    own = client.get("/api/v1/tenants/1/members").json()
    assert {u["id"] for u in own["items"]} == {2, 3, 4}
    assert client.get("/api/v1/tenants/2/members").status_code == 404
    assert client.patch("/api/v1/tenants/2", json={"name": "Attack"}).status_code == 404
    assert (
        client.patch("/api/v1/tenants/1", json={"name": "Átnevezett"}).status_code
        == 200
    )
    assert client.patch("/api/v1/tenants/1", json={"active": False}).status_code == 403
    assert client.post("/api/v1/auth/tenant", json={"tenant_id": 2}).status_code == 403
    assert (
        client.post(
            "/api/v1/tenants/2/users",
            json={
                "email": "new@example.hu",
                "password": "Long-new-password!",
                "name": "Nem",
                "role": "processor",
            },
        ).status_code
        == 404
    )
    result = client.post(
        "/api/v1/tenants/1/users",
        json={
            "email": "new@example.hu",
            "password": "Long-new-password!",
            "name": "Új",
            "role": "reviewer",
        },
    )
    assert result.status_code == 201
    assert client.get("/api/v1/users").status_code == 403
    assert (
        client.post(
            "/api/v1/tenants/1/users",
            json={
                "email": "other@example.hu",
                "password": "Long-new-password!",
                "name": "Átvétel",
                "role": "reviewer",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/tenants/1/users",
            json={
                "email": "bad@example.hu",
                "password": "Long-new-password!",
                "name": "Nem",
                "superadmin": True,
            },
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/v1/tenants/1/members/3", json={"role": "superadmin"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/tenants/1/members", json={"user_id": 5, "role": "processor"}
        ).status_code
        == 403
    )


def test_last_administrators_protected(environment):
    client, *_ = environment
    login(client)
    assert client.patch("/api/v1/users/1", json={"active": False}).status_code == 409
    assert (
        client.patch("/api/v1/users/1", json={"superadmin": False}).status_code == 409
    )
    login(client, "admin@example.hu")
    assert (
        client.patch("/api/v1/tenants/1/members/2", json={"active": False}).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/v1/tenants/1/members/2", json={"role": "reviewer"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/v1/tenants/1/members/3", json={"role": "tenant_admin"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/v1/tenants/1/members/2", json={"role": "reviewer"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/tenants/1/members").status_code == 403


def test_superadmin_manage_memberships_and_configuration(environment):
    client, engine, *_ = environment
    login(client)
    tenant = client.post("/api/v1/tenants", json={"name": "Új ügyfél"}).json()
    response = client.post(
        "/api/v1/users",
        json={
            "email": "NEW@EXAMPLE.HU",
            "name": "Új felhasználó",
            "password": "Long-new-password!",
        },
    )
    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "new@example.hu"
    assert (
        client.post(
            "/api/v1/tenants/%s/members" % tenant["id"],
            json={"user_id": user["id"], "role": "tenant_admin"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/tenants/%s/members" % tenant["id"],
            json={"user_id": user["id"], "role": "tenant_admin"},
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v1/auth/tenant", json={"tenant_id": tenant["id"]}).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").json()["tenant_id"] == tenant["id"]
    assert (
        client.put(
            "/api/v1/settings/admin_notice", json={"value": "Új rendszer"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/settings").json()["admin_notice"] == "Új rendszer"
    assert (
        client.put(
            "/api/v1/settings/OPENAI_API_KEY", json={"value": "not-a-secret"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/users/%s" % user["id"],
            json={"name": "Módosított", "active": False},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/users?limit=1").json()["total"] == 6
    with Session(engine) as db:
        assert not db.get(User, user["id"]).active
        assert db.get(Membership, (tenant["id"], user["id"])).role == "tenant_admin"


def test_password_change_revokes_sessions(environment):
    client, engine, *_ = environment
    login(client, "processor@example.hu")
    assert (
        client.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong", "password": "New-password-2026!"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/password",
            json={
                "current_password": "Test-password-2026!",
                "password": "New-password-2026!",
            },
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "processor@example.hu", "New-password-2026!")
    with Session(engine) as db:
        logs = list(db.scalars(select(Audit)))
        assert any(event.action == "user.password_change" for event in logs)
        assert "New-password" not in str([event.details for event in logs])


def test_tenant_audit_isolation(environment):
    client, *_ = environment
    login(client)
    client.patch("/api/v1/tenants/2", json={"name": "Privát ügyfél"})
    login(client, "admin@example.hu")
    client.patch("/api/v1/tenants/1", json={"name": "Saját ügyfél"})
    events = client.get("/api/v1/audit").json()["items"]
    assert events and all(e["tenant_id"] == 1 for e in events)
    assert "Privát ügyfél" not in str(events)


def test_session_expiry_and_realtime_account_revocation(environment):
    client, engine, *_ = environment
    login(client, "processor@example.hu")
    with Session(engine) as db:
        db.scalar(select(LoginSession)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "processor@example.hu")
    with Session(engine) as db:
        db.get(User, 3).active = False
        db.commit()
    assert client.get("/api/v1/reference/categories").status_code == 401


def test_membership_changes_take_effect_immediately(environment):
    client, engine, *_ = environment
    login(client, "admin@example.hu")
    with Session(engine) as db:
        db.get(Membership, (1, 2)).role = "reviewer"
        db.commit()
    assert client.get("/api/v1/tenants/1/members").status_code == 403
    assert client.get("/api/v1/reference/categories").status_code == 200


def test_validation_never_echoes_password(environment):
    client, *_ = environment
    login(client)
    response = client.post(
        "/api/v1/users", json={"email": "invalid", "name": "Test", "password": "secret"}
    )
    assert response.status_code == 422 and "secret" not in response.text
    assert client.get("/api/v1/users?limit=1000").status_code == 422


def test_openapi_requires_login(environment):
    client, *_ = environment
    assert client.get("/api/v1/openapi.json").status_code == 401
    login(client)
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert (
        "/api/v1/reference/parameters/{parameter_id}/values" in response.json()["paths"]
    )
    assert client.get("/api/v1/docs").status_code == 200


def test_password_hashing_has_salt_and_constant_verification(password_hash):
    assert verify_password("Test-password-2026!", password_hash)
    assert not verify_password("Wrong", password_hash)
    other = hash_password("Test-password-2026!")
    assert other != password_hash and "Test-password" not in other
    assert not verify_password("Test", "invalid")


def test_rate_limiter_atomic_and_fail_closed(monkeypatch):
    from app.security import limit_login
    from app import security
    from starlette.requests import Request
    from fastapi import HTTPException

    class FakeRedis:
        count = 0

        def eval(self, *args):
            return self.count

    redis = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    monkeypatch.setattr(security.Redis, "from_url", lambda *a, **k: redis)
    request = Request({"type": "http", "client": ("127.0.0.1", 42), "headers": []})
    limit_login(request, "test@example.hu")
    redis.count = 11
    with pytest.raises(HTTPException) as error:
        limit_login(request, "test@example.hu")
    assert error.value.status_code == 429
    monkeypatch.setattr(
        security.Redis, "from_url", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(HTTPException) as error:
        limit_login(request, "test@example.hu")
    assert error.value.status_code == 503


def test_tenant_admin_profile_management_excludes_shared_accounts(environment):
    client, engine, *_ = environment
    login(client, "admin@example.hu")
    assert (
        client.patch(
            "/api/v1/tenants/1/users/3", json={"name": "Átnevezett"}
        ).status_code
        == 200
    )
    assert (
        client.patch("/api/v1/tenants/2/users/5", json={"name": "Attack"}).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/v1/tenants/1/users/2", json={"password": "New-password-2026!"}
        ).status_code
        == 403
    )
    with Session(engine) as db:
        db.add(Membership(tenant_id=2, user_id=3, role="processor"))
        db.commit()
    assert (
        client.patch(
            "/api/v1/tenants/1/users/3", json={"password": "New-password-2026!"}
        ).status_code
        == 403
    )
    assert (
        client.patch("/api/v1/tenants/1/users/3", json={"active": False}).status_code
        == 422
    )


def test_revoked_membership_allows_logout_and_switch(environment):
    client, engine, *_ = environment
    login(client, "processor@example.hu")
    with Session(engine) as db:
        db.get(Membership, (1, 3)).active = False
        db.commit()
    assert client.get("/api/v1/reference/categories").status_code == 403
    assert client.get("/api/v1/auth/me").json()["tenant_id"] is None
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_non_ascii_csrf_is_rejected_as_forbidden(environment):
    client, *_ = environment
    login(client)
    response = client.post(
        "/api/v1/tenants",
        json={"name": "Forbidden"},
        headers=[(b"X-CSRF-Token", b"\xff")],
    )
    assert response.status_code == 403
