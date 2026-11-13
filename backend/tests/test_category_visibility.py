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


def test_navigation_keeps_structural_ancestors_and_pagination(environment):
    client, *_ = environment
    login(client)
    expected = {10, 20, 30, 40, 50, 60, 101, 102, 105, 106, 107, 109}
    ids = []
    for offset in range(len(expected)):
        page = client.get(
            f"/api/v1/reference/categories?roots=false&limit=1&offset={offset}"
        ).json()
        assert page["total"] == len(expected)
        ids.append(page["items"][0]["id"])
    assert set(ids) == expected and len(ids) == len(set(ids))
    assert (
        client.get("/api/v1/reference/categories/101").json()["classification"]
        == "structural"
    )


def test_explicit_selectability_not_language_filters(environment):
    client, *_ = environment
    login(client)
    found = client.get(
        "/api/v1/reference/categories", params={"q": "Carne proaspata"}
    ).json()
    assert [r["id"] for r in found["items"]] == [107]
    assert found["items"][0]["selectable"]
    assert (
        client.get("/api/v1/reference/categories?q=Deleted&view=all").json()["items"]
        == []
    )
    assert client.get("/api/v1/reference/categories/108/selection").status_code == 404


def test_structural_parent_children_and_complete_path(environment):
    client, *_ = environment
    login(client)
    roots = client.get("/api/v1/reference/categories").json()
    assert {r["id"] for r in roots["items"]} == {10, 30, 50, 101, 107}
    children = client.get("/api/v1/reference/categories?parent_id=101").json()
    assert [r["id"] for r in children["items"]] == [105]
    assert not children["items"][0]["missing_parent"]
    detail = client.get("/api/v1/reference/categories/106").json()
    assert [r["id"] for r in detail["path"]] == [101, 105, 106]
    assert detail["parent_id"] == 105 and detail["hierarchy_error"] is None
    assert detail["ancestors"][0]["selectable"] is False
    assert [
        r["id"]
        for r in client.get("/api/v1/reference/categories?parent_id=10").json()["items"]
    ] == [102, 20]


@pytest.mark.parametrize("id", [101, 102, 104])
def test_structural_categories_never_selectable_even_in_all_view(environment, id):
    client, *_ = environment
    login(client)
    detail = client.get(f"/api/v1/reference/categories/{id}?view=all")
    assert detail.status_code == 200 and detail.json()["selectable"] is False
    assert client.get(f"/api/v1/reference/categories/{id}/selection").status_code == 409


@pytest.mark.parametrize("id", [103, 108])
def test_deleted_marker_hidden_even_if_allowed_and_even_in_all_view(environment, id):
    client, *_ = environment
    login(client)
    assert client.get(f"/api/v1/reference/categories/{id}?view=all").status_code == 404
    assert (
        client.get(f"/api/v1/reference/categories?parent_id={id}&view=all").status_code
        == 404
    )
    assert client.get(f"/api/v1/reference/categories/{id}/selection").status_code == 404


def test_parameter_browsing_does_not_imply_product_selection(environment):
    client, *_ = environment
    login(client)
    parameters = client.get("/api/v1/reference/parameters?category_id=101").json()
    assert parameters["items"][0]["id"] == 170
    assert client.get("/api/v1/reference/parameters/170/values").status_code == 200
    assert client.get("/api/v1/reference/categories/101/selection").status_code == 409
    selection = client.get("/api/v1/reference/categories/105/selection").json()
    assert selection["parameter_source_category_id"] == 105
    assert (
        selection["parameter_inheritance"] is False
        and selection["reference_writes_allowed"] is False
    )
    assert (
        client.get("/api/v1/reference/parameters?category_id=105").json()["items"][0][
            "id"
        ]
        == 171
    )
    # No inheritance: parameter 170 belongs to structural parent 101, not child 105.
    assert client.get("/api/v1/reference/parameters?category_id=104").status_code == 404
    assert (
        client.get("/api/v1/reference/parameters/172/values?view=all").status_code
        == 200
    )


def test_search_returns_full_structural_path_and_counts(environment):
    client, *_ = environment
    login(client)
    item = client.get("/api/v1/reference/categories?q=Aktív%20unoka").json()["items"][0]
    assert [p["id"] for p in item["path"]] == [101, 105, 106]
    parent = client.get("/api/v1/reference/categories/101").json()
    assert parent["children_count"] == 1 and parent["parameter_count"] == 1
    assert (
        parent["mandatory_parameter_count"] == 1
        and parent["optional_parameter_count"] == 0
    )
    assert parent["parent_id"] is None
