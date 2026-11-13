"""Resumable offline import into a staged owned catalog. Never writes the source."""

from contextlib import contextmanager
import argparse
import hashlib
import json
import logging
import threading
import time
from sqlalchemy import select, func, insert, text
from sqlalchemy.orm import Session, undefer
from app.db import engine
from app.models import (
    CatalogVersion,
    CatalogCategory,
    CatalogNode,
    CatalogParameter,
    CatalogLink,
    CatalogLinkEntry,
    CatalogValue,
    CatalogSourceMapping,
    CategoryOverride,
    Setting,
    Audit,
    now,
)
from app.reference import categories, parameters, values, load_tree
from app.unified_categories import build_unified, normalized

from app.catalog_constants import SOURCE, ACTIVE_KEY, COMMON_ID_START

TABLES = {"categories": categories, "parameters": parameters, "values": values}
KINDS = {"categories": "category", "parameters": "parameter", "values": "value"}
_local_lock = threading.Lock()
log = logging.getLogger("catalog_import")


def digest(row):
    return hashlib.sha256(
        json.dumps(
            row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


class SourceReader:
    metadata_budget = 16 * 1024 * 1024
    max_metadata_record = 64 * 1024 * 1024

    def __init__(self, source_engine, connection=None):
        self.engine, self.connection = source_engine, connection

    @contextmanager
    def connect(self):
        if self.connection is not None:
            yield self.connection
        else:
            with self.engine.connect() as conn:
                if conn.dialect.name == "mysql":
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                yield conn

    @contextmanager
    def snapshot(self):
        with self.engine.connect() as conn:
            if conn.dialect.name == "mysql":
                conn = conn.execution_options(isolation_level="REPEATABLE READ")
                conn.execute(text("SET TRANSACTION READ ONLY"))
            yield SourceReader(self.engine, conn)

    def batch(self, phase, cursor, limit, ceiling=None):
        table = TABLES[phase]
        if phase != "values":
            limit = min(
                limit, 100
            )  # Source JSON may be larger than normalized metadata.
        stmt = select(table).where(table.c.id > cursor)
        if ceiling is not None:
            stmt = stmt.where(table.c.id <= ceiling)
        with self.connect() as conn:
            if phase != "values":
                sizes = conn.execute(
                    stmt.with_only_columns(table.c.id, func.length(table.c.raw_json))
                    .order_by(table.c.id)
                    .limit(limit)
                ).all()
                selected, used = [], 0
                for source_id, size in sizes:
                    size = size or 0
                    if size > self.max_metadata_record:
                        raise ValueError(
                            f"Source JSON record exceeds bounded import size: {phase} {source_id}"
                        )
                    if selected and used + size > self.metadata_budget:
                        break
                    selected.append(source_id)
                    used += size
                if not selected:
                    return []
                stmt = stmt.where(table.c.id.in_(selected))
            return [
                dict(row)
                for row in conn.execute(
                    stmt.order_by(table.c.id).limit(limit)
                ).mappings()
            ]

    def profile(self):
        result = {}
        with self.connect() as conn:
            for phase, table in TABLES.items():
                count, high = conn.execute(
                    select(func.count(), func.max(table.c.id))
                ).one()
                result[phase] = {"count": count, "max_id": high or 0}
        h = hashlib.sha256()
        for phase in ("categories", "parameters"):
            cursor = 0
            while rows := self.batch(phase, cursor, 1000):
                for row in rows:
                    h.update(digest(row).encode())
                cursor = rows[-1]["id"]
        result["metadata_sha256"] = h.hexdigest()
        return result


@contextmanager
def import_lock(target):
    if target.dialect.name == "mysql":
        with target.connect() as conn:
            if (
                conn.scalar(text("SELECT GET_LOCK('adatdusito.catalog_import', 0)"))
                != 1
            ):
                raise ValueError("Another catalog import/activation is running")
            try:
                yield
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('adatdusito.catalog_import')"))
    else:
        if not _local_lock.acquire(blocking=False):
            raise ValueError("Another catalog import is running")
        try:
            yield
        finally:
            _local_lock.release()


def entities(db, model, records):
    """Bulk reuse stable common IDs; only the serialized importer creates them."""
    requested = {r["key"]: r for r in records}
    found = (
        {r.key: r for r in db.scalars(select(model).where(model.key.in_(requested)))}
        if requested
        else {}
    )
    next_id = max(db.scalar(select(func.max(model.id))) or 0, COMMON_ID_START - 1)
    missing = []
    for key, record in requested.items():
        if key in found:
            existing = found[key]
            if model is CatalogValue and (
                existing.parameter_id != record["parameter_id"]
                or existing.value_text != record["value_text"]
            ):
                raise ValueError("Value identity collision")
            continue
        next_id += 1
        if next_id >= 2**53:
            raise ValueError("Common ID exceeds exact JSON integer range")
        missing.append({"id": next_id, **record})
    if missing:
        db.execute(insert(model), missing)
        found.update(
            {
                r.key: r
                for r in db.scalars(
                    select(model).where(model.key.in_([r["key"] for r in missing]))
                )
            }
        )
    return {key: row.id for key, row in found.items()}


def mappings(db, version_id, kind):
    return {
        r.source_id: r
        for r in db.scalars(
            select(CatalogSourceMapping).where(
                CatalogSourceMapping.version_id == version_id,
                CatalogSourceMapping.kind == kind,
                CatalogSourceMapping.source_key == SOURCE,
            )
        )
    }


def category_phase(db, run, reader):
    from app.web_navigation import navigation, observations

    with reader.connect() as conn:
        tree = load_tree(conn)
    from app.curated_taxonomy import apply_taxonomy

    original = navigation()
    base = apply_taxonomy(original)
    nav = build_unified(
        base,
        tree,
        observations(db, original),
        list(db.scalars(select(CategoryOverride))),
    )
    wanted = [
        {"key": f"{SOURCE}:category:{r['emag_category_id']}", "name": r["name"]}
        for r in tree.rows.values()
    ]
    wanted += [
        {"key": "navigation:" + k, "name": nav.nodes[k]["name"]}
        for k in nav.visible
        if k not in nav.bindings
    ]
    # Bounded category metadata, not the millions of allowed values.
    ids = {}
    for start in range(0, len(wanted), 500):
        ids.update(entities(db, CatalogCategory, wanted[start : start + 500]))
    category_ids = {
        k: ids[f"{SOURCE}:category:{r['emag_category_id']}"]
        for k, r in tree.rows.items()
    }
    source_count, cursor = 0, 0
    while rows := reader.batch("categories", cursor, 100):
        source_rows = [
            dict(
                version_id=run.id,
                kind="category",
                source_key=SOURCE,
                source_id=row["id"],
                target_id=category_ids[row["id"]],
                context_id=None,
                external_id=str(row["emag_category_id"]),
                ordinal=None,
                payload_sha256=digest(row),
                data={k: v for k, v in row.items() if k != "raw_json"},
                source_json=row.get("raw_json"),
            )
            for row in rows
        ]
        db.execute(insert(CatalogSourceMapping), source_rows)
        source_count += len(rows)
        cursor = rows[-1]["id"]
    run.counters = {"categories": source_count, "parameters": 0, "values": 0}
    store_tree(db, run, tree, base, nav, category_ids)
    run.phase, run.cursor = "parameters", 0


def store_tree(db, run, tree, base, nav, category_ids):
    from app.curated_taxonomy import plan_signature

    wanted = [
        {"key": "navigation:" + k, "name": nav.nodes[k]["name"]}
        for k in nav.visible
        if k not in nav.bindings
    ]
    ids = {}
    for start in range(0, len(wanted), 500):
        ids.update(entities(db, CatalogCategory, wanted[start : start + 500]))
    legacy_ids = {
        r.key: r.id
        for r in db.scalars(
            select(CatalogCategory).where(
                CatalogCategory.key.in_(["navigation:" + k for k in nav.visible])
            )
        )
    }
    nodes = []
    for key, node in nav.nodes.items():
        internal = nav.bindings.get(key)
        meta = {
            **node,
            "placement_status": nav.placement[key],
            "mapping_method": nav.methods.get(key),
        }
        meta.update(
            {
                "canonical_emag_id": tree.rows[internal]["emag_category_id"]
                if internal is not None
                else None,
                "marketplace_category_id": internal,
                "archived": internal in tree.deleted if internal is not None else False,
                "inactive": tree.rows[internal]["is_allowed"] != 1
                if internal is not None
                else False,
                "selectable": bool(
                    internal is not None
                    and internal in tree.selectable
                    and node["kind"] == "category"
                    and not node.get("structural_only")
                ),
            }
        )
        meta["mapping_candidate_ids"] = [
            category_ids[c] for c in nav.candidates.get(key, [])
        ]
        category_id = (
            category_ids[internal]
            if internal is not None
            else ids.get("navigation:" + key)
        )
        meta["_imported_category_id"] = category_id
        meta["_imported_parent_id"] = meta["parent_id"]
        meta["_imported_hierarchy_status"] = meta["hierarchy_status"]
        meta["category_alias_ids"] = (
            [legacy_ids["navigation:" + key]]
            if "navigation:" + key in legacy_ids
            and legacy_ids["navigation:" + key] != category_id
            else []
        )
        nodes.append(
            dict(version_id=run.id, key=key, category_id=category_id, data=meta)
        )
    for start in range(0, len(nodes), 500):
        db.execute(insert(CatalogNode), nodes[start : start + 500])
    run.counters = {
        **run.counters,
        "coverage": nav.reference_coverage,
        "root_ids": nav.roots,
        "navigation_snapshot": base.data["archive_sha256"],
        "plan_signature": plan_signature(base),
        "taxonomy_version": base.data.get("curated_taxonomy_version"),
        "taxonomy_edges": {
            k: n["parent_id"]
            for k, n in base.nodes.items()
            if n.get("taxonomy_version")
        },
        "taxonomy_identity_issues": base.data.get("curated_taxonomy_issues", []),
    }


def validate_tree(db, run):
    rows = {
        r.key: r
        for r in db.scalars(select(CatalogNode).where(CatalogNode.version_id == run.id))
    }
    for key, parent in run.counters.get("taxonomy_edges", {}).items():
        if key not in rows or rows[key].data["parent_id"] != parent:
            raise ValueError(
                "Declared hierarchy conflicts with an operator choice: " + key
            )
    return rows


def parameter_batch(db, run, rows):
    cat = mappings(db, run.id, "category")
    definitions = [
        {
            "key": digest(
                {
                    "source": SOURCE,
                    "external_id": r["emag_parameter_id"],
                    "name": normalized(r["name"]),
                    "type": r["type_id"],
                }
            ),
            "name": r["name"],
            "type_id": r["type_id"],
        }
        for r in rows
    ]
    defs = entities(db, CatalogParameter, definitions)
    links = entities(
        db,
        CatalogLink,
        [{"key": f"{SOURCE}:category_parameter:{r['id']}"} for r in rows],
    )
    entries, sources = [], []
    for row, definition in zip(rows, definitions):
        if row["category_id"] not in cat:
            raise ValueError("Missing source category mapping")
        link = links[f"{SOURCE}:category_parameter:{row['id']}"]
        category_id = cat[row["category_id"]].target_id
        entries.append(
            dict(
                version_id=run.id,
                link_id=link,
                category_id=category_id,
                parameter_id=defs[definition["key"]],
                **{
                    k: row[k]
                    for k in (
                        "name",
                        "emag_parameter_id",
                        "display_order",
                        "is_mandatory",
                        "is_filter",
                        "allow_new_value",
                    )
                },
            )
        )
        sources.append(
            dict(
                version_id=run.id,
                kind="parameter",
                source_key=SOURCE,
                source_id=row["id"],
                target_id=link,
                context_id=category_id,
                external_id=str(row["emag_parameter_id"]),
                ordinal=row["display_order"],
                payload_sha256=digest(row),
                data={k: v for k, v in row.items() if k != "raw_json"},
                source_json=row.get("raw_json"),
            )
        )
    db.execute(insert(CatalogLinkEntry), entries)
    db.execute(insert(CatalogSourceMapping), sources)


def parameter_context(db, version_id):
    entries = {
        r.link_id: r.parameter_id
        for r in db.scalars(
            select(CatalogLinkEntry).where(CatalogLinkEntry.version_id == version_id)
        )
    }
    return {
        source_id: (r.target_id, entries[r.target_id])
        for source_id, r in mappings(db, version_id, "parameter").items()
    }


def value_batch(db, run, rows, context):
    wanted = []
    for row in rows:
        if row["parameter_id"] not in context:
            raise ValueError("Missing source category-parameter mapping")
        _, parameter_id = context[row["parameter_id"]]
        wanted.append(
            dict(
                key=digest({"parameter": parameter_id, "text": row["value_text"]}),
                parameter_id=parameter_id,
                value_text=row["value_text"],
            )
        )
    ids = entities(db, CatalogValue, wanted)
    db.execute(
        insert(CatalogSourceMapping),
        [
            dict(
                version_id=run.id,
                kind="value",
                source_key=SOURCE,
                source_id=r["id"],
                target_id=ids[w["key"]],
                context_id=context[r["parameter_id"]][0],
                external_id=None,
                ordinal=r["value_order"],
                payload_sha256=digest(r),
                data={"parameter_id": r["parameter_id"]},
            )
            for r, w in zip(rows, wanted)
        ],
    )


def count_unique_values(db, data_id):
    """Use the covering value index; allow this aggregate to exceed API timeouts."""
    statement = (
        select(func.count(func.distinct(CatalogSourceMapping.target_id)))
        .where(
            CatalogSourceMapping.version_id == data_id,
            CatalogSourceMapping.kind == "value",
        )
        .with_hint(
            CatalogSourceMapping,
            "FORCE INDEX (ix_catalog_mapping_targets)",
            dialect_name="mysql",
        )
    )
    target = db.get_bind()
    if target.dialect.name != "mysql":
        return db.scalar(statement)
    # A measured production count takes >11s even with the right index. Keep
    # the normal 5s timeout for every other check/API read, using a disposable
    # application-DB connection solely for this read-only aggregate.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    aggregate_engine = create_engine(
        target.url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 3, "read_timeout": 60, "write_timeout": 3},
    )
    try:
        with aggregate_engine.connect() as connection:
            return connection.scalar(statement)
    finally:
        aggregate_engine.dispose()


def verify_version(target, reader, version_id, batch_size=2000, expected=None):
    if not 1 <= batch_size <= 5000:
        raise ValueError("Invalid verification batch size")
    with Session(target) as db, reader.snapshot() as snapshot:
        run = db.get(CatalogVersion, version_id)
        if not run:
            raise ValueError("Unknown catalog version")
        if snapshot.profile() != run.source_state:
            raise ValueError("Source metadata/counts changed; start a new version")
        from app.catalog_store import data_version_id

        data_id = data_version_id(db, run)
        context = parameter_context(db, data_id)
        cats = dict(
            db.execute(
                select(
                    CatalogSourceMapping.source_id, CatalogSourceMapping.target_id
                ).where(
                    CatalogSourceMapping.version_id == data_id,
                    CatalogSourceMapping.kind == "category",
                    CatalogSourceMapping.source_key == SOURCE,
                )
            ).all()
        )
        entries = {
            r.link_id: r
            for r in db.scalars(
                select(CatalogLinkEntry).where(CatalogLinkEntry.version_id == data_id)
            )
        }
        definitions = {
            p.id: p
            for p in db.scalars(
                select(CatalogParameter).where(
                    CatalogParameter.id.in_({e.parameter_id for e in entries.values()})
                )
            )
        }
        links = {
            p.id: p.key
            for p in db.scalars(select(CatalogLink).where(CatalogLink.id.in_(entries)))
        }
        processed = {}
        for phase, kind in KINDS.items():
            cursor, count = 0, 0
            while rows := snapshot.batch(phase, cursor, batch_size):
                records = {
                    r.source_id: r
                    for r in db.scalars(
                        select(CatalogSourceMapping)
                        .options(undefer(CatalogSourceMapping.source_json))
                        .where(
                            CatalogSourceMapping.version_id == data_id,
                            CatalogSourceMapping.kind == kind,
                            CatalogSourceMapping.source_key == SOURCE,
                            CatalogSourceMapping.source_id.in_([r["id"] for r in rows]),
                        )
                    )
                }
                stored_values = (
                    {
                        v.id: v
                        for v in db.scalars(
                            select(CatalogValue).where(
                                CatalogValue.id.in_(
                                    [r.target_id for r in records.values()]
                                )
                            )
                        )
                    }
                    if phase == "values"
                    else {}
                )
                for row in rows:
                    record = records.get(row["id"])
                    if not record or record.payload_sha256 != digest(row):
                        raise ValueError(
                            f"Missing/changed source record: {kind} {row['id']}"
                        )
                    if phase == "values":
                        value = stored_values.get(record.target_id)
                        if (
                            not value
                            or record.context_id != context[row["parameter_id"]][0]
                            or value.parameter_id != context[row["parameter_id"]][1]
                            or value.value_text != row["value_text"]
                            or record.ordinal != row["value_order"]
                            or record.data != {"parameter_id": row["parameter_id"]}
                            or value.key
                            != digest(
                                {
                                    "parameter": value.parameter_id,
                                    "text": row["value_text"],
                                }
                            )
                        ):
                            raise ValueError(
                                "Stored value or allowed-value membership differs"
                            )
                    elif record.data != {
                        k: v for k, v in row.items() if k != "raw_json"
                    } or record.source_json != row.get("raw_json"):
                        raise ValueError("Stored source metadata differs")
                    elif phase == "parameters":
                        entry = entries.get(record.target_id)
                        if (
                            not entry
                            or entry.category_id != cats[row["category_id"]]
                            or record.context_id != entry.category_id
                            or links.get(record.target_id)
                            != f"{SOURCE}:category_parameter:{row['id']}"
                            or entry.parameter_id not in definitions
                            or definitions[entry.parameter_id].type_id != row["type_id"]
                            or normalized(definitions[entry.parameter_id].name)
                            != normalized(row["name"])
                            or record.external_id != str(row["emag_parameter_id"])
                            or any(
                                getattr(entry, k) != row[k]
                                for k in (
                                    "name",
                                    "emag_parameter_id",
                                    "display_order",
                                    "is_mandatory",
                                    "is_filter",
                                    "allow_new_value",
                                )
                            )
                        ):
                            raise ValueError("Stored category parameter differs")
                    else:
                        category = db.get(CatalogCategory, record.target_id)
                        if (
                            not category
                            or category.key
                            != f"{SOURCE}:category:{row['emag_category_id']}"
                            or record.external_id != str(row["emag_category_id"])
                        ):
                            raise ValueError("Missing or incorrect common category")
                count += len(rows)
                cursor = rows[-1]["id"]
            own_count = db.scalar(
                select(func.count())
                .select_from(CatalogSourceMapping)
                .where(
                    CatalogSourceMapping.version_id == data_id,
                    CatalogSourceMapping.kind == kind,
                    CatalogSourceMapping.source_key == SOURCE,
                )
            )
            if own_count != count or count != run.source_state[phase]["count"]:
                raise ValueError("Source/mapping record count mismatch")
            if (
                expected
                and expected.get(phase) is not None
                and count != expected[phase]
            ):
                raise ValueError("Unexpected production source count: " + phase)
            processed[phase] = count
        from app.catalog_facets import resolve_tv_filters

        if run.status != "ready":
            resolve_tv_filters(db, run, data_id)
        validate_tree(db, run)
        nodes = list(
            db.scalars(select(CatalogNode).where(CatalogNode.version_id == version_id))
        )
        roots = [
            n.key
            for n in nodes
            if n.data["kind"] == "department" and n.data["parent_id"] is None
        ]
        if roots != run.counters["root_ids"]:
            # Database row ordering is not source ordering: compare ordered node metadata.
            roots = [
                n.key
                for n in sorted(nodes, key=lambda n: n.data["order"])
                if n.data["kind"] == "department" and n.data["parent_id"] is None
            ]
            if roots != run.counters["root_ids"]:
                raise ValueError("Verified 13-root hierarchy differs")
        if not set(cats.values()) <= {r.category_id for r in nodes}:
            raise ValueError("A source category is missing from the common browser")
        if len(entries) != processed["parameters"]:
            raise ValueError("Category-parameter membership count mismatch")
        tv_report = None
        if expected and expected.get("television_parameters") is not None:
            from app.catalog_store import index

            nav = index(db, run)
            tv = next(
                (r for r in nav.owned_categories.values() if r.external_id == "79"),
                None,
            )
            key = "web-item-43-3730"
            if (
                not tv
                or key not in nav.owned_nodes
                or nav.owned_nodes[key].category_id != tv.target_id
                or nav.path(key)[0] != "web-dept-43"
            ):
                raise ValueError("Televíziók is not bound beneath TV és szórakozás")
            tv_count = db.scalar(
                select(func.count())
                .select_from(CatalogLinkEntry)
                .where(
                    CatalogLinkEntry.version_id == data_id,
                    CatalogLinkEntry.category_id == tv.target_id,
                )
            )
            if tv_count != expected["television_parameters"]:
                raise ValueError("Unexpected Televíziók parameter count")
            tv_report = {
                "category_id": tv.target_id,
                "parameters": tv_count,
                "path": [nav.nodes[k]["name"] for k in nav.path(key)],
            }
        unique_values = count_unique_values(db, data_id)
        report = {
            "unified_parameter_count": len(definitions),
            "unified_value_count": unique_values,
            "unified_category_count": len(
                {n.category_id for n in nodes if n.category_id is not None}
            ),
            "complete": True,
            "televisions": tv_report,
            "processed": processed,
            "root_count": len(roots),
            "verified_at": now().isoformat(),
            "source_state": run.source_state,
        }
        db.commit()
    with Session(target) as db:
        run = db.get(CatalogVersion, version_id)
        run.verification = report
        if run.phase == "verify":
            run.status, run.phase, run.error = "ready", "complete", None
        db.commit()
    return report


def import_catalog(
    target,
    reader,
    version_id=None,
    new_version=False,
    batch_size=2000,
    pause_ms=10,
    max_batches=None,
):
    if (new_version and version_id is not None) or (
        max_batches is not None and max_batches < 1
    ):
        raise ValueError("Invalid version or batch limit")
    if not 1 <= batch_size <= 5000 or not 0 <= pause_ms <= 1000:
        raise ValueError("Invalid batch size/pause")
    with import_lock(target):
        profile = reader.profile()
        from app.web_navigation import navigation
        from app.curated_taxonomy import plan_signature

        current_plan = plan_signature(navigation())
        with Session(target) as db:
            run = db.get(CatalogVersion, version_id) if version_id else None
            if version_id and not run:
                raise ValueError("Unknown catalog version")
            if not run and not new_version:
                run = db.scalar(
                    select(CatalogVersion)
                    .where(CatalogVersion.source_key == SOURCE)
                    .order_by(CatalogVersion.id.desc())
                    .limit(1)
                )
                if run and (
                    run.source_state != profile
                    or run.counters.get("plan_signature") != current_plan
                ):
                    run = None
            if run and run.source_state != profile:
                raise ValueError("Source changed; use --new-version")
            if run is None:
                run = CatalogVersion(source_key=SOURCE, source_state=profile)
                db.add(run)
                db.commit()
            if (
                run.status != "ready"
                and run.phase != "categories"
                and run.counters.get("plan_signature") != current_plan
            ):
                raise ValueError("Hierarchy plan changed; start a new version")
            version_id = run.id
            ready = run.status == "ready"
        if ready:
            verify_version(target, reader, version_id, batch_size)
            return version_id
        batches = 0
        context = None
        try:
            while True:
                with Session(target) as db:
                    run = db.get(CatalogVersion, version_id)
                    phase = run.phase
                    if phase == "verify":
                        break
                    if phase == "categories":
                        category_phase(db, run, reader)
                    else:
                        rows = reader.batch(
                            phase,
                            run.cursor,
                            batch_size,
                            run.source_state[phase]["max_id"],
                        )
                        if not rows:
                            run.phase, run.cursor = (
                                ("values" if phase == "parameters" else "verify"),
                                0,
                            )
                            db.commit()
                            continue
                        if phase == "parameters":
                            parameter_batch(db, run, rows)
                        else:
                            if context is None:
                                context = parameter_context(db, version_id)
                            value_batch(db, run, rows, context)
                        run.cursor = rows[-1]["id"]
                        run.counters = {
                            **run.counters,
                            phase: run.counters[phase] + len(rows),
                        }
                    run.updated_at, run.error = now(), None
                    db.commit()
                    log.info(
                        json.dumps(
                            {
                                "at": now().isoformat() + "Z",
                                "version": run.id,
                                "phase": run.phase,
                                "cursor": run.cursor,
                                "counts": {k: run.counters[k] for k in TABLES},
                            }
                        )
                    )
                batches += 1
                if max_batches is not None and batches >= max_batches:
                    return version_id
                if pause_ms:
                    time.sleep(pause_ms / 1000)
            verify_version(target, reader, version_id, batch_size)
        except BaseException as error:
            with Session(target) as db:
                run = db.get(CatalogVersion, version_id)
                run.error = (
                    type(error).__name__
                    + ": stopped safely; inspect the source and resume this version or start a new one"
                )
                run.updated_at = now()
                db.commit()
            raise
        return version_id


def rebuild_catalog(target, version_id):
    """Stage a tree-only version from owned metadata; never reads the source DB.

    Memberships reference the verified immutable data version, so millions of
    allowed-value records are neither copied nor rewritten. Activation is separate.
    """
    from copy import deepcopy
    from app.catalog_store import data_version_id
    from app.category_tree import CategoryTree
    from app.curated_taxonomy import apply_taxonomy
    from app.web_navigation import navigation, observations

    with import_lock(target), Session(target) as db:
        previous = db.get(CatalogVersion, version_id)
        if (
            not previous
            or previous.status != "ready"
            or not previous.verification
            or not previous.verification.get("complete")
        ):
            raise ValueError("Rebuild requires a verified ready version")
        data_id = data_version_id(db, previous)
        records = mappings(db, data_id, "category")
        counts = {}
        from sqlalchemy import case

        grouped = {
            row.category_id: dict(row._mapping)
            for row in db.execute(
                select(
                    CatalogLinkEntry.category_id,
                    func.count().label("total"),
                    func.sum(
                        case((CatalogLinkEntry.is_mandatory.is_(True), 1), else_=0)
                    ).label("mandatory"),
                    func.sum(
                        case((CatalogLinkEntry.is_mandatory.is_(False), 1), else_=0)
                    ).label("optional"),
                )
                .where(CatalogLinkEntry.version_id == data_id)
                .group_by(CatalogLinkEntry.category_id)
            )
        }
        for internal, record in records.items():
            counts[internal] = grouped.get(
                record.target_id, {"total": 0, "mandatory": 0, "optional": 0}
            )
        tree = CategoryTree([r.data for r in records.values()], counts)
        original = navigation()
        base = apply_taxonomy(original)
        nav = build_unified(
            base,
            tree,
            observations(db, original),
            list(db.scalars(select(CategoryOverride))),
        )
        run = CatalogVersion(
            source_key=previous.source_key,
            source_state=deepcopy(previous.source_state),
            counters={
                **{p: previous.counters[p] for p in TABLES},
                "data_version_id": data_id,
                "rebuilt_from": previous.id,
            },
        )
        db.add(run)
        db.flush()
        store_tree(
            db, run, tree, base, nav, {k: r.target_id for k, r in records.items()}
        )
        from app.catalog_facets import resolve_tv_filters

        resolve_tv_filters(db, run, data_id)
        rows = validate_tree(db, run)
        if len(nav.roots) != 13 or not {r.target_id for r in records.values()} <= {
            r.category_id for r in rows.values()
        }:
            raise ValueError("Incomplete rebuilt hierarchy")
        run.verification = {
            **deepcopy(previous.verification),
            "mode": "hierarchy_rebuild",
            "data_version_id": data_id,
            "unified_category_count": len(
                {r.category_id for r in rows.values() if r.category_id is not None}
            ),
            "root_count": 13,
            "verified_at": now().isoformat(),
        }
        run.status, run.phase = "ready", "complete"
        db.commit()
        return run.id


def activate(target, version_id=None, legacy=False):
    with import_lock(target), Session(target) as db:
        run = db.get(CatalogVersion, version_id) if version_id else None
        if not legacy and (
            not run
            or run.status != "ready"
            or not run.verification
            or not run.verification.get("complete")
        ):
            raise ValueError(
                "Only a completely verified, ready catalog can be activated"
            )
        if not legacy:
            from app.catalog_store import data_version_id

            data_version_id(db, run)
        setting = db.get(Setting, ACTIVE_KEY, with_for_update=True)
        previous = setting.value if setting else "legacy"
        value = "legacy" if legacy else str(version_id)
        if not setting:
            db.add(Setting(key=ACTIVE_KEY, value=value))
        else:
            setting.value = value
        db.add(
            Audit(
                actor_id=None,
                tenant_id=None,
                action="catalog.activate",
                target=value,
                details={"previous": previous, "current": value},
            )
        )
        db.commit()
    return {"previous": previous, "current": value}


def main():
    parser = argparse.ArgumentParser(
        description="Owned reference catalog: stage, verify, explicitly activate/rollback"
    )
    parser.add_argument(
        "action", choices=["import", "rebuild", "verify", "activate", "status"]
    )
    parser.add_argument("--version", type=int)
    parser.add_argument("--new-version", action="store_true")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Explicit rollback to the unchanged pre-import reader",
    )
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--pause-ms", type=int, default=10)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--expected-television-parameters", type=int)
    for phase in TABLES:
        parser.add_argument("--expected-" + phase, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    target = engine()
    if args.action == "status":
        with Session(target) as db:
            print(
                json.dumps(
                    {
                        "active": (
                            db.get(Setting, ACTIVE_KEY).value
                            if db.get(Setting, ACTIVE_KEY)
                            else "legacy"
                        ),
                        "versions": [
                            {
                                "id": r.id,
                                "status": r.status,
                                "phase": r.phase,
                                "cursor": r.cursor,
                                "counts": r.counters,
                                "error": r.error,
                            }
                            for r in db.scalars(
                                select(CatalogVersion)
                                .order_by(CatalogVersion.id.desc())
                                .limit(20)
                            )
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        return
    if args.action == "activate":
        print(json.dumps(activate(target, args.version, args.legacy)))
        return
    if args.action == "rebuild":
        if not args.version:
            parser.error("--version is required for rebuild")
        print(
            json.dumps(
                {
                    "version": rebuild_catalog(target, args.version),
                    "active_not_changed": True,
                }
            )
        )
        return
    reader = SourceReader(engine(True))
    if args.action == "import":
        version = import_catalog(
            target,
            reader,
            args.version,
            args.new_version,
            args.batch_size,
            args.pause_ms,
            args.max_batches,
        )
        print(json.dumps({"version": version, "active_not_changed": True}))
    else:
        if not args.version:
            parser.error("--version is required for verify")
        print(
            json.dumps(
                verify_version(
                    target,
                    reader,
                    args.version,
                    args.batch_size,
                    {
                        **{p: getattr(args, "expected_" + p) for p in TABLES},
                        "television_parameters": args.expected_television_parameters,
                    },
                )
            )
        )


if __name__ == "__main__":
    from sqlalchemy.exc import SQLAlchemyError

    try:
        main()
    except (ValueError, KeyboardInterrupt) as error:
        raise SystemExit(
            str(error) or "Import paused; completed batches are preserved"
        ) from None
    except SQLAlchemyError:
        raise SystemExit(
            "Database operation failed; no activation performed. Inspect catalog status and resume the recorded version after correcting connectivity or permissions."
        ) from None
