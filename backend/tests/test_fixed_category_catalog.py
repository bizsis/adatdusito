"""The operator-approved tree is immutable; sources only donate parameter sets."""

from copy import deepcopy
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.category_tree import CategoryTree
from app.category_export import load_category_export
from app.fixed_navigation import resolve_fixed
from app.web_navigation import navigation
from app.curated_taxonomy import apply_taxonomy
from app.catalog_import import SourceReader, import_catalog, activate, digest
from app.models import (
    CatalogNode,
    CatalogSourceMapping,
    CatalogLinkEntry,
    CatalogValue,
    CategoryOverride,
    User,
)
from conftest import login

DESKTOP = "web-item-7-3630"


@pytest.fixture
def extra_reference_categories():
    return [
        dict(
            id=5,
            emag_category_id=6,
            name="Asztali számítógép",
            parent_id=None,
            is_allowed=False,
        ),
        dict(
            id=501,
            emag_category_id=60001,
            name="Alternatív asztali számítógép",
            parent_id=None,
            is_allowed=False,
        ),
        dict(
            id=502,
            emag_category_id=60002,
            name="Nagyítók",
            parent_id=None,
            is_allowed=False,
        ),
        dict(
            id=503,
            emag_category_id=60003,
            name="Nagyítók",
            parent_id=None,
            is_allowed=True,
        ),
    ]


@pytest.fixture
def extra_reference_parameters():
    return [
        dict(
            id=8000 + i,
            category_id=5,
            emag_parameter_id=9000 + i,
            name=f"Asztali paraméter {i}",
            type_id=2,
            display_order=i,
            is_mandatory=i % 3 == 0,
            is_filter=i == 0,
            allow_new_value=False,
        )
        for i in range(70)
    ] + [
        dict(
            id=8100 + i,
            category_id=501 + i,
            emag_parameter_id=9900 + i,
            name="Forrásspecifikus érték",
            type_id=2,
            display_order=0,
            is_mandatory=True,
            is_filter=False,
            allow_new_value=False,
        )
        for i in range(3)
    ]


@pytest.fixture
def extra_reference_values():
    return [dict(id=90000, parameter_id=8000, value_text="Intel", value_order=0)] + [
        dict(
            id=90001 + i,
            parameter_id=8100 + i,
            value_text=f"Alternatív érték {i}",
            value_order=0,
        )
        for i in range(3)
    ]


def test_every_fixed_id_name_parent_and_order_ignores_all_source_activity_flags():
    original = load_category_export(
        Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    )
    before = deepcopy(original.rows)
    expected = apply_taxonomy(navigation())
    fixed_ids = [k for k, n in expected.nodes.items() if n.get("taxonomy_version")]
    snapshots = []
    for flag in (0, 1, None):
        tree = CategoryTree(
            [{**r, "is_allowed": flag} for r in original.rows.values()], original.counts
        )
        nav = resolve_fixed(navigation(), tree)
        assert list(nav.nodes) == fixed_ids and len(nav.nodes) == 584
        assert all(
            nav.nodes[k]["parent_id"] == expected.nodes[k]["parent_id"]
            and nav.nodes[k]["name"] == expected.nodes[k]["name"]
            for k in fixed_ids
        )
        assert nav.bindings[DESKTOP] == original.external[6]
        assert tree.counts[nav.bindings[DESKTOP]]["total"] == 70
        assert not any(k.startswith("ref-") for k in nav.nodes)
        snapshots.append(nav.bindings)
    assert snapshots[0] == snapshots[1] == snapshots[2]
    assert original.rows == before


def frozen_data(db, version):
    return {
        "values": [
            (r.id, r.key, r.parameter_id, r.value_text)
            for r in db.scalars(select(CatalogValue).order_by(CatalogValue.id))
        ],
        "mappings": [
            (
                r.kind,
                r.source_id,
                r.target_id,
                r.context_id,
                r.ordinal,
                r.payload_sha256,
                digest(r.data),
            )
            for r in db.scalars(
                select(CatalogSourceMapping)
                .where(CatalogSourceMapping.version_id == version)
                .order_by(CatalogSourceMapping.kind, CatalogSourceMapping.source_id)
            )
        ],
        "links": [
            (
                r.link_id,
                r.category_id,
                r.parameter_id,
                r.name,
                r.is_mandatory,
                r.is_filter,
                r.allow_new_value,
            )
            for r in db.scalars(
                select(CatalogLinkEntry)
                .where(CatalogLinkEntry.version_id == version)
                .order_by(CatalogLinkEntry.link_id)
            )
        ],
        "nodes": [
            (r.key, r.category_id, digest(r.data))
            for r in db.scalars(
                select(CatalogNode)
                .where(CatalogNode.version_id == version)
                .order_by(CatalogNode.key)
            )
        ],
    }


@pytest.mark.parametrize("owned", [False, True])
def test_inactive_source_supplies_70_parameters_without_changing_fixed_taxonomy(
    environment, owned
):
    client, target, source, _ = environment
    if owned:
        version = import_catalog(target, SourceReader(source), pause_ms=0)
        activate(target, version)
        with Session(target) as db:
            before = frozen_data(db, version)
    login(client)
    roots = client.get("/api/v1/reference/navigation").json()
    assert [n["id"] for n in roots["items"]] == navigation().roots
    desktop = client.get("/api/v1/reference/navigation/" + DESKTOP).json()
    assert (
        desktop["canonical_emag_id"] == 6 and desktop["mapping_status"] == "confirmed"
    )
    assert desktop["selectable"] and not desktop["inactive"]
    assert (
        desktop["parameter_count"] == 70
        and desktop["mandatory_parameter_count"] == 24
        and desktop["optional_parameter_count"] == 46
    )
    assert [n["name"] for n in desktop["path"]] == [
        "Számítástechnika",
        "Asztali PC és monitorok",
        "Asztali számítógépek",
    ]
    identity = client.get(
        "/api/v1/reference/navigation/" + DESKTOP + "/selection"
    ).json()["canonical_reference_key"]
    assert identity == "fixed_category:" + DESKTOP
    params = client.get(
        f"/api/v1/reference/navigation/{DESKTOP}/parameters?limit=100"
    ).json()
    assert params["total"] == 70
    first = params["items"][0]
    assert (
        client.get(
            f"/api/v1/reference/parameters/{first['id']}/values?view=all"
        ).json()["items"][0]["value_text"]
        == "Intel"
    )
    parent = client.get("/api/v1/reference/navigation/" + desktop["parent_id"]).json()
    assert parent["mapping_status"] == "navigation"
    assert (
        client.get("/api/v1/reference/navigation?q=Alternatív asztali").json()["total"]
        == 0
    )
    stats = client.get("/api/v1/reference/navigation/coverage").json()[
        "reference_coverage"
    ]
    assert stats["fixed_category_count"] == 584
    assert stats["ambiguous_parameter_binding_count"] == 1
    review = client.get("/api/v1/reference/navigation?scope=unclassified").json()[
        "items"
    ]
    assert len(review) == 1 and review[0]["name"] == "Nagyítók"
    choices = client.get(
        "/api/v1/reference/navigation/choices/reference?q=Alternatív asztali"
    ).json()["items"]
    assert choices[0]["emag_category_id"] == 60001  # inactive donors are allowed
    body = (
        {"category_id": choices[0]["category_id"]}
        if owned
        else {"canonical_emag_id": 60001}
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/" + DESKTOP + "/assignment", json=body
        ).status_code
        == 200
    )
    changed = client.get("/api/v1/reference/navigation/" + DESKTOP).json()
    assert (
        changed["parent_id"] == desktop["parent_id"]
        and changed["path"] == desktop["path"]
    )
    assert changed["canonical_emag_id"] == 60001 and changed["parameter_count"] == 1
    assert (
        client.get("/api/v1/reference/navigation/" + DESKTOP + "/selection").json()[
            "canonical_reference_key"
        ]
        == identity
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/" + DESKTOP + "/assignment",
            json={"parent_id": "web-dept-43"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/" + desktop["parent_id"] + "/assignment",
            json=body,
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/" + DESKTOP + "/assignment",
            json={"reset": True},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/reference/navigation/" + DESKTOP).json()["parameter_count"]
        == 70
    )
    if owned:
        with Session(target) as db:
            assert frozen_data(db, version) == before  # zero value/link/node writes
            # An old placement decision may remain recorded, but cannot change the fixed hierarchy.
            db.add(
                CategoryOverride(
                    node_id=DESKTOP,
                    source_key="emag_marketplace",
                    source_category_id="6",
                    override_parent=True,
                    parent_id="web-dept-43",
                    source_snapshot=navigation().data["archive_sha256"],
                    actor_id=db.scalar(select(User.id)),
                )
            )
            db.commit()
        assert (
            client.get("/api/v1/reference/navigation/" + DESKTOP).json()["path"]
            == desktop["path"]
        )
