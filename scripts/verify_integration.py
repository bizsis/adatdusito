"""End-to-end API checks against the synthetic cloud stack only.

Usage: .venv/bin/python scripts/verify_integration.py --credentials /secure/test.json
The file contains an already bootstrapped test Superadmin's email/password.
Never pass a VPS URL: this runner intentionally permits only the cloud loopback port.
"""

import argparse
import json
import secrets
from pathlib import Path
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--credentials", required=True, type=Path)
args = parser.parse_args()
credentials = json.loads(args.credentials.read_text())
base = "http://127.0.0.1:18080/api/v1"
suffix = secrets.token_hex(5)
new_password = secrets.token_urlsafe(24)


def checked(response, status=200):
    assert response.status_code == status, (
        f"{response.request.method} {response.request.url.path}: {response.status_code}"
    )
    return response.json() if status != 204 else None


def login(client, email, password):
    result = checked(
        client.post("/auth/login", json={"email": email, "password": password})
    )
    client.headers["X-CSRF-Token"] = result["csrf_token"]


with httpx.Client(
    base_url=base, headers={"Origin": "http://127.0.0.1:18080"}, timeout=20
) as admin:
    login(admin, credentials["email"], credentials["password"])
    checked(admin.get("/openapi.json"))
    stats = checked(admin.get("/reference/coverage"))
    assert (
        stats["reference_total"] == 3
        and stats["max_depth"] == 2
        and stats["categories_with_parameters"] == 2
    )
    assert len(checked(admin.get("/reference/sources"))["items"]) == 4
    selection = checked(admin.get("/reference/categories/20/selection"))
    assert (
        selection["parameter_inheritance"] is False
        and selection["category"]["parameter_count"] == 1
    )
    checked(
        admin.post(
            "/reference/sources/observations",
            json={
                "source_key": "emag_webshop",
                "evidence_url": "https://www.emag.hu/",
                "outcome": "partial",
                "source_category_id": "synthetic-unmatched-" + suffix,
                "summary": "Szintetikus integrációs megfigyelés; nem igazolt megfeleltetés.",
            },
        ),
        201,
    )
    assert checked(admin.get("/reference/coverage"))["reference_total"] == 3

    tenant = checked(
        admin.post("/tenants", json={"name": "Integrációs ügyfél " + suffix}), 201
    )
    second = checked(
        admin.post("/tenants", json={"name": "Elkülönített ügyfél " + suffix}), 201
    )
    email = f"admin-{suffix}@example.hu"
    member = checked(
        admin.post(
            f"/tenants/{tenant['id']}/users",
            json={
                "name": "Teszt ügyféladmin",
                "email": email,
                "password": new_password,
                "role": "tenant_admin",
            },
        ),
        201,
    )
    categories = checked(admin.get("/reference/categories"))
    assert {c["id"] for c in categories["items"]} == {10, 30}
    assert (
        next(c for c in categories["items"] if c["id"] == 10)["name"]
        == "Műszaki cikkek"
    )
    assert next(c for c in categories["items"] if c["id"] == 30)["missing_parent"]
    assert (
        checked(admin.get("/reference/categories", params={"parent_id": 10}))["items"][
            0
        ]["id"]
        == 20
    )
    parameter = checked(admin.get("/reference/parameters", params={"category_id": 20}))[
        "items"
    ][0]
    assert parameter["id"] == 70 and parameter["emag_parameter_id"] == 9000
    first = checked(admin.get("/reference/parameters/70/values", params={"limit": 1}))
    assert first["has_more"]
    last = checked(
        admin.get(
            "/reference/parameters/70/values",
            params={"limit": 1, "after": first["next_cursor"]},
        )
    )
    assert last["items"][0]["id"] != first["items"][0]["id"] and not last["has_more"]
    # Protected reference routes have no mutating operation.
    checked(admin.patch("/reference/categories/20", json={"name": "Forbidden"}), 405)
    checked(
        admin.post("/tenants", json={"name": "No CSRF"}, headers={"X-CSRF-Token": ""}),
        403,
    )
    with httpx.Client(base_url=base, timeout=20) as scoped:
        login(scoped, email, new_password)
        assert checked(scoped.get("/tenants"))["items"] == [tenant]
        checked(scoped.get(f"/tenants/{second['id']}/members"), 404)
        checked(scoped.get("/users"), 403)
        checked(
            scoped.patch(
                f"/tenants/{tenant['id']}/members/{member['id']}",
                json={"active": False},
            ),
            409,
        )
        checked(
            scoped.patch(
                f"/tenants/{tenant['id']}", json={"name": "Átnevezett " + suffix}
            )
        )
        assert all(
            row["tenant_id"] == tenant["id"]
            for row in checked(scoped.get("/audit"))["items"]
        )
        checked(scoped.post("/auth/logout"), 204)
        checked(scoped.get("/auth/me"), 401)
    assert all(checked(admin.get("/system/status"))["checks"].values())
print(
    "MySQL API integration: login, tenant isolation, roles, CSRF, audit, hierarchy, internal-ID joins and cursor pagination passed."
)
