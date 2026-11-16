"""CATEGORY-02C: regression guard for the 457 bindable categories and donor choice."""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import product_catalog as pc

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL = json.loads((ROOT / "docs/reports/reviewed-parameter-profiles.json").read_text(encoding="utf-8"))
RULES = json.loads(
    (ROOT / "backend/reference_data/reviewed_parameter_bindings.json").read_text(encoding="utf-8")
)["rules"]
RETIRED = "web-item-43-3550"


def report_module():
    spec = importlib.util.spec_from_file_location("report_category_457", ROOT / "scripts/report_category_457.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report():
    return report_module().build()


def fixed_tree():
    from app.curated_taxonomy import apply_taxonomy
    from app.web_navigation import navigation

    base = apply_taxonomy(navigation())
    return {k: n for k, n in base.nodes.items() if n.get("taxonomy_version")}


def test_457_ids_are_unique_legal_bindable_nodes():
    cats = pc.internal_categories()
    tree = fixed_tree()
    assert len(cats) == 457
    assert len(RULES) == 457 and len({r["node_id"] for r in RULES}) == 457
    assert set(cats) == {r["node_id"] for r in RULES}
    for key, node in cats.items():
        assert key in tree and tree[key]["kind"] == "category"
        assert not tree[key].get("structural_only")
        assert node["path"][-1] == tree[key]["name"] and node["donors"]


def test_profiles_belong_only_to_their_own_node():
    cats = pc.internal_categories()
    for rule in RULES:
        node = cats[rule["node_id"]]
        assert node["path"] == rule["path"]
        assert [d["emag_category_id"] for d in node["donors"]] == [
            d["emag_category_id"] for d in rule["donors"]
        ]
        assert len({d["emag_category_id"] for d in rule["donors"]}) == len(rule["donors"])
    # A donor of another node is rejected for this node.
    a, b = "web-item-114-3490", "web-item-114-3820"  # 385 Mosógépek vs 58 Porszívók
    with pytest.raises(HTTPException) as err:
        pc.validate_target(a, 58)
    assert err.value.status_code == 422
    with pytest.raises(HTTPException):
        pc.validate_target(b, 385)


def test_13_roots_and_583_nodes_are_unchanged():
    tree = fixed_tree()
    roots = [k for k, n in tree.items() if n["parent_id"] is None]
    assert roots == HISTORICAL["roots"] and len(roots) == 13
    assert len(tree) == 583 == HISTORICAL["approved_nodes"]
    assert {k: (n["name"], n["parent_id"]) for k, n in tree.items()} == {
        e["id"]: (e["name"], e["parent_id"]) for e in HISTORICAL["entries"]
    }


def test_retired_and_structural_nodes_are_not_classifiable():
    cats = pc.internal_categories()
    assert RETIRED not in cats and RETIRED not in fixed_tree()
    structural = [k for k in fixed_tree() if k not in cats]
    assert len(structural) == 126
    for key in [RETIRED, *structural]:
        with pytest.raises(HTTPException) as err:
            pc.validate_target(key, None)
        assert err.value.status_code == 422


def test_multi_profile_categories_require_explicit_choice():
    multi = {k: n for k, n in pc.internal_categories().items() if len(n["donors"]) > 1}
    assert len(multi) == 23
    for key, node in multi.items():
        assert pc.default_donor(key) is None
        assert pc.parameter_profile_state(key, None) == "choice_required"
        assert pc.donor_reasons(key, None) == ["parameter_profile_choice_required"]


def test_98_percent_is_not_a_measured_guarantee_and_uncalibrated_rules_never_auto():
    assert pc.CALIBRATED_PRECISION == {}
    assert pc.DEFAULT_AUTO_THRESHOLD == 0.98
    for threshold in (0.5, 0.9, 0.98, 1.0):
        assert not pc.method_is_automatic("exact_name_match", threshold)

    class Product:
        source_category_id = 1

    decision = pc.decide(None, Product(), {}, 0.5, "Háztartás > Elöltöltős mosógépek")
    assert decision["status"] == pc.REVIEW
    assert decision["navigation_node_id"] is None and decision["confidence"] is None
    assert "uncalibrated_suggestion" in decision["reason_codes"]


def test_exactly_45_newly_bindable_items(report):
    added = report["added"]
    assert report["classification"]["added"] == len(added) == 45
    assert report["classification"]["removed"] == []
    assert {a["old_status"] for a in added} == {"navigation"}
    assert len({a["id"] for a in added}) == 45
    historical_confirmed = {e["id"] for e in HISTORICAL["entries"] if e["status"] == "confirmed"}
    assert set(pc.internal_categories()) == historical_confirmed | {a["id"] for a in added}
    assert all(d["parameter_count"] for a in added for d in a["donors"])
    assert {a["id"] for a in added if a["risk"] == "pending_review"} == {
        "web-item-114-3492", "web-item-114-3820", "web-item-83-4339"
    }


def test_committed_report_is_reproducible():
    assert report_module().main(["--check"]) == 0


def test_donor_review_cannot_name_a_foreign_donor(monkeypatch):
    pc.internal_categories.cache_clear()
    monkeypatch.setattr(pc, "donor_review", lambda: {("web-item-114-3490", 58): "pending_review"})
    try:
        with pytest.raises(ValueError):
            pc.internal_categories()
    finally:
        monkeypatch.undo()
        pc.internal_categories.cache_clear()
    assert len(pc.internal_categories()) == 457
