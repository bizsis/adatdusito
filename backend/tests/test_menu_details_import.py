from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from app.menu_details_import import process_details_archive
from app.web_navigation import navigation
from conftest import login

FIXTURE = Path(__file__).parent / "fixtures/emag-menu-details.zip"


def changed_archive(tmp_path, mutate, corrupt=False):
    with zipfile.ZipFile(FIXTURE) as z:
        data = json.loads(z.read("menu-details.json"))
    mutate(data)
    raw = json.dumps(data, ensure_ascii=False).encode()
    digest = "0" * 64 if corrupt else hashlib.sha256(raw).hexdigest()
    path = tmp_path / "modified.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("menu-details.json", raw)
        z.writestr("SHA256.txt", digest + "  menu-details.json\r\n")
    return path


def test_real_details_reproduce_shared_snapshot_without_changing_graph():
    original = navigation().data
    result = process_details_archive(FIXTURE, original)
    assert result == original
    assert len(result["nodes"]) == 636
    summary = result["details_verification"]
    assert summary["menu_item_count"] == 623
    assert summary["verified_parent_connections"] == 544
    assert summary["explicit_section_connections"] == 415
    assert summary["direct_department_connections"] == 129
    assert summary["needs_review"] == len(result["issues"]) == 79
    assert summary["changed_parent_connections"] == 0
    assert len(summary["category_pages"]) == 1
    assert summary["category_pages"][0]["identifiers"][-1]["namespace"] == "unverified"
    assert all(n["canonical_emag_id"] is None for n in result["nodes"])
    assert not result["canonical_mappings"]
    assert not result["full_category_tree_verified"]
    assert original == navigation().data


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d["menu_panels"].reverse(), "order"),
        (lambda d: d["menu_panels"].pop(), "13 departments"),
        (
            lambda d: d["menu_panels"][0]["dom"][0]["items"].append(
                d["menu_panels"][0]["dom"][0]["items"][0]
            ),
            "Duplicate",
        ),
        (
            lambda d: d["menu_panels"][0]["dom"][0]["items"][1].update(
                parent_menu_item_id="79"
            ),
            "DOM ancestry",
        ),
        (
            lambda d: d["menu_panels"][0]["dom"][0]["items"][1].update(
                identifier_namespace="marketplace"
            ),
            "identity",
        ),
        (
            lambda d: d["category_pages"][0]["identifiers"][0].update(
                namespace="marketplace"
            ),
            "namespace",
        ),
        (lambda d: d["errors"].append({"error": "timeout"}), "complete"),
    ],
)
def test_rejects_unproven_conflicting_or_incomplete_details(tmp_path, mutation, match):
    before = deepcopy(navigation().data)
    with pytest.raises(ValueError, match=match):
        process_details_archive(changed_archive(tmp_path, mutation), before)
    assert before == navigation().data


def test_checksums_and_conflicting_existing_parent_are_checked(tmp_path):
    with pytest.raises(ValueError, match="checksum"):
        process_details_archive(
            changed_archive(tmp_path, lambda d: None, corrupt=True), navigation().data
        )
    modified = deepcopy(navigation().data)
    modified["nodes"][2]["parent_id"] = "web-dept-114"
    with pytest.raises(ValueError, match="Conflicting hierarchy"):
        process_details_archive(FIXTURE, modified)


def test_coverage_exposes_evidence_counts_without_creating_bindings(environment):
    client, *_ = environment
    login(client)
    data = client.get("/api/v1/reference/navigation/coverage").json()
    assert data["root_count"] == 13
    assert data["hierarchy_needs_review"] == 79
    assert data["confirmed_bindings"] == 0
    assert data["details_verification"]["verified_parent_connections"] == 544
    assert data["details_verification"]["changed_parent_connections"] == 0
    assert data["details_verification"]["new_marketplace_bindings"] == 0
