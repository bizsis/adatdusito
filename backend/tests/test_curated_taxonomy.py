"""CODEX 04B: declared paths, safe contextual matches and immutable versions."""

from copy import deepcopy
from pathlib import Path
import pytest
from sqlalchemy import select, func, event, insert
from sqlalchemy.orm import Session
from app.category_export import load_category_export
from app.curated_taxonomy import apply_taxonomy, specification
from app.web_navigation import navigation
from app.unified_categories import build_unified
from app.models import (
    CatalogNode,
    CatalogVersion,
    CatalogSourceMapping,
    CatalogLinkEntry,
    CatalogCategory,
    CatalogParameter,
    CatalogLink,
    CatalogValue,
    CategoryOverride,
    User,
)
from app.catalog_import import (
    SourceReader,
    import_catalog,
    rebuild_catalog,
    activate,
    verify_version,
)
from app.catalog_store import (
    index,
    active_version,
    data_version_id,
    values,
    parameters,
    dto,
)
from app import reference
from conftest import login
from test_unified_categories import (
    extra_reference_categories as extra_reference_categories,
    extra_reference_parameters as extra_reference_parameters,
    extra_reference_values as extra_reference_values,
)


def real_graph():
    tree = load_category_export(
        Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    )
    return tree, build_unified(apply_taxonomy(navigation()), tree)


def find(nav, *path):
    keys = [
        k
        for k in nav.nodes
        if [nav.nodes[p]["name"] for p in nav.path(k)] == list(path)
    ]
    assert len(keys) == 1, path
    return keys[0]


def test_declared_583_nodes_preserve_13_roots_order_and_all_parent_edges():
    base = navigation()
    before = deepcopy(base.data)
    curated = apply_taxonomy(base)
    tree, nav = real_graph()
    assert base.data == before
    assert nav.roots == base.roots
    declared = [n for n in curated.nodes.values() if n.get("taxonomy_version")]
    assert len(declared) == 583
    assert max(len(curated.path(n["id"])) for n in declared) == 4
    assert curated.data["curated_taxonomy_issues"] == []
    for n in declared:
        assert nav.nodes[n["id"]]["parent_id"] == n["parent_id"]
        assert nav.placement[n["id"]] == "verified_tree"
        assert n["id"] in base.nodes  # original navigation identities retained
    assert set(nav.bindings.values()) == set(tree.rows)
    assert nav.reference_coverage["represented_reference_count"] == 2669
    assert nav.reference_coverage["categories_with_parameters"] == 1807
    assert nav.reference_coverage["parameter_definition_total"] == 29398


def test_required_paths_context_and_aliases_do_not_bind_generic_names_in_wrong_branches():
    tree, nav = real_graph()
    expected = [
        (("TV és szórakozás", "Televíziók"), 79),
        (("Szupermarket", "Alkoholos italok", "Sör"), 3985),
        (("Számítástechnika", "Hálózatok és megfigyelő rendszerek", "Kapcsolók"), 670),
        (
            (
                "Számítástechnika",
                "Hálózatok és megfigyelő rendszerek",
                "Térfigyelő kamerák",
            ),
            407,
        ),
        (
            (
                "Fotó-Videó, Okos eszközök",
                "Okos eszközök",
                "Okos vércukor- és vérnyomásmérők",
            ),
            3404,
        ),
        (("Telefon, Tablet, Laptop", "Laptop tartozékok", "Memóriák"), 56),
        (("Számítástechnika", "PC alkatrészek", "Memóriák"), 3),
        (
            (
                "Divat, ékszerek és kiegészítők",
                "NŐI DIVAT",
                "Női kiegészítők",
                "Táskák",
            ),
            2698,
        ),
        (
            (
                "Divat, ékszerek és kiegészítők",
                "FÉRFI DIVAT",
                "Férfi kiegészítők",
                "Táskák",
            ),
            2751,
        ),
        (("Divat, ékszerek és kiegészítők", "NŐI DIVAT", "Női ruházat", "Pólók"), 2678),
        (
            ("Divat, ékszerek és kiegészítők", "FÉRFI DIVAT", "Férfi ruházat", "Pólók"),
            2719,
        ),
        (("Divat, ékszerek és kiegészítők", "GYERMEK DIVAT", "Pólók"), 3216),
    ]
    for path, external in expected:
        key = find(nav, *path)
        assert tree.rows[nav.bindings[key]]["emag_category_id"] == external
    tv = find(nav, "TV és szórakozás", "Televíziók")
    assert tree.counts[nav.bindings[tv]]["total"] == 46
    magnifier = find(
        nav, "Fotó-Videó, Okos eszközök", "Távcsövek és optikai eszközök", "Nagyítók"
    )
    assert magnifier not in nav.bindings  # broader 318 is not exact identity
    wash = find(
        nav,
        "Háztartási gépek és klíma",
        "Mosógépek és szárítógépek",
        "Elöltöltős mosógépek",
    )
    assert not nav.nodes[wash]["structural_only"]
    assert nav.nodes[wash]["kind"] == "category"
    assert all(
        n["name"] not in specification()["excluded_tv_filters"]
        for k, n in nav.nodes.items()
        if k in nav.visible
    )
    assert not any(
        n["name"] == "LEGO Shop" for k, n in nav.nodes.items() if k in nav.visible
    )


def test_rebuild_reuses_owned_memberships_stable_ids_and_preserves_active_tree(
    environment,
    monkeypatch,
):
    client, target, source, _ = environment
    from app import curated_taxonomy

    with monkeypatch.context() as old_plan:
        old_plan.setattr(curated_taxonomy, "apply_taxonomy", lambda base: base)
        first = import_catalog(target, SourceReader(source), pause_ms=0)
    activate(target, first)
    models = (
        CatalogCategory,
        CatalogParameter,
        CatalogLink,
        CatalogValue,
        CatalogSourceMapping,
        CatalogLinkEntry,
    )
    with Session(target) as db:
        before = {
            m: db.scalar(select(func.count()).select_from(m))
            for m in models
            if m is not CatalogCategory
        }
        original_category_ids = {
            r.key: r.id for r in db.scalars(select(CatalogCategory))
        }
        original = {
            r.key: (r.category_id, deepcopy(r.data))
            for r in db.scalars(
                select(CatalogNode).where(CatalogNode.version_id == first)
            )
        }
        tv_id = original["web-item-43-3730"][0]

    def forbid(*args):
        raise AssertionError("Tree rebuild accessed pinfo_db")

    event.listen(source, "before_cursor_execute", forbid)
    second = rebuild_catalog(target, first)
    third = rebuild_catalog(target, second)
    with Session(target) as db:
        assert active_version(db).id == first
        assert before == {
            m: db.scalar(select(func.count()).select_from(m)) for m in before
        }
        assert original == {
            r.key: (r.category_id, r.data)
            for r in db.scalars(
                select(CatalogNode).where(CatalogNode.version_id == first)
            )
        }
        current_category_ids = {
            r.key: r.id for r in db.scalars(select(CatalogCategory))
        }
        assert all(
            current_category_ids[k] == own_id
            for k, own_id in original_category_ids.items()
        )
        rebuilt_rows = list(
            db.scalars(select(CatalogNode).where(CatalogNode.version_id == second))
        )
        assert any(
            r.key in original and r.data["parent_id"] != original[r.key][1]["parent_id"]
            for r in rebuilt_rows
        )
        assert {r.key: r.category_id for r in rebuilt_rows} == {
            r.key: r.category_id
            for r in db.scalars(
                select(CatalogNode).where(CatalogNode.version_id == third)
            )
        }
        for version_id in (second, third):
            run = db.get(CatalogVersion, version_id)
            assert run.status == "ready" and data_version_id(db, run) == first
            nav = index(db, run)
            assert nav.owned_nodes["web-item-43-3730"].category_id == tv_id
            details = dto(db, run, nav, "web-item-43-3730")
            assert details["parameter_count"] == 46
            assert details["mandatory_parameter_count"] == 15
            assert details["optional_parameter_count"] == 31
            links = parameters(db, run, category_id=tv_id, limit=100, view="all")
            assert links["total"] == 46
            assert (
                values(db, run, links["items"][0]["id"], q="123", view="all")["items"][
                    0
                ]["value_text"]
                == "TV érték 123"
            )
            assert not db.scalar(
                select(CatalogLinkEntry).where(
                    CatalogLinkEntry.version_id == version_id
                )
            )
    activate(target, third)
    login(client)
    assert client.get("/api/v1/reference/navigation").json()["total"] == 13
    assert (
        client.get("/api/v1/reference/navigation?q=Menüben nem szereplő").json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get("/api/v1/reference/navigation/web-item-43-3730/parameters").json()[
            "total"
        ]
        == 46
    )
    activate(target, first)
    event.remove(source, "before_cursor_execute", forbid)
    assert (
        verify_version(target, SourceReader(source), third)["processed"]["parameters"]
        == 50
    )


def test_rebuild_preserves_admin_bindings_and_native_parent_choices_but_blocks_declared_conflicts(
    environment,
):
    _, target, source, _ = environment
    first = import_catalog(target, SourceReader(source), pause_ms=0)
    activate(target, first)
    with Session(target) as db:
        db.add(
            CategoryOverride(
                actor_id=db.scalar(select(User.id)),
                node_id="web-item-43-3730",
                source_key="emag_marketplace",
                source_category_id="79",
                source_snapshot=navigation().data["archive_sha256"],
            )
        )
        db.add(
            CategoryOverride(
                actor_id=db.scalar(select(User.id)),
                node_id="ref-emag-54321",
                source_key="emag_marketplace",
                override_parent=True,
                parent_id="web-dept-43",
            )
        )
        db.commit()
    second = rebuild_catalog(target, first)
    with Session(target) as db:
        nav = index(db, db.get(CatalogVersion, second))
        assert nav.nodes["web-item-43-3730"]["mapping_method"] == "administrator"
        assert "ref-emag-54321" not in nav.nodes
        assert (
            db.get(CatalogNode, (second, "ref-emag-54321")).data["parent_id"]
            == "web-dept-43"
        )
        override = db.get(CategoryOverride, "web-item-43-3730")
        override.parent_id, override.override_parent = "web-dept-44", True
        db.commit()
    with pytest.raises(ValueError, match="conflicts with an operator choice"):
        rebuild_catalog(target, second)
    with Session(target) as db:
        assert active_version(db).id == first
        assert db.get(CategoryOverride, "web-item-43-3730").parent_id == "web-dept-44"
        assert db.scalar(select(func.count()).select_from(CatalogVersion)) == 2


def test_tv_filters_link_only_real_contextual_parameter_values(environment):
    _, target, source, _ = environment
    # Fixture extension happens before enabling the source read-only guard again.
    from app.db import enforce_reference_readonly

    event.remove(source, "before_cursor_execute", enforce_reference_readonly)
    with source.begin() as conn:
        conn.execute(
            insert(reference.parameters),
            dict(
                id=8000,
                category_id=200,
                emag_parameter_id=9001,
                name="Kijelzőtechnológia",
                type_id=1,
            ),
        )
        conn.execute(
            insert(reference.values),
            [
                dict(id=80000, parameter_id=8000, value_text="OLED"),
                dict(id=80001, parameter_id=8000, value_text="LED"),
            ],
        )
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    first = import_catalog(target, SourceReader(source), pause_ms=0)
    second = rebuild_catalog(target, first)
    with Session(target) as db:
        node = db.get(CatalogNode, (second, "web-item-43-3730"))
        facets = {r["name"]: r for r in node.data["related_parameter_filters"]}
        assert facets["OLED TV"]["status"] == facets["LED TV"]["status"] == "linked"
        assert (
            facets["OLED TV"]["match"]["value_id"]
            != facets["LED TV"]["match"]["value_id"]
        )
        assert facets["QLED TV"]["status"] == facets["8K"]["status"] == "unresolved"
        assert facets["OLED TV"]["match"]["parameter_name"] == "Kijelzőtechnológia"
        assert facets["OLED TV"]["match"]["parameter_id"] >= 1_000_000_000


def test_changed_hierarchy_plan_stages_new_version_instead_of_reusing_old_ready(
    environment, monkeypatch
):
    from app import curated_taxonomy

    _, target, source, _ = environment
    reader = SourceReader(source)
    first = import_catalog(target, reader, pause_ms=0)
    activate(target, first)
    monkeypatch.setattr(curated_taxonomy, "plan_signature", lambda base: "changed-plan")
    second = import_catalog(target, reader, pause_ms=0)
    assert second != first
    with Session(target) as db:
        assert active_version(db).id == first
        assert (
            db.get(CatalogVersion, second).counters["plan_signature"] == "changed-plan"
        )
