import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Audit
from conftest import login
from app.web_navigation import navigation

ROOT_NAMES = [
    "Háztartási gépek és klíma",
    "TV és szórakozás",
    "Telefon, Tablet, Laptop",
    "Számítástechnika",
    "Fotó-Videó, Okos eszközök",
    "Szupermarket",
    "Otthon, barkács, kert",
    "Játékok, Baba, Mama",
    "Divat, ékszerek és kiegészítők",
    "Szépségápolás",
    "Sport és utazás",
    "Könyvek, Filmek és Irodaszerek",
    "Autó- és motor felszerelések",
]


@pytest.fixture
def extra_reference_categories():
    return [
        dict(
            id=200,
            emag_category_id=79,
            parent_id=None,
            name="Televíziók",
            is_allowed=True,
        )
    ]


@pytest.fixture
def extra_reference_parameters():
    return [
        dict(
            id=270,
            category_id=200,
            emag_parameter_id=9999,
            name="TV képernyő",
            type_id=2,
            display_order=1,
            is_mandatory=True,
            is_filter=True,
            allow_new_value=False,
        )
    ]


def proof(node="web-item-43-3730", **overrides):
    return dict(
        source_key="emag_webshop",
        source_category_id=node,
        evidence_url="https://www.emag.hu/televiziok/c",
        outcome="available",
        mapping_status="confirmed",
        canonical_emag_id=79,
        evidence_kind="documented_crosswalk",
        content_sha256="a" * 64,
        summary="Szintetikus, explicit operátori megfeleltetési bizonyíték.",
        **overrides,
    )


def test_actual_13_roots_order_and_namespace_separation(environment):
    client, *_ = environment
    login(client)
    response = client.get("/api/v1/reference/navigation").json()
    assert (
        response["total"] == 13 and [n["name"] for n in response["items"]] == ROOT_NAMES
    )
    books = next(n for n in response["items"] if n["id"] == "web-dept-79")
    assert books["canonical_emag_id"] is None and not books["selectable"]
    tv = client.get("/api/v1/reference/navigation/web-item-43-3730").json()
    assert (
        tv["name"] == "Televíziók"
        and tv["canonical_emag_id"] == 79
        and tv["mapping_status"] == "confirmed"
        and tv["mapping_method"] == "automatic_exact"
    )
    assert tv["parameter_count"] == 1  # Direct existing fixture parameter, no copy.
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/parameters"
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/selection"
        ).status_code
        == 200
    )


def test_dom_sections_facets_brands_and_reviewed_unknown_groups(environment):
    client, *_ = environment
    login(client)
    washing = client.get("/api/v1/reference/navigation/web-item-114-3487").json()
    assert (
        washing["name"] == "Mosógépek és szárítógépek" and washing["kind"] == "section"
    )
    children = client.get(
        "/api/v1/reference/navigation?parent_id=" + washing["id"]
    ).json()["items"]
    assert any(n["name"] == "Elöltöltős mosógépek" for n in children)
    television = client.get("/api/v1/reference/navigation/web-item-43-3730").json()
    assert any(
        n["name"] == "LED TV" and n["kind"] == "parameter_filter"
        for n in television["related_links"]
    )
    root = client.get("/api/v1/reference/navigation/web-dept-114").json()
    assert any(n["kind"] == "brand" for n in root["related_links"])
    # The operator-approved former filter is now a fixed structural point.
    assert (
        client.get("/api/v1/reference/navigation/web-item-114-3490").status_code == 200
    )
    assert (
        client.get("/api/v1/reference/navigation/web-item-114-4165").status_code == 404
    )
    unresolved = next(
        n
        for n in navigation().nodes.values()
        if n["kind"] == "category" and n["hierarchy_status"] == "needs_review"
    )
    assert (
        client.get("/api/v1/reference/navigation/" + unresolved["id"]).json()[
            "hierarchy_status"
        ]
        == "verified_assignment"
    )


def test_explicit_mapping_reads_correct_internal_fk_and_can_be_revoked(environment):
    client, engine, *_ = environment
    login(client)
    confirmed = client.post("/api/v1/reference/sources/observations", json=proof())
    assert confirmed.status_code == 201
    selected = client.get(
        "/api/v1/reference/navigation/web-item-43-3730/selection"
    ).json()
    assert selected["emag_category_id"] == 79 and selected["category_id"] == 200
    assert (
        not selected["reference_writes_allowed"]
        and not selected["parameter_inheritance"]
    )
    params = client.get(
        "/api/v1/reference/navigation/web-item-43-3730/parameters"
    ).json()
    assert [p["id"] for p in params["items"]] == [270]
    assert (
        client.get("/api/v1/reference/navigation/web-item-43-3730").json()[
            "parameter_count"
        ]
        == 1
    )
    revoked = proof()
    revoked.update(
        mapping_status="pending",
        canonical_emag_id=None,
        evidence_kind=None,
        content_sha256=None,
    )
    assert (
        client.post("/api/v1/reference/sources/observations", json=revoked).status_code
        == 201
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/selection"
        ).status_code
        == 409
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/parameters"
        ).status_code
        == 409
    )
    with Session(engine) as db:
        assert db.scalar(
            select(Audit).where(Audit.action == "reference.source_observation")
        )


def test_root_brand_filter_cannot_be_promoted_to_product_category(environment):
    client, *_ = environment
    login(client)
    for id in ["web-dept-79", "web-item-114-3490", "web-item-114-4165"]:
        assert (
            client.post(
                "/api/v1/reference/sources/observations", json=proof(node=id)
            ).status_code
            == 409
        )
    assert (
        client.post(
            "/api/v1/reference/sources/observations",
            json=proof(node="web-item-does-not-exist"),
        ).status_code
        == 404
    )
    login(client, "admin@example.hu")
    assert (
        client.post("/api/v1/reference/sources/observations", json=proof()).status_code
        == 403
    )


def test_shared_navigation_search_pagination_and_reference_readonly(environment):
    client, _, _, statements = environment
    login(client, "processor@example.hu")
    assert client.get("/api/v1/reference/navigation").json()["total"] == 13
    first = client.get("/api/v1/reference/navigation?limit=1&offset=0").json()
    assert first["items"][0]["name"] == ROOT_NAMES[0] and first["total"] == 13
    hit = client.get("/api/v1/reference/navigation?q=Televíziók").json()["items"][0]
    assert [p["name"] for p in hit["path"]] == ["TV és szórakozás", "Televíziók"]
    coverage = client.get("/api/v1/reference/navigation/coverage").json()
    assert coverage["root_count"] == 13 and coverage["manifest_link_count"] == 609
    assert (
        coverage["reference_coverage"]["represented_reference_count"] == 7
        and not coverage["full_category_tree_verified"]
    )
    assert coverage["hierarchy_needs_review"] == 79
    assert all(s.strip().upper().startswith("SELECT ") for s in statements)


def test_mapping_approval_is_bound_to_source_snapshot(environment, monkeypatch):
    from app import web_navigation

    client, *_ = environment
    login(client)
    response = client.post("/api/v1/reference/sources/observations", json=proof())
    assert response.status_code == 201
    assert response.json()["source_category_id"].endswith(
        "@" + navigation().data["archive_sha256"]
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/selection"
        ).status_code
        == 200
    )
    changed = web_navigation.Navigation(
        {**navigation().data, "archive_sha256": "b" * 64}
    )
    monkeypatch.setattr(web_navigation, "navigation", lambda: changed)
    assert (
        client.get(
            "/api/v1/reference/navigation/web-item-43-3730/selection"
        ).status_code
        == 200
    )

    assert (
        client.get("/api/v1/reference/navigation/web-item-43-3730").json()[
            "mapping_method"
        ]
        == "automatic_exact"
    )


def test_root_registry_and_separate_unclassified_list_preserve_source_graph(
    environment, monkeypatch
):
    from copy import deepcopy
    from app import web_navigation

    client, *_ = environment
    login(client)
    data = deepcopy(navigation().data)
    template = deepcopy(next(n for n in data["nodes"] if n["kind"] == "category"))
    for key, parent in [
        ("unplaced", None),
        ("orphan", "missing-parent"),
        ("cycle-a", "cycle-b"),
        ("cycle-b", "cycle-a"),
    ]:
        data["nodes"].append(
            {**template, "id": key, "name": "Teszt " + key, "parent_id": parent}
        )
    before = deepcopy(data)
    nav = web_navigation.Navigation(data)
    monkeypatch.setattr(web_navigation, "navigation", lambda: nav)
    response = client.get("/api/v1/reference/navigation").json()
    assert response["total"] == 13
    assert [n["id"] for n in response["items"]] == data["verified_root_ids"]
    listed = client.get(
        "/api/v1/reference/navigation?scope=unclassified&limit=100"
    ).json()
    assert {"unplaced", "orphan", "cycle-a", "cycle-b"}.isdisjoint(
        {n["id"] for n in listed["items"]}
    )
    assert nav.placement["unplaced"] == "unclassified"
    assert nav.placement["orphan"] == "missing_parent"
    assert nav.placement["cycle-a"] == "cycle"
    found = client.get("/api/v1/reference/navigation?q=Teszt&limit=100").json()
    assert found["total"] == 0
    assert client.get("/api/v1/reference/navigation/orphan").status_code == 404
    assert data == before  # Indexing/search never repairs identities or parents.


def test_uncertain_children_are_separate_but_remain_globally_searchable(environment):
    client, *_ = environment
    login(client)
    nav = navigation()
    pending = next(
        n
        for n in nav.nodes.values()
        if n["kind"] == "category" and n["hierarchy_status"] == "needs_review"
    )
    from app.curated_taxonomy import apply_taxonomy

    pending = apply_taxonomy(nav).nodes[pending["id"]]
    children = client.get(
        "/api/v1/reference/navigation",
        params={"parent_id": pending["parent_id"], "limit": 100},
    ).json()
    assert pending["id"] in {n["id"] for n in children["items"]}
    assert all(n["placement_status"] == "verified_tree" for n in children["items"])
    review = client.get(
        "/api/v1/reference/navigation?scope=unclassified&limit=100"
    ).json()
    assert pending["id"] not in {n["id"] for n in review["items"]}
    found = client.get(
        "/api/v1/reference/navigation",
        params={"q": pending["name"], "parent_id": "web-dept-43"},
    ).json()
    assert pending["id"] in {n["id"] for n in found["items"]}
    # Requesting one branch returns only immediate verified children, not descendants.
    root = client.get("/api/v1/reference/navigation/web-dept-114").json()
    branch = client.get(
        "/api/v1/reference/navigation?parent_id=web-dept-114&limit=100"
    ).json()
    assert root["children_count"] == branch["total"]
    assert all(n["parent_id"] == "web-dept-114" for n in branch["items"])
    assert "web-item-114-3490" not in {n["id"] for n in branch["items"]}


def test_unverified_department_cannot_enter_root_registry():
    from copy import deepcopy
    from app.web_navigation import Navigation

    data = deepcopy(navigation().data)
    data["verified_root_ids"].append("web-item-43-3730")
    with pytest.raises(ValueError, match="13 explicitly verified"):
        Navigation(data)
