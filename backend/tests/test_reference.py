import pytest
from sqlalchemy import text
from conftest import login


def test_reference_requires_auth(environment):
    client, *_ = environment
    assert client.get("/api/v1/reference/categories").status_code == 401


def test_hierarchy_external_parent_and_missing_parent(environment):
    client, *_ = environment
    login(client)
    root = client.get("/api/v1/reference/categories").json()
    assert {c["id"] for c in root["items"]} == {10, 30, 50}
    orphan = next(c for c in root["items"] if c["id"] == 30)
    assert orphan["missing_parent"] and orphan["parent_id"] is None
    children = client.get("/api/v1/reference/categories?parent_id=10").json()
    assert [c["id"] for c in children["items"]] == [20]
    assert children["items"][0]["parent_id"] == 10
    detail = client.get("/api/v1/reference/categories/40").json()
    assert [a["id"] for a in detail["ancestors"]] == [10, 20]
    assert detail["hierarchy_error"] is None
    assert (
        client.get("/api/v1/reference/categories/30").json()["hierarchy_error"]
        == "missing_parent"
    )
    assert (
        client.get("/api/v1/reference/categories/50").json()["hierarchy_error"]
        == "cycle"
    )


def test_category_and_parameter_search(environment):
    client, *_ = environment
    login(client)
    assert (
        client.get("/api/v1/reference/categories?q=Laptop").json()["items"][0]["id"]
        == 20
    )
    assert (
        client.get("/api/v1/reference/categories?q=2000").json()["items"][0]["id"] == 20
    )
    assert client.get("/api/v1/reference/categories?q=%25").json()["total"] == 0
    assert client.get("/api/v1/reference/categories?limit=1").json()["total"] == 3
    parameters = client.get("/api/v1/reference/parameters?category_id=20").json()
    assert parameters["total"] == 1 and parameters["items"][0]["id"] == 70
    parameter = parameters["items"][0]
    assert (
        parameter["type_id"] == 2
        and parameter["is_mandatory"]
        and not parameter["allow_new_value"]
    )
    assert client.get("/api/v1/reference/parameters?q=9000").json()["total"] == 2
    assert (
        client.get("/api/v1/reference/parameters?mandatory=false").json()["items"][0][
            "id"
        ]
        == 80
    )
    assert (
        client.get("/api/v1/reference/parameters?category_id=2000").status_code == 404
    )
    assert client.get("/api/v1/reference/categories/999").status_code == 404


def test_values_are_keyset_paginated_by_internal_parameter_id(environment):
    client, *_ = environment
    login(client)
    cursor = 0
    ids = []
    for _ in range(3):
        response = client.get(
            f"/api/v1/reference/parameters/70/values?after={cursor}&limit=50"
        )
        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) <= 50
        ids.extend(v["id"] for v in page["items"])
        assert all(v["parameter_id"] == 70 for v in page["items"])
        if not page["has_more"]:
            break
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
    assert len(ids) == 125 and len(set(ids)) == 125 and ids == sorted(ids)
    assert 900 not in ids
    assert not page["has_more"] and page["next_cursor"] is None
    assert client.get("/api/v1/reference/parameters/9000/values").status_code == 404
    assert (
        client.get("/api/v1/reference/parameters/70/values?limit=101").status_code
        == 422
    )
    assert (
        client.get("/api/v1/reference/parameters/70/values?after=-1").status_code == 422
    )
    assert (
        client.get("/api/v1/reference/parameters/70/values?q=124").json()["items"][0][
            "value_text"
        ]
        == "Érték 124"
    )
    assert (
        client.get("/api/v1/reference/parameters/70/values?q=%27%20OR%201=1").json()[
            "items"
        ]
        == []
    )


def test_reference_endpoints_issue_only_selects_and_reject_writes(environment):
    client, _, ref_engine, statements = environment
    login(client)
    urls = [
        "/categories",
        "/categories/20",
        "/parameters?category_id=20",
        "/parameters/70/values",
    ]
    for url in urls:
        assert client.get("/api/v1/reference" + url).status_code == 200
    assert statements and all(
        s.lstrip().upper().startswith("SELECT ") for s in statements
    )
    for method in [client.post, client.put, client.patch, client.delete]:
        assert method("/api/v1/reference/categories/20").status_code == 405
    for sql in [
        "DELETE FROM emag_categories",
        'UPDATE emag_categories SET name="bad"',
        "CREATE TABLE stolen (id int)",
        "DROP TABLE emag_parameter_values",
        "SELECT * FROM emag_categories FOR UPDATE",
    ]:
        with ref_engine.connect() as conn:
            with pytest.raises(PermissionError):
                conn.execute(text(sql))


def test_reference_schema_cannot_enter_application_migrations():
    from app.models import Base

    assert not set(
        reference_name
        for reference_name in [
            "emag_categories",
            "emag_category_parameters",
            "emag_parameter_values",
        ]
    ) & set(Base.metadata.tables)
