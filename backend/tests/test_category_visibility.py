"""Category visibility is enforced in every read/selection path, including parents."""

import pytest
from conftest import login


@pytest.fixture
def extra_reference_categories():
    def row(id, external, name, allowed, parent=None):
        return dict(
            id=id,
            emag_category_id=external,
            name=name,
            parent_id=parent,
            is_allowed=allowed,
        )

    return [
        row(101, 1715, "Legume proaspete", False),
        row(102, 1749, "Fructe proaspete", False, 1000),
        row(103, 1874, "Deleted Peste & Produse din peste", False),
        row(104, 1885, "Carne proaspata", None),
        row(105, 7000, "Aktív gyermek", True, 1715),
        row(106, 7100, "Aktív unoka", True, 7000),
        row(107, 1886, "Carne proaspata aktív", True),
        row(108, 7200, "Deleted de aktív", True),
        row(109, 7300, "Aktív mély gyermek", True, 1749),
    ]


@pytest.fixture
def extra_reference_parameters():
    return [
        dict(
            id=id,
            category_id=category,
            emag_parameter_id=9001,
            name="Láthatósági paraméter",
            type_id=2,
            display_order=1,
            is_mandatory=True,
            is_filter=False,
            allow_new_value=False,
        )
        for id, category in [(170, 101), (171, 105), (172, 104)]
    ]


@pytest.fixture
def extra_reference_values():
    return [
        dict(
            id=1000 + i, parameter_id=parameter, value_text="Tesztérték", value_order=1
        )
        for i, parameter in enumerate([170, 171, 172])
    ]


def test_only_explicitly_active_categories_in_all_lists_and_pagination(environment):
    client, *_ = environment
    login(client)
    expected = {10, 20, 30, 40, 50, 60, 105, 106, 107, 108, 109}
    all_rows = client.get("/api/v1/reference/categories?roots=false").json()
    assert all_rows["total"] == len(expected)
    assert {row["id"] for row in all_rows["items"]} == expected
    ids = []
    for offset in range(len(expected)):
        page = client.get(
            f"/api/v1/reference/categories?roots=false&limit=1&offset={offset}"
        ).json()
        assert page["total"] == len(expected)
        assert len(page["items"]) == 1 and page["items"][0]["is_allowed"] is True
        ids.append(page["items"][0]["id"])
    assert set(ids) == expected and len(ids) == len(set(ids))
    assert (
        client.get(
            f"/api/v1/reference/categories?roots=false&offset={len(expected)}"
        ).json()["items"]
        == []
    )


@pytest.mark.parametrize(
    "query", ["Legume", "1715", "Fructe", "1749", "Peste", "1874", "1885"]
)
def test_inactive_categories_not_searchable_by_name_or_external_id(environment, query):
    client, *_ = environment
    login(client)
    page = client.get("/api/v1/reference/categories", params={"q": query}).json()
    assert page["items"] == [] and page["total"] == 0


def test_filter_depends_on_active_flag_not_language_or_deleted_word(environment):
    client, *_ = environment
    login(client)
    romanian = client.get(
        "/api/v1/reference/categories", params={"q": "Carne proaspata"}
    ).json()
    assert [row["id"] for row in romanian["items"]] == [107]
    deleted = client.get("/api/v1/reference/categories", params={"q": "Deleted"}).json()
    assert [row["id"] for row in deleted["items"]] == [108]


def test_active_children_of_inactive_parents_are_roots_and_keep_descendants(
    environment,
):
    client, *_ = environment
    login(client)
    root = client.get("/api/v1/reference/categories").json()
    assert {row["id"] for row in root["items"]} == {10, 30, 105, 107, 108, 109}
    orphan = next(row for row in root["items"] if row["id"] == 105)
    assert (
        orphan["missing_parent"]
        and orphan["parent_id"] is None
        and orphan["parent_name"] is None
    )
    assert orphan["parent_emag_id"] == 1715
    children = client.get("/api/v1/reference/categories?parent_id=105").json()
    assert [row["id"] for row in children["items"]] == [106]
    # The inactive child of an active parent is not exposed in its child list.
    assert [
        row["id"]
        for row in client.get("/api/v1/reference/categories?parent_id=10").json()[
            "items"
        ]
    ] == [20]
    detail = client.get("/api/v1/reference/categories/106").json()
    assert [row["id"] for row in detail["ancestors"]] == [105]
    assert detail["hierarchy_error"] == "missing_parent"
    assert client.get("/api/v1/reference/categories/109").json()["ancestors"] == []


@pytest.mark.parametrize("id", [101, 102, 103, 104])
def test_inactive_category_detail_and_parent_selection_return_404(environment, id):
    client, *_ = environment
    login(client)
    assert client.get(f"/api/v1/reference/categories/{id}").status_code == 404
    assert client.get(f"/api/v1/reference/categories?parent_id={id}").status_code == 404
    assert (
        client.get(f"/api/v1/reference/parameters?category_id={id}").status_code == 404
    )


def test_parameter_and_value_routes_cannot_bypass_category_visibility(environment):
    client, *_ = environment
    login(client)
    page = client.get("/api/v1/reference/parameters?q=9001").json()
    assert [row["id"] for row in page["items"]] == [171]
    assert page["total"] == 1
    assert client.get("/api/v1/reference/parameters/170/values").status_code == 404
    assert client.get("/api/v1/reference/parameters/172/values").status_code == 404
    active = client.get("/api/v1/reference/parameters/171/values")
    assert active.status_code == 200 and len(active.json()["items"]) == 1
