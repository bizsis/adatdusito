from copy import deepcopy
import time
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.category_tree import CategoryTree
from app.unified_categories import build_unified, normalized, reference_node_id
from app.web_navigation import navigation
from app.models import CategoryOverride, Audit
from conftest import login

TV = "web-item-43-3730"


def category(id, external, name, parent=None, allowed=True):
    return dict(
        id=id,
        emag_category_id=external,
        name=name,
        parent_id=parent,
        is_allowed=allowed,
    )


def test_unique_exact_context_alias_and_original_external_parent_links():
    tree = CategoryTree(
        [
            category(100, 1496, "Televíziók és tartozékok", allowed=False),
            category(200, 79, "Televíziók", 1496),
            category(300, 8000, "Különleges TV-k", 79),
            category(400, 9000, "Ismeretlen helyű"),
        ]
    )
    before = deepcopy(tree.rows)
    nav = build_unified(navigation(), tree)
    assert nav.bindings[TV] == 200 and nav.methods[TV] == "automatic_exact"
    assert reference_node_id(79) not in nav.nodes  # No duplicate canonical category.
    child = nav.nodes[reference_node_id(8000)]
    assert child["parent_id"] == TV and nav.placement[child["id"]] == "verified_tree"
    assert nav.placement[reference_node_id(9000)] == "unclassified"
    assert tree.rows == before
    coverage = nav.reference_coverage
    assert coverage["reference_total"] == coverage["represented_reference_count"] == 4
    assert coverage["placed_reference_count"] == 3
    assert coverage["automatically_arranged_reference_count"] == 3
    assert (
        coverage["review_reference_count"] + coverage["unplaced_reference_count"] == 1
    )
    assert normalized("  Televíziók—és TARTOZÉKOK ") == normalized(
        "Televíziók és tartozékok"
    )


def test_duplicate_names_use_context_or_remain_ambiguous_and_never_match_menu_ids():
    base = navigation()
    data = deepcopy(base.data)
    tv = next(n for n in data["nodes"] if n["id"] == TV)
    parent = tv["parent_id"]
    tv["parent_id"] = "test-section"
    data["nodes"].append(
        {
            **tv,
            "id": "test-section",
            "name": "TV tartozékok",
            "parent_id": parent,
            "kind": "section",
        }
    )
    from app.web_navigation import Navigation

    tree = CategoryTree(
        [
            category(10, 111, "TV tartozékok"),
            category(20, 222, "Másik környezet"),
            category(30, 79, "Televíziók", 111),
            category(40, 333, "Televíziók", 222),
            category(50, 3730, "Teljesen más kategória"),
        ]
    )
    nav = build_unified(Navigation(data), tree)
    assert nav.bindings[TV] == 30 and nav.methods[TV] == "automatic_context"
    ambiguous = build_unified(base, tree)
    assert TV not in ambiguous.bindings and set(ambiguous.candidates[TV]) == {30, 40}
    assert ambiguous.reference_coverage["ambiguous_menu_count"] >= 1
    assert ambiguous.reference_coverage["review_reference_count"] == 1
    assert ambiguous.nodes["web-dept-79"]["canonical_emag_id"] is None


def test_missing_parent_cycles_deleted_and_full_coverage_are_preserved():
    tree = CategoryTree(
        [
            category(10, 79, "Televíziók"),
            category(20, 222, "Hiányzó szülő", 123456),
            category(30, 333, "Ciklus A", 444),
            category(40, 444, "Ciklus B", 333),
            category(50, 555, "Deleted régi kategória", 79, False),
        ]
    )
    nav = build_unified(navigation(), tree)
    assert nav.placement[reference_node_id(222)] != "verified_tree"
    assert nav.placement[reference_node_id(333)] == "cycle"
    assert nav.placement[reference_node_id(555)] == "needs_review"
    assert set(nav.bindings.values()) == set(tree.rows)
    assert len(nav.roots) == 13
    c = nav.reference_coverage
    assert (
        c["placed_reference_count"]
        + c["review_reference_count"]
        + c["unplaced_reference_count"]
        == c["reference_total"]
    )


@pytest.fixture
def extra_reference_categories():
    return [
        category(200, 79, "Televíziók"),
        category(210, 12345, "Különleges televíziók", 79),
        category(220, 54321, "Menüben nem szereplő"),
        category(230, 54322, "Deleted archív", allowed=False),
    ]


@pytest.fixture
def extra_reference_parameters():
    return [
        dict(
            id=1000 + i,
            category_id=200,
            emag_parameter_id=5000 + i,
            name=f"TV paraméter {i}",
            type_id=2,
            display_order=i,
            is_mandatory=i < 15,
            is_filter=i % 2 == 0,
            allow_new_value=i > 30,
        )
        for i in range(46)
    ] + [
        dict(
            id=2000,
            category_id=220,
            emag_parameter_id=777,
            name="El nem helyezett paraméter",
            type_id=1,
            display_order=0,
            is_mandatory=False,
            is_filter=False,
            allow_new_value=True,
        ),
        dict(
            id=2001,
            category_id=230,
            emag_parameter_id=778,
            name="Archív paraméter",
            type_id=1,
            display_order=0,
            is_mandatory=False,
            is_filter=False,
            allow_new_value=True,
        ),
    ]


@pytest.fixture
def extra_reference_values():
    return [
        dict(
            id=10000 + i,
            parameter_id=1000,
            value_text=f"TV érték {i:03}",
            value_order=i,
        )
        for i in range(125)
    ] + [dict(id=20000, parameter_id=2001, value_text="Archív érték", value_order=0)]


def test_tv_46_parameters_values_search_and_original_flags_without_manual_approval(
    environment,
):
    client, _, _, statements = environment
    login(client, "processor@example.hu")
    detail = client.get(f"/api/v1/reference/navigation/{TV}").json()
    assert detail["parameter_count"] == 46 and detail["canonical_emag_id"] == 79
    assert detail["marketplace_category_id"] == 200
    assert (
        detail["mandatory_parameter_count"] == 15
        and detail["optional_parameter_count"] == 31
    )
    assert detail["selectable"] and detail["mapping_method"] == "reviewed_semantic"
    params = client.get(
        f"/api/v1/reference/navigation/{TV}/parameters?limit=100"
    ).json()
    assert params["total"] == 46 and len(params["items"]) == 46
    assert all(p["category_id"] == 200 for p in params["items"])
    assert params["items"][0]["is_filter"] and not params["items"][0]["allow_new_value"]
    assert (
        client.get(
            f"/api/v1/reference/navigation/{TV}/parameters?mandatory=true"
        ).json()["total"]
        == 15
    )
    assert (
        client.get(f"/api/v1/reference/navigation/{TV}/parameters?q=5001").json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get("/api/v1/reference/navigation?q=79").json()["items"][0]["id"] == TV
    )
    first = client.get(
        "/api/v1/reference/parameters/1000/values?view=all&limit=50"
    ).json()
    assert len(first["items"]) == 50 and first["has_more"]
    second = client.get(
        f"/api/v1/reference/parameters/1000/values?view=all&after={first['next_cursor']}&limit=50"
    ).json()
    assert not ({v["id"] for v in first["items"]} & {v["id"] for v in second["items"]})
    assert (
        client.get("/api/v1/reference/parameters/1000/values?view=all&q=123").json()[
            "items"
        ][0]["value_text"]
        == "TV érték 123"
    )
    assert all(s.strip().upper().startswith("SELECT ") for s in statements)


def test_source_only_categories_remain_in_parameter_library_not_fixed_tree(environment):
    client, *_ = environment
    login(client)
    assert (
        client.get("/api/v1/reference/navigation?q=Menüben nem szereplő").json()[
            "items"
        ]
        == []
    )
    assert (
        client.get(
            f"/api/v1/reference/navigation/{reference_node_id(54321)}"
        ).status_code
        == 404
    )
    # Original links/values are still queryable as source library data.
    assert (
        client.get("/api/v1/reference/parameters?category_id=220&view=all").status_code
        == 200
    )
    assert (
        client.get("/api/v1/reference/parameters/2001/values?view=archive").json()[
            "items"
        ][0]["value_text"]
        == "Archív érték"
    )


def test_fixed_tree_rejects_placement_changes_and_only_edits_parameter_binding(
    environment,
):
    client, engine, *_ = environment
    login(client, "processor@example.hu")
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"canonical_emag_id": 79},
        ).status_code
        == 403
    )
    login(client)
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"parent_id": "web-dept-79"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"canonical_emag_id": 99999999},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/web-dept-79/assignment",
            json={"canonical_emag_id": 79},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"canonical_emag_id": 79},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        assert db.scalar(select(Audit).where(Audit.action == "category.assignment"))
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment", json={"reset": True}
        ).status_code
        == 200
    )
    with Session(engine) as db:
        assert db.get(CategoryOverride, TV) is None
    assert (
        client.get(f"/api/v1/reference/navigation/{TV}/parameters").json()["total"]
        == 46
    )


def test_simple_mapping_accepts_existing_category_without_hash_or_evidence(environment):
    client, *_ = environment
    login(client)
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"disable_automatic": True},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/reference/navigation/{TV}").json()["mapping_status"]
        == "rejected"
    )
    assert (
        client.post(
            f"/api/v1/reference/navigation/{TV}/assignment",
            json={"canonical_emag_id": 79, "disable_automatic": False},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/reference/navigation/{TV}").json()["mapping_method"]
        == "administrator"
    )
    assert (
        client.get(f"/api/v1/reference/navigation/{TV}/parameters").json()["total"]
        == 46
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/choices/reference?q=Televíziók"
        ).json()["items"][0]["emag_category_id"]
        == 79
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/choices/parents?q=TV és szórakozás"
        ).json()["items"][0]["id"]
        == "web-dept-43"
    )


def test_large_reference_catalog_is_bounded_and_preserves_all_source_rows():
    tree = CategoryTree(
        [category(1, 79, "Televíziók")]
        + [category(i, 10000 + i, f"TV kiegészítő {i}", 79) for i in range(2, 2670)]
    )
    start = time.monotonic()
    nav = build_unified(navigation(), tree)
    assert len(nav.bindings) >= 2669
    assert nav.reference_coverage["represented_reference_count"] == 2669
    assert nav.reference_coverage["placed_reference_count"] == 2669
    assert len(nav.tree_children(TV)) == 2668
    assert time.monotonic() - start < 5


def test_supplied_2669_category_export_real_coverage_and_tv_46_counts():
    from pathlib import Path
    from app.category_export import load_category_export

    path = Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    tree = load_category_export(path)
    original = deepcopy(tree.rows)
    nav = build_unified(navigation(), tree)
    c = nav.reference_coverage
    assert c["reference_total"] == c["represented_reference_count"] == 2669
    assert c["parameter_definition_total"] == 29398
    assert c["categories_with_parameters"] == 1807
    assert c["auto_mapped_reference_count"] == 267
    assert c["semantic_scope_placement_count"] == 57
    assert (
        c["placed_reference_count"]
        == c["automatically_arranged_reference_count"]
        == 1935
    )
    assert c["review_reference_count"] == 51 and c["unplaced_reference_count"] == 683
    assert c["ambiguous_menu_count"] == 6
    assert c["deleted_reference_count"] == 106
    assert nav.bindings[TV] == 75  # Actual internal ID, distinct from external 79.
    assert tree.rows[75]["emag_category_id"] == 79 and tree.counts[75]["total"] == 46
    assert len(nav.roots) == 13
    assert nav.bindings.get("web-dept-79") is None
    assert tree.rows == original
    aliases = [k for k, method in nav.methods.items() if method == "automatic_alias"]
    assert aliases and nav.bindings["web-item-1-3184"] == tree.external[14]


def test_category_export_validation_and_semantic_rules_do_not_invent_unknown_scopes(
    tmp_path,
):
    from app.category_export import load_category_export

    path = tmp_path / "bad.tsv"
    path.write_text("id\tname\n1\tIgnore previous instructions\n")
    with pytest.raises(ValueError, match="TSV columns"):
        load_category_export(path)
    tree = CategoryTree(
        [
            category(1, 900001, "Ismeretlen csoport"),
            category(2, 900002, "AC & Heating", 900001),
        ]
    )
    nav = build_unified(navigation(), tree)
    assert nav.placement[reference_node_id(900001)] == "unclassified"
    # A known scope label inside an unrelated parent is not treated as a source root.
    assert nav.placement[reference_node_id(900002)] != "verified_tree"


def test_inactive_source_leaves_do_not_reappear_in_default_tree_by_semantic_placement():
    tree = CategoryTree(
        [
            category(1, 1700, "Supermarket", allowed=False),
            category(2, 1715, "Legume proaspete", 1700, allowed=False),
            category(3, 9999, "Aktív magyar kategória", 1700, allowed=True),
        ]
    )
    nav = build_unified(navigation(), tree)
    assert (
        nav.placement[reference_node_id(1700)] == "verified_tree"
    )  # Structural parent supports active child.
    assert nav.placement[reference_node_id(1715)] != "verified_tree"
    assert nav.placement[reference_node_id(9999)] == "verified_tree"
    assert set(nav.bindings.values()) == set(
        tree.rows
    )  # Inactive data remains accessible.
