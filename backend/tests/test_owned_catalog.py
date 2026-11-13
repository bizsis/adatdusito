from contextlib import contextmanager
import pytest
from sqlalchemy import create_engine, select, func, insert, update, event
from sqlalchemy.orm import Session
from app import reference, web_navigation, reference_sources, catalog_import
from app.db import enforce_reference_readonly
from app.models import (
    Base,
    CatalogVersion,
    CatalogCategory,
    CatalogParameter,
    CatalogLink,
    CatalogValue,
    CatalogSourceMapping,
)
from app.catalog_import import SourceReader, import_catalog, verify_version, activate
from conftest import login
from test_unified_categories import (
    extra_reference_categories as extra_reference_categories,
    extra_reference_parameters as extra_reference_parameters,
    extra_reference_values as extra_reference_values,
)


def count(target, model):
    with Session(target) as db:
        return db.scalar(select(func.count()).select_from(model))


def test_owned_catalog_serves_all_existing_browsing_without_source_access(
    environment, monkeypatch
):
    client, target, source, _ = environment
    reader = SourceReader(source)
    version = import_catalog(target, reader, batch_size=17, pause_ms=0)
    with Session(target) as db:
        run = db.get(CatalogVersion, version)
        assert run.status == "ready" and run.verification["processed"] == {
            "categories": 10,
            "parameters": 50,
            "values": 252,
        }
    assert (
        verify_version(target, reader, version, expected={"television_parameters": 46})[
            "televisions"
        ]["parameters"]
        == 46
    )
    activate(target, version)

    @contextmanager
    def forbidden():
        raise AssertionError("An owned-catalog API read contacted the source")
        yield

    for module in (reference, web_navigation, reference_sources):
        monkeypatch.setattr(module, "reference_database", forbidden)
    login(client, "processor@example.hu")
    roots = client.get("/api/v1/reference/navigation").json()
    assert roots["total"] == 13
    tv = client.get("/api/v1/reference/navigation/web-item-43-3730").json()
    assert tv["unified_category_id"] >= 1_000_000_000 and tv["parameter_count"] == 46
    assert (
        tv["mandatory_parameter_count"] == 15 and tv["optional_parameter_count"] == 31
    )
    response = client.get(
        "/api/v1/reference/navigation/web-item-43-3730/parameters?limit=100"
    ).json()
    assert response["total"] == 46 and len(response["items"]) == 46
    first = response["items"][0]
    assert first["id"] >= 1_000_000_000 and first["parameter_id"] >= 1_000_000_000
    vals = client.get(
        f"/api/v1/reference/parameters/{first['id']}/values?view=all"
    ).json()
    assert len(vals["items"]) == 50 and vals["has_more"]
    next_page = client.get(
        f"/api/v1/reference/parameters/{first['id']}/values?view=all&after={vals['next_cursor']}"
    ).json()
    assert not (
        {r["id"] for r in vals["items"]} & {r["id"] for r in next_page["items"]}
    )
    assert (
        client.get(
            f"/api/v1/reference/parameters/{first['id']}/values?view=all&q=123"
        ).json()["items"][0]["value_text"]
        == "TV érték 123"
    )
    assert (
        client.get("/api/v1/reference/categories/200").json()["unified_category_id"]
        == tv["unified_category_id"]
    )
    assert (
        client.get(
            "/api/v1/reference/parameters?category_id=200&view=all&mandatory=true"
        ).json()["total"]
        == 15
    )
    assert client.get("/api/v1/reference/parameters/1000/values?view=all&q=123").json()[
        "items"
    ]
    assert (
        client.get("/api/v1/reference/navigation?q=Menüben nem szereplő").json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get("/api/v1/reference/navigation/coverage").json()[
            "source_record_counts"
        ]["values"]
        == 252
    )
    assert client.get("/api/v1/reference/coverage").status_code == 200
    assert (
        client.get("/api/v1/reference/navigation/web-item-43-3730/selection").json()[
            "category_id"
        ]
        == tv["unified_category_id"]
    )
    login(client)
    assert (
        client.get(
            "/api/v1/reference/navigation/choices/reference?q=Televíziók"
        ).json()["items"][0]["category_id"]
        == tv["unified_category_id"]
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/ref-emag-54321/assignment",
            json={"parent_id": "web-dept-43"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/web-item-43-3730/assignment",
            json={"parent_id": "web-dept-43"},
        ).status_code
        == 409
    )


def synthetic_source(value_count=25001):
    source = create_engine("sqlite://")
    reference.metadata.create_all(source)
    with source.begin() as conn:
        conn.execute(
            insert(reference.categories),
            [
                {
                    "id": 11,
                    "emag_category_id": 79,
                    "name": "Televíziók",
                    "parent_id": None,
                    "is_allowed": True,
                },
                {
                    "id": 12,
                    "emag_category_id": 8000,
                    "name": "Másik TV",
                    "parent_id": 79,
                    "is_allowed": True,
                },
            ],
        )
        conn.execute(
            insert(reference.parameters),
            [
                dict(
                    id=i,
                    category_id=11 if i == 31 else 12,
                    emag_parameter_id=42,
                    name="Méret",
                    type_id=2,
                    display_order=i,
                    is_mandatory=i == 31,
                    is_filter=True,
                    allow_new_value=False,
                )
                for i in (31, 32)
            ],
        )
        for start in range(1, value_count + 1, 500):
            conn.execute(
                insert(reference.values),
                [
                    dict(
                        id=i,
                        parameter_id=31 if i % 2 else 32,
                        value_text=f"Érték {i % 101}",
                        value_order=i,
                    )
                    for i in range(start, min(start + 500, value_count + 1))
                ],
            )
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    return source


def test_bounded_batches_idempotent_resume_deduplicated_definitions_and_values():
    source = synthetic_source()
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    reader = SourceReader(source)
    maximum = 0
    original = reader.batch

    def tracked(phase, cursor, limit, ceiling=None):
        nonlocal maximum
        result = original(phase, cursor, limit, ceiling)
        if phase == "values":
            maximum = max(maximum, len(result))
        return result

    reader.batch = tracked
    version = import_catalog(target, reader, batch_size=997, pause_ms=0, max_batches=3)
    with Session(target) as db:
        assert db.get(CatalogVersion, version).status == "building"
    with pytest.raises(ValueError, match="verified"):
        activate(target, version)
    assert (
        import_catalog(target, reader, version, batch_size=997, pause_ms=0) == version
    )
    assert maximum <= 997
    assert (
        count(target, CatalogParameter) == 1
    )  # Same source definition across categories.
    assert (
        count(target, CatalogLink) == 2
    )  # Original contextual requirements preserved.
    assert (
        count(target, CatalogValue) == 101
    )  # 25,001 source rows, shared text stored once.
    assert count(target, CatalogSourceMapping) == 25005
    before = {
        m: count(target, m)
        for m in (
            CatalogCategory,
            CatalogParameter,
            CatalogLink,
            CatalogValue,
            CatalogSourceMapping,
        )
    }
    import_catalog(target, reader, version, batch_size=997, pause_ms=0)
    assert before == {m: count(target, m) for m in before}
    second = import_catalog(
        target, reader, new_version=True, batch_size=997, pause_ms=0
    )
    assert second != version
    assert all(
        count(target, m) == before[m]
        for m in (CatalogCategory, CatalogParameter, CatalogLink, CatalogValue)
    )
    activate(target, version)
    assert activate(target, second)["previous"] == str(version)
    assert activate(target, version)["current"] == str(
        version
    )  # Atomic historical rollback.
    assert activate(target, legacy=True)["current"] == "legacy"


def test_interrupted_batch_rolls_back_atomically_and_keeps_checkpoint(monkeypatch):
    source = synthetic_source(151)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    reader = SourceReader(source)
    original = catalog_import.value_batch
    calls = 0

    def interrupted(db, run, rows, context):
        nonlocal calls
        calls += 1
        original(db, run, rows, context)
        if calls == 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr(catalog_import, "value_batch", interrupted)
    with pytest.raises(KeyboardInterrupt):
        import_catalog(target, reader, batch_size=17, pause_ms=0)
    with Session(target) as db:
        run = db.scalar(select(CatalogVersion))
        assert run.cursor == 17 and run.counters["values"] == 17
        assert run.error.startswith("KeyboardInterrupt")
        version = run.id
    monkeypatch.setattr(catalog_import, "value_batch", original)
    import_catalog(target, reader, version, batch_size=17, pause_ms=0)
    assert verify_version(target, reader, version)["processed"]["values"] == 151
    with pytest.raises(ValueError, match="Unexpected production"):
        verify_version(target, reader, version, expected={"values": 2847054})
    with target.begin() as conn:
        conn.execute(update(CatalogValue).values(value_text="corrupt"))
    with pytest.raises(ValueError, match="Stored value"):
        verify_version(target, reader, version)


def test_real_category_export_all_2669_categories_imported_without_claiming_missing_values():
    from pathlib import Path
    from app.category_export import load_category_export

    tree = load_category_export(
        Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    )
    source = create_engine("sqlite://")
    reference.metadata.create_all(source)
    rows = list(tree.rows.values())
    with source.begin() as conn:
        for start in range(0, len(rows), 500):
            conn.execute(insert(reference.categories), rows[start : start + 500])
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    version = import_catalog(target, SourceReader(source), pause_ms=0)
    report = verify_version(
        target,
        SourceReader(source),
        version,
        expected={"categories": 2669, "parameters": 0, "values": 0},
    )
    assert report["processed"] == {"categories": 2669, "parameters": 0, "values": 0}
    assert count(target, CatalogCategory) >= 2669
    with Session(target) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(CatalogSourceMapping)
                .where(CatalogSourceMapping.kind == "category")
            )
            == 2669
        )


def test_existing_source_version_is_not_silently_overwritten_and_staging_does_not_activate():
    source = synthetic_source(41)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    reader = SourceReader(source)
    first = import_catalog(target, reader, pause_ms=0)
    activate(target, first)
    event.remove(source, "before_cursor_execute", enforce_reference_readonly)
    with source.begin() as conn:
        conn.execute(
            update(reference.values)
            .where(reference.values.c.id == 1)
            .values(value_text="Frissített érték")
        )
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    with pytest.raises(ValueError, match="Missing/changed source"):
        import_catalog(target, reader, first, pause_ms=0)
    second = import_catalog(target, reader, new_version=True, pause_ms=0)
    from app.catalog_store import active_version

    with Session(target) as db:
        assert active_version(db).id == first
    activate(target, second)
    with Session(target) as db:
        assert active_version(db).id == second


def test_owned_readiness_uses_application_catalog_instead_of_source(
    environment, monkeypatch
):
    from app import db as database_module

    _, target, source, _ = environment
    version = import_catalog(target, SourceReader(source), pause_ms=0)
    activate(target, version)

    def own_only(reference=False):
        assert reference is False, "Readiness contacted the source"
        return target

    monkeypatch.setattr(database_module, "engine", own_only)
    database_module.check_database(True)


def test_raw_source_metadata_preserved_but_not_loaded_by_normal_category_reads():
    from app.catalog_store import index

    source = synthetic_source(11)
    raw = {"units": ["cm", "inch"], "nested": {"allowed": ["a", "b"]}}
    event.remove(source, "before_cursor_execute", enforce_reference_readonly)
    with source.begin() as conn:
        conn.execute(
            update(reference.categories).values(raw_json={"original": "category data"})
        )
        conn.execute(update(reference.parameters).values(raw_json=raw))
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    version = import_catalog(target, SourceReader(source), pause_ms=0)
    with Session(target) as db:
        mapping = db.get(
            CatalogSourceMapping, (version, "parameter", "emag_marketplace", 31)
        )
        assert mapping.source_json == raw and "raw_json" not in mapping.data
    statements = []
    event.listen(
        target,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(
            statement
        ),
    )
    with Session(target) as db:
        nav = index(db, db.get(CatalogVersion, version))
        assert len(nav.roots) == 13
    assert not any("catalog_source_mappings.source_json" in sql for sql in statements)


def test_broken_active_catalog_fails_closed_instead_of_falling_back(
    environment, monkeypatch
):
    from app.models import Setting
    from app.catalog_constants import ACTIVE_KEY

    client, target, _, _ = environment
    with Session(target) as db:
        db.add(Setting(key=ACTIVE_KEY, value="999999"))
        db.commit()

    @contextmanager
    def forbidden():
        raise AssertionError("Silent source fallback")
        yield

    monkeypatch.setattr(web_navigation, "reference_database", forbidden)
    login(client)
    assert client.get("/api/v1/reference/navigation").status_code == 503


def test_shared_parameter_keeps_each_category_allowed_values_separate():
    from app.catalog_store import values as own_values

    source = synthetic_source(9)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)
    version = import_catalog(target, SourceReader(source), pause_ms=0)
    with Session(target) as db:
        run = db.get(CatalogVersion, version)
        left = own_values(db, run, 31, view="all")["items"]
        right = own_values(db, run, 32, view="all")["items"]
        assert {r["value_text"] for r in left} == {
            f"Érték {i}" for i in (1, 3, 5, 7, 9)
        }
        assert {r["value_text"] for r in right} == {f"Érték {i}" for i in (2, 4, 6, 8)}
        assert run.verification["unified_parameter_count"] == 1
        assert run.verification["unified_value_count"] == 9


def test_metadata_payload_budget_is_checked_before_reading_json_payloads():
    source = synthetic_source(1)
    event.remove(source, "before_cursor_execute", enforce_reference_readonly)
    with source.begin() as conn:
        conn.execute(update(reference.parameters).values(raw_json={"k": "x" * 60}))
    event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    reader = SourceReader(source)
    reader.metadata_budget = 100
    reader.max_metadata_record = 200
    assert len(reader.batch("parameters", 0, 100)) == 1
    assert len(reader.batch("parameters", 31, 100)) == 1
    reader.max_metadata_record = 50
    with pytest.raises(ValueError, match="bounded import size"):
        reader.batch("parameters", 0, 100)
