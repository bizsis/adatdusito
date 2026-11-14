"""Additive RBAC, active-session enforcement, safe invitations and scope isolation."""

from datetime import timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import User, Membership, Audit, now
from app.access_models import Invitation
from app import invitations
from conftest import login


def switch(c, id):
    r = c.post("/api/v1/auth/tenant", json={"tenant_id": id})
    assert r.status_code == 200, r.text


def roles(c, tid=None):
    r = c.get("/api/v1/access/roles" + (f"?tenant_id={tid}" if tid else ""))
    assert r.status_code == 200, r.text
    return {x["code"]: x for x in r.json()}


def custom(c, code, permissions, tid=None):
    r = c.post(
        "/api/v1/access/roles" + (f"?tenant_id={tid}" if tid else ""),
        json={"code": code, "name": "Teszt " + code, "permissions": permissions},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def grant(c, user, ids, tid=None, **extra):
    r = c.put(
        f"/api/v1/access/users/{user}" + (f"?tenant_id={tid}" if tid else ""),
        json={"roles": ids, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_superadmin_workspaces_without_membership_and_search(environment):
    c, t, *_ = environment
    login(c)
    me = c.get("/api/v1/auth/me").json()
    assert [(w["tenant_id"], w["name"]) for w in me["workspaces"]] == [
        (1, "Első ügyfél"),
        (2, "Második ügyfél"),
    ]
    assert me["system"] is True
    switch(c, 2)
    assert c.get("/api/v1/auth/me").json()["tenant_id"] == 2
    assert c.get("/api/v1/access/workspaces?q=Második").json()["items"] == [
        {"tenant_id": 2, "name": "Második ügyfél"}
    ]
    with Session(t) as db:
        assert db.get(Membership, (2, 1)) is None
    switch(c, None)


def test_system_role_own_permissions_and_selected_scope(environment):
    c, t, *_ = environment
    login(c)
    id = custom(
        c, "restricted_system", ["reference.read", "imports.read", "products.read"]
    )
    grant(c, 3, [id], tenant_mode="selected", tenants=[2])
    login(c, "processor@example.hu")
    me = c.get("/api/v1/auth/me").json()
    assert me["system"] and me["tenant_id"] is None
    assert [w["tenant_id"] for w in me["workspaces"]] == [2]
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 403
    switch(c, 2)
    assert c.get("/api/v1/imports/runs").status_code == 200
    assert c.get("/api/v1/tenants/2/members").status_code == 403
    assert "members.manage" not in c.get("/api/v1/auth/me").json()["permissions"]


def test_system_auditor_cannot_mutate_and_central_only_user(environment):
    c, t, *_ = environment
    login(c)
    rr = roles(c)
    grant(c, 3, [rr["system_auditor"]["id"]], tenant_mode="selected", tenants=[1])
    login(c, "processor@example.hu")
    switch(c, 1)
    assert c.get("/api/v1/imports/runs").status_code == 200
    assert c.post("/api/v1/imports/suppliers", json={"name": "No"}).status_code == 403
    switch(c, None)
    assert c.get("/api/v1/audit").status_code == 200
    login(c)
    id = custom(c, "central_only", ["system.settings.read"])
    grant(c, 3, [id], tenant_mode="none")
    login(c, "processor@example.hu")
    assert c.get("/api/v1/access/workspaces").json()["items"] == []
    assert c.get("/api/v1/settings").status_code == 200
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 403


def test_multiple_roles_union_denies_and_user_permissions_sources(environment):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    a = custom(c, "upload_reader", ["imports.read", "imports.create"], 1)
    b = custom(c, "approver", ["imports.approve", "reference.read"], 1)
    grant(c, 3, [a, b], 1, deny=["imports.create"], allow=["products.read"])
    login(c, "processor@example.hu")
    me = c.get("/api/v1/auth/me").json()
    assert {r["code"] for r in me["roles"]} == {"upload_reader", "approver"}
    assert {
        "imports.read",
        "imports.approve",
        "reference.read",
        "products.read",
    } <= set(me["permissions"])
    assert (
        "imports.create" not in me["permissions"]
        and me["permission_sources"]["imports.create"]["exception"] == "deny"
    )
    assert c.get("/api/v1/imports/runs").status_code == 200
    assert (
        c.post(
            "/api/v1/imports/runs",
            data={"supplier_id": 1},
            files={"file": ("a.csv", b"SKU\n001\n")},
        ).status_code
        == 403
    )


def test_multiple_tenants_different_roles_and_immediate_revocation(environment):
    c, t, *_ = environment
    login(c)
    assert (
        c.post(
            "/api/v1/tenants/2/members", json={"user_id": 3, "role": "reviewer"}
        ).status_code
        == 201
    )
    login(c, "processor@example.hu")
    switch(c, 1)
    assert "imports.create" in c.get("/api/v1/auth/me").json()["permissions"]
    switch(c, 2)
    assert "imports.create" not in c.get("/api/v1/auth/me").json()["permissions"]
    with Session(t) as db:
        db.get(Membership, (2, 3)).active = False
        db.commit()
    assert c.get("/api/v1/imports/runs").status_code == 403
    assert c.get("/api/v1/auth/me").json()["tenant_id"] is None
    switch(c, 1)


def test_tenant_admin_cannot_delegate_system_rights_or_old_role_escalation(environment):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    assert (
        c.post(
            "/api/v1/access/roles?tenant_id=1",
            json={
                "code": "evil",
                "name": "Evil",
                "permissions": ["system.users.manage"],
            },
        ).status_code
        == 403
    )
    assert c.get("/api/v1/users").status_code == 403
    assert c.get("/api/v1/tenants/2/members").status_code == 404
    login(c)
    switch(c, 1)
    id = custom(
        c,
        "limited_staff_admin",
        ["members.read", "members.manage", "members.roles.manage"],
        1,
    )
    grant(c, 2, [id], 1)
    login(c, "admin@example.hu")
    assert (
        c.patch("/api/v1/tenants/1/members/3", json={"role": "processor"}).status_code
        == 403
    )


def test_selected_resources_are_not_extended_and_unassigned_import_is_denied(
    environment,
):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    a = c.post("/api/v1/access/companies", json={"name": "Cég A"}).json()["id"]
    b = c.post("/api/v1/access/companies", json={"name": "Cég B"}).json()["id"]
    sa = c.post(
        "/api/v1/access/webshops", json={"name": "Bolt A", "company_id": a}
    ).json()["id"]
    sb = c.post(
        "/api/v1/access/webshops", json={"name": "Bolt B", "company_id": b}
    ).json()["id"]
    role = custom(
        c, "resource_reader", ["companies.read", "webshops.read", "imports.read"], 1
    )
    grant(c, 3, [role], 1, resource_mode="selected", companies=[a], shops=[sa])
    future = c.post(
        "/api/v1/access/webshops", json={"name": "Új bolt A", "company_id": a}
    ).json()["id"]
    login(c, "processor@example.hu")
    assert [x["name"] for x in c.get("/api/v1/access/companies").json()] == ["Cég A"]
    assert [x["id"] for x in c.get("/api/v1/access/webshops").json()] == [sa]
    for id in [sb, future]:
        assert c.get(f"/api/v1/access/webshops/{id}").status_code == 404
    assert c.get(f"/api/v1/access/companies/{b}").status_code == 404
    assert c.get("/api/v1/imports/runs").status_code == 403


def test_protected_superadmin_and_system_scope_escalation(environment):
    c, t, *_ = environment
    login(c)
    rr = roles(c)
    assert c.delete(f"/api/v1/access/roles/{rr['superadmin']['id']}").status_code == 403
    assert c.patch("/api/v1/users/1", json={"active": False}).status_code == 409
    actor = custom(
        c, "delegator", ["system.users.read", "system.users.manage", "reference.read"]
    )
    grant(c, 3, [actor], tenant_mode="selected", tenants=[1])
    login(c, "processor@example.hu")
    assert (
        c.put(
            "/api/v1/access/users/4", json={"roles": [], "tenant_mode": "all"}
        ).status_code
        == 403
    )
    assert c.patch("/api/v1/users/1", json={"active": False}).status_code == 403


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(
        invitations,
        "send_email",
        lambda email, token, workspace: sent.append((email, token, workspace)),
    )
    return sent


def invite(c, email, role, tid=1):
    r = c.post(
        "/api/v1/invitations" + (f"?tenant_id={tid}" if tid else ""),
        json={"email": email, "roles": [role]},
    )
    assert r.status_code == 200, r.text
    assert "token" not in r.text
    return r.json()["id"]


def test_invite_new_account_once_and_no_token_in_audit(environment, mail):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    id = invite(c, "new@example.hu", roles(c, 1)["processor"]["id"])
    token = mail[-1][1]
    c.post("/api/v1/auth/logout")
    assert (
        c.post("/api/v1/invitations/inspect", json={"token": token}).json()[
            "existing_account"
        ]
        is False
    )
    r = c.post(
        "/api/v1/invitations/accept",
        json={"token": token, "name": "Új Munkatárs", "password": "Own-password-2026!"},
    )
    assert r.status_code == 200, r.text
    assert (
        c.post(
            "/api/v1/invitations/accept",
            json={"token": token, "name": "No", "password": "Own-password-2026!"},
        ).status_code
        == 400
    )
    login(c, "new@example.hu", "Own-password-2026!")
    assert c.get("/api/v1/auth/me").json()["tenant_id"] == 1
    with Session(t) as db:
        i = db.get(Invitation, id)
        assert i.state == "accepted" and i.token_hash != token
        records = list(db.scalars(select(Audit).where(Audit.action.like("access.%"))))
        assert token not in str([r.details for r in records])
        assert any(
            r.action == "access.invite_accept" and r.actor_id == i.accepted_by
            for r in records
        )


def test_existing_account_owner_accepts_without_password_or_other_tenant_change(
    environment, mail
):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    role = roles(c, 1)["reviewer"]["id"]
    invite(c, "other@example.hu", role)
    token = mail[-1][1]
    with Session(t) as db:
        before = db.get(User, 5).password_hash
    c.post("/api/v1/auth/logout")
    assert (
        c.post("/api/v1/invitations/accept", json={"token": token}).status_code == 401
    )
    login(c, "other@example.hu")
    assert (
        c.post("/api/v1/invitations/accept", json={"token": token}).status_code == 200
    )
    with Session(t) as db:
        assert db.get(User, 5).password_hash == before
        assert db.get(Membership, (2, 5)).role == "tenant_admin"
        assert db.get(Membership, (1, 5)).active
    switch(c, 1)
    assert "members.manage" not in c.get("/api/v1/auth/me").json()["permissions"]


def test_expired_revoked_and_rotated_invites(environment, mail):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    role = roles(c, 1)["viewer"]["id"]
    id = invite(c, "one@example.hu", role)
    old = mail[-1][1]
    assert c.post(f"/api/v1/invitations/{id}/resend").status_code == 200
    new = mail[-1][1]
    assert new != old
    assert c.post("/api/v1/invitations/inspect", json={"token": old}).status_code == 400
    assert c.post(f"/api/v1/invitations/{id}/revoke").status_code == 200
    assert c.post("/api/v1/invitations/inspect", json={"token": new}).status_code == 400
    id = invite(c, "two@example.hu", role)
    token = mail[-1][1]
    with Session(t) as db:
        db.get(Invitation, id).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert (
        c.post("/api/v1/invitations/inspect", json={"token": token}).status_code == 400
    )


def test_invite_privacy_and_failed_smtp_not_fake_success(
    environment, mail, monkeypatch
):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    role = roles(c, 1)["processor"]["id"]
    a = invite(c, "unknown@example.hu", role)
    b = invite(c, "other@example.hu", role)
    records = c.get("/api/v1/invitations?tenant_id=1").json()
    assert {r["id"] for r in records} == {a, b}
    assert all("existing_account" not in r for r in records)
    assert c.get("/api/v1/users?q=other").status_code == 403
    monkeypatch.setattr(
        invitations,
        "send_email",
        lambda *args: (_ for _ in ()).throw(RuntimeError("secret provider content")),
    )
    r = c.post(
        "/api/v1/invitations?tenant_id=1",
        json={"email": "failure@example.hu", "roles": [role]},
    )
    assert r.status_code == 503 and "secret provider" not in r.text
    assert c.get("/api/v1/invitations?tenant_id=1").json()[0]["delivery"] == "failed"


def test_actual_smtp_delivery_with_local_server(monkeypatch):
    import socketserver
    import threading

    messages = []

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 local test\r\n")
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                command = line.split(b" ", 1)[0].strip().upper()
                if command in (b"EHLO", b"HELO"):
                    self.wfile.write(b"250 local\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 send data\r\n")
                    body = []
                    while True:
                        part = self.rfile.readline()
                        if part in (b".\r\n", b""):
                            break
                        body.append(part)
                    messages.append(b"".join(body))
                    self.wfile.write(b"250 accepted\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    server = socketserver.TCPServer(("127.0.0.1", 0), SMTP)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(server.server_address[1]))
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.invalid")
    monkeypatch.delenv("SMTP_USER", raising=False)
    try:
        invitations.send_email(
            "invited@example.invalid", "test-token-only-in-email", "Teszt munkaterület"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    from email import message_from_bytes

    assert len(messages) == 1
    message = message_from_bytes(messages[0])
    body = message.get_payload(decode=True).decode()
    assert "#invite=test-token-only-in-email" in body and "Teszt munkaterület" in body


def test_read_only_members_and_per_operation_import_permissions(environment):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    read = custom(
        c,
        "member_reader",
        ["members.read", "imports.read", "imports.cancel", "products.read"],
        1,
    )
    grant(c, 3, [read], 1)
    login(c, "processor@example.hu")
    assert c.get("/api/v1/tenants/1/members").status_code == 200
    assert (
        c.patch("/api/v1/tenants/1/members/4", json={"active": False}).status_code
        == 403
    )
    assert c.get("/api/v1/imports/products?supplier_id=1").status_code == 200
    assert c.get("/api/v1/imports/export-profiles").status_code == 403
    assert c.post("/api/v1/imports/suppliers", json={"name": "No"}).status_code == 403


def test_role_update_and_explicit_allow_take_effect_in_current_session(environment):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    id = custom(c, "mutable_role", ["imports.read"], 1)
    grant(c, 3, [id], 1, allow=["reference.read"])
    login(c, "processor@example.hu")
    assert c.get("/api/v1/imports/runs").status_code == 200
    from app.access_models import AccessRole

    with Session(t) as db:
        r = db.get(AccessRole, id)
        r.permissions = []
        db.commit()
    assert c.get("/api/v1/imports/runs").status_code == 403
    assert "reference.read" in c.get("/api/v1/auth/me").json()["permissions"]


def test_system_actor_resource_restriction_blocks_broader_delegation(environment):
    c, t, *_ = environment
    login(c)
    id = custom(
        c,
        "scoped_delegator",
        [
            "system.users.read",
            "system.users.manage",
            "tenants.access.manage",
            "companies.read",
        ],
    )
    grant(c, 3, [id], tenant_mode="selected", tenants=[1])
    response = c.put(
        "/api/v1/access/users/3/resources?tenant_id=1",
        json={"resource_mode": "selected", "companies": [], "shops": []},
    )
    assert response.status_code == 200
    login(c, "processor@example.hu")
    assert (
        c.put(
            "/api/v1/access/users/4",
            json={"roles": [], "tenant_mode": "selected", "tenants": [1]},
        ).status_code
        == 403
    )


def test_membership_deactivation_does_not_remove_account_or_other_tenant(environment):
    c, t, *_ = environment
    login(c)
    assert (
        c.post(
            "/api/v1/tenants/1/members", json={"user_id": 5, "role": "reviewer"}
        ).status_code
        == 201
    )
    switch(c, 1)
    assert (
        c.patch("/api/v1/tenants/1/members/5", json={"active": False}).status_code
        == 200
    )
    with Session(t) as db:
        assert db.get(User, 5).active
        assert db.get(Membership, (2, 5)).active
        assert not db.get(Membership, (1, 5)).active
    assert (
        c.patch("/api/v1/tenants/1/members/5", json={"active": True}).status_code == 200
    )


def test_tenant_role_changes_do_not_modify_other_tenant_templates(environment):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    r = roles(c, 1)["processor"]
    out = c.put(
        f"/api/v1/access/roles/{r['id']}?tenant_id=1",
        json={
            "code": "processor",
            "name": "Saját feldolgozó",
            "permissions": ["reference.read"],
        },
    )
    assert out.status_code == 200, out.text
    login(c, "processor@example.hu")
    assert "imports.create" not in c.get("/api/v1/auth/me").json()["permissions"]
    login(c)
    switch(c, 2)
    assert roles(c, 2)["processor"]["name"] == "Adatfeldolgozó"


def test_pending_invite_uses_updated_tenant_role_not_original_template(
    environment, mail
):
    c, t, *_ = environment
    login(c)
    switch(c, 1)
    template = roles(c, 1)["processor"]
    invite(c, "pending@example.hu", template["id"])
    token = mail[-1][1]
    r = c.put(
        f"/api/v1/access/roles/{template['id']}?tenant_id=1",
        json={
            "code": "processor",
            "name": "Helyi olvasó",
            "permissions": ["reference.read"],
        },
    )
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id != template["id"]
    assert roles(c, 1)["processor"]["id"] == new_id
    assert (
        c.put(
            "/api/v1/access/users/3?tenant_id=1", json={"roles": [template["id"]]}
        ).status_code
        == 409
    )
    c.post("/api/v1/auth/logout")
    assert (
        c.post(
            "/api/v1/invitations/accept",
            json={"token": token, "name": "Pending", "password": "Pending-password!"},
        ).status_code
        == 200
    )
    login(c, "pending@example.hu", "Pending-password!")
    assert c.get("/api/v1/auth/me").json()["permissions"] == ["reference.read"]


def test_individual_override_cannot_grant_system_permission_in_tenant(environment):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    ids = [roles(c, 1)["processor"]["id"]]
    r = c.put(
        "/api/v1/access/users/3?tenant_id=1",
        json={"roles": ids, "allow": ["system.users.manage"]},
    )
    assert r.status_code == 403
    assert c.get("/api/v1/users").status_code == 403


def test_fine_grained_deny_removes_legacy_broad_alias(environment):
    c, t, *_ = environment
    login(c)
    id = custom(
        c,
        "settings_editor",
        ["system.settings.read", "system.settings.manage", "reference.manage"],
    )
    grant(c, 3, [id], deny=["system.settings.manage"])
    login(c, "processor@example.hu")
    me = c.get("/api/v1/auth/me").json()
    assert (
        "system.manage" not in me["permissions"]
        and "system.settings.manage" not in me["permissions"]
    )
    assert c.get("/api/v1/settings").status_code == 200
    assert (
        c.put("/api/v1/settings/display_name", json={"value": "No"}).status_code == 403
    )


def test_new_invitation_and_permission_revocation_invalidate_old_links(
    environment, mail
):
    c, t, *_ = environment
    login(c, "admin@example.hu")
    role = roles(c, 1)["processor"]["id"]
    first = invite(c, "processor@example.hu", role)
    old = mail[-1][1]
    second = invite(c, "processor@example.hu", role)
    latest = mail[-1][1]
    assert c.post("/api/v1/invitations/inspect", json={"token": old}).status_code == 400
    grant(c, 3, [roles(c, 1)["viewer"]["id"]], tid=1, deny=["imports.read"])
    assert (
        c.post("/api/v1/invitations/inspect", json={"token": latest}).status_code == 400
    )
    login(c, "processor@example.hu")
    assert (
        c.post("/api/v1/invitations/accept", json={"token": latest}).status_code == 400
    )
    assert "imports.read" not in c.get("/api/v1/auth/me").json()["permissions"]
    with Session(t) as db:
        assert db.get(Invitation, first).state == "revoked"
        assert db.get(Invitation, second).state == "revoked"
        assert (
            len(
                list(
                    db.scalars(
                        select(Audit).where(Audit.action == "access.invite_superseded")
                    )
                )
            )
            == 2
        )
