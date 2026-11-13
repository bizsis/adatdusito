import json
import time
from app.category_tree import CategoryTree
from app.source_evidence import breadcrumb_observations
from conftest import login


def row(id, external, parent=None, allowed=True, name=None):
    return {
        "id": id,
        "emag_category_id": external,
        "parent_id": parent,
        "name": name or f"Kategória {id}",
        "is_allowed": allowed,
    }


def test_tv_structural_parent_1496_and_category_79_have_one_identity():
    tree = CategoryTree(
        [
            row(1, 1496, allowed=False, name="Televíziók és tartozékok"),
            row(2, 79, 1496, name="Televíziók"),
        ],
        {2: {"total": 46, "mandatory": 10, "optional": 36, "unknown": 0}},
    )
    assert tree.navigation == {1, 2} and tree.selectable == {2}
    item = tree.item(2, "navigation", tree.children_counts("navigation"))
    assert [r["emag_category_id"] for r in item["path"]] == [1496, 79]
    assert item["parameter_count"] == 46 and item["parent_id"] == 1


def test_missing_2661_is_not_mapped_to_an_internal_id():
    tree = CategoryTree(
        [row(2661, 9999), row(2, 3904, 2661), row(3, 3306, 2661), row(4, 3810, 2661)]
    )
    assert tree.parents[2] is None
    assert tree.coverage()["missing_parent_ids"] == {2661: 3}
    assert tree.item(2, "navigation")["missing_parent"]


def test_deleted_parent_is_not_invented_and_cycles_are_reachable():
    tree = CategoryTree(
        [
            row(1, 100, name="Deleted régi"),
            row(2, 200, 100),
            row(3, 300, 400),
            row(4, 400, 300),
        ]
    )
    assert 1 not in tree.navigation
    assert tree.item(2, "navigation")["hierarchy_error"] == "excluded_parent"
    assert tree.parent(3, "navigation") is None
    assert tree.item(4, "navigation")["hierarchy_error"] == "cycle"
    assert tree.coverage()["cycle_components"] == [[300, 400]]


def test_large_deep_tree_is_iterative_and_metadata_payload_is_lazy():
    rows = [
        row(i, 100000 + i, 100000 + i - 1 if i > 1 else None, allowed=i == 10000)
        for i in range(1, 10001)
    ]
    before = time.monotonic()
    tree = CategoryTree(rows)
    assert len(tree.navigation) == 10000
    assert tree.coverage()["max_depth"] == 10000
    assert len(tree.path_ids(10000, "navigation")) == 10000
    assert time.monotonic() - before < 5
    # Only category metadata, never the millions of permitted values, is needed.
    assert len(tree.rows) == 10000


def test_coverage_is_runtime_observation_not_webshop_completeness(environment):
    client, *_ = environment
    login(client)
    stats = client.get("/api/v1/reference/coverage").json()
    assert stats["reference_total"] == 6 and stats["categories_with_parameters"] == 2
    assert stats["parameter_definition_total"] == 2
    assert stats["original_root_reachable"] == 3 and stats["max_depth"] == 3
    assert stats["missing_parent_ids"] == {"10": 1}
    assert stats["webshop_completeness"] == "unverified"


def test_structured_breadcrumb_is_pending_even_for_same_name_or_numeric_url():
    data = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "position": 1,
                "name": "Televíziók",
                "item": "https://www.emag.hu/televiziok/c/79",
            },
            {
                "position": 2,
                "name": "Televíziók",
                "item": "https://www.emag.hu/masik/c/999",
            },
        ],
    }
    result = breadcrumb_observations(
        '<script type="application/ld+json">' + json.dumps(data) + "</script>"
    )
    assert len(result[0]) == 2
    assert all(
        r["canonical_emag_id"] is None and r["mapping_status"] == "pending"
        for r in result[0]
    )
    assert result[0][0]["source_category_id"] != result[0][1]["source_category_id"]
    assert (
        breadcrumb_observations('<script type="application/ld+json">invalid</script>')
        == []
    )
