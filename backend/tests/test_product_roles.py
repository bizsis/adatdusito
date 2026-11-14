"""Explicit product roles override archived menu link types without changing edges."""

import json
from pathlib import Path
from copy import deepcopy
import pytest
from app.curated_taxonomy import apply_taxonomy
from app.web_navigation import navigation
from app.fixed_navigation import resolve_fixed
from app.category_export import load_category_export
from app.category_constraints import annotate_parameters


def test_reclassified_products_and_unchanged_hierarchy():
    base = navigation()
    before = deepcopy(base.data)
    nav = resolve_fixed(
        base,
        load_category_export(
            Path(__file__).parent / "fixtures/emag_categories_export.tsv"
        ),
    )
    report = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/reports/reclassified-products.json"
        ).read_text()
    )
    assert len(report) == 45
    assert len(nav.nodes) == 583 and nav.roots == base.roots
    for item in report:
        key = item["node_id"]
        node = nav.nodes[key]
        assert node["kind"] == "category" and not node["structural_only"]
        assert [nav.nodes[k]["name"] for k in nav.path(key)] == item["path"]
        assert [
            nav.reference.rows[i]["emag_category_id"] for i in nav.parameter_donors[key]
        ] == [d["emag_category_id"] for d in item["profiles"]]
    assert base.data == before
    for key in ["web-item-114-3490", "web-item-114-3491", "web-item-114-3492"]:
        assert nav.reference.rows[nav.bindings[key]]["emag_category_id"] == 385
    assert apply_taxonomy(base).nodes["web-item-114-3487"]["kind"] == "section"


@pytest.mark.parametrize(
    "key,value",
    [("web-item-114-3490", "Elöltöltős"), ("web-item-114-3491", "Felültöltős")],
)
def test_loading_constraint_is_category_specific_and_preserves_source(key, value):
    source = {"id": 42, "name": "Betöltés típusa", "is_mandatory": True}
    page = {"items": [dict(source), {"name": "Kapacitás"}], "total": 2}
    result = annotate_parameters(key, page)
    assert result["items"][0]["category_constraint"]["value_text"] == value
    assert {
        k: v for k, v in result["items"][0].items() if k != "category_constraint"
    } == source
    assert "category_constraint" not in result["items"][1]
    assert annotate_parameters("web-item-114-3492", {"items": [dict(source)]})[
        "items"
    ] == [source]


@pytest.fixture
def extra_reference_categories():
    return [
        dict(
            id=19000,
            emag_category_id=385,
            name="Mosógépek",
            parent_id=None,
            is_allowed=False,
        )
    ]


@pytest.fixture
def extra_reference_parameters():
    return [
        dict(
            id=19000,
            category_id=19000,
            emag_parameter_id=9999,
            name="Betöltés típusa",
            type_id=1,
            display_order=0,
            is_mandatory=True,
            is_filter=True,
            allow_new_value=False,
        )
    ]


@pytest.fixture
def extra_reference_values():
    return [
        dict(id=19000 + i, parameter_id=19000, value_text=v, value_order=i)
        for i, v in enumerate(["Elöltöltős", "Felültöltős"])
    ]


@pytest.mark.parametrize("owned", [False, True])
def test_washing_selection_and_constraint_api_without_changing_values(
    environment, owned
):
    from app.catalog_import import import_catalog, SourceReader, activate
    from test_fixed_category_catalog import frozen_data
    from sqlalchemy.orm import Session
    from conftest import login

    client, target, source, _ = environment
    if owned:
        version = import_catalog(target, SourceReader(source), pause_ms=0)
        activate(target, version)
        with Session(target) as db:
            before = frozen_data(db, version)
    login(client)
    for suffix, expected in [
        ("3490", "Elöltöltős"),
        ("3491", "Felültöltős"),
        ("3492", None),
    ]:
        url = "/api/v1/reference/navigation/web-item-114-" + suffix
        detail = client.get(url).json()
        assert detail["selectable"] and not detail["structural_only"]
        assert detail["canonical_emag_id"] == 385
        assert client.get(url + "/selection").status_code == 200
        p = client.get(url + "/parameters").json()["items"][0]
        if expected:
            assert p["category_constraint"]["value_text"] == expected
        else:
            assert "category_constraint" not in p
        values = client.get(
            f"/api/v1/reference/parameters/{p['id']}/values?view=all"
        ).json()["items"]
        assert [v["value_text"] for v in values] == ["Elöltöltős", "Felültöltős"]
    if owned:
        with Session(target) as db:
            assert frozen_data(db, version) == before
