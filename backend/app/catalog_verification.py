"""Bounded, indexed value verification with durable, replay-checked checkpoints."""

import json
import logging
import time
from sqlalchemy import select
from app.models import CatalogSourceMapping, CatalogValue
from app.catalog_constants import SOURCE

log = logging.getLogger("catalog_import")
CHECKER_VERSION = 1


def sql_error(error):
    # DBAPI's original error, without SQLAlchemy's potentially huge SQL/params.
    original = getattr(error, "orig", error)
    return f"{type(error).__name__}: {original}"


def mismatch(phase, source_id, target_id, field, expected, actual, message):
    def preview(value):
        return repr(value)[:240]

    details = dict(
        event="verification_mismatch",
        phase=phase,
        source_id=source_id,
        target_id=target_id,
        field=field,
        expected=preview(expected),
        actual=preview(actual),
    )
    log.error(json.dumps(details, ensure_ascii=False))
    raise ValueError(
        f"{message}: phase={phase} source_id={source_id} target_id={target_id} field={field}; expected={preview(expected)} actual={preview(actual)}"
    )


def value_statement(data_id, after, through=None, limit=None):
    m, v = CatalogSourceMapping.__table__, CatalogValue.__table__
    statement = (
        select(
            m.c.source_id,
            m.c.target_id,
            m.c.context_id,
            m.c.ordinal,
            m.c.payload_sha256,
            m.c.data,
            v.c.id.label("value_id"),
            v.c.parameter_id,
            v.c.key,
            v.c.value_text,
        )
        .select_from(m.outerjoin(v, v.c.id == m.c.target_id))
        .where(
            m.c.version_id == data_id,
            m.c.kind == "value",
            m.c.source_key == SOURCE,
            m.c.source_id > after,
        )
        .with_hint(m, "FORCE INDEX (PRIMARY)", dialect_name="mysql")
        .order_by(m.c.source_id)
    )
    if through is not None:
        statement = statement.where(m.c.source_id <= through)
    if limit is not None:
        statement = statement.limit(limit)
    return statement


def target_batch(db, data_id, after, through, count):
    # One indexed range + value PK join. No ORM hydration, raw JSON blobs,
    # separate value query or multi-thousand-element IN clause.
    return [
        dict(r)
        for r in db.execute(
            value_statement(data_id, after, through, count + 1)
        ).mappings()
    ]


def batch_digests(rows, records):
    from app.catalog_import import digest

    return digest(rows), digest(records)


def check_values(rows, records, context):
    from app.catalog_import import digest

    by_id = {r["source_id"]: r for r in records}
    expected_ids = {r["id"] for r in rows}
    for unexpected in set(by_id) - expected_ids:
        mismatch(
            "values",
            unexpected,
            by_id[unexpected]["target_id"],
            "source_id",
            "absent",
            unexpected,
            "Unexpected target mapping",
        )
    for row in rows:
        record = by_id.get(row["id"])
        target_id = record["target_id"] if record else None

        def check(
            field,
            expected,
            actual,
            message="Stored value or allowed-value membership differs",
        ):
            if expected != actual:
                mismatch(
                    "values", row["id"], target_id, field, expected, actual, message
                )

        if not record:
            mismatch(
                "values",
                row["id"],
                None,
                "mapping",
                "present",
                None,
                "Missing/changed source record",
            )
        check(
            "payload_sha256",
            digest(row),
            record["payload_sha256"],
            "Missing/changed source record",
        )
        if row["parameter_id"] not in context:
            mismatch(
                "values",
                row["id"],
                target_id,
                "parameter_id",
                "existing source parameter",
                row["parameter_id"],
                "Missing source parameter mapping",
            )
        link_id, definition_id = context[row["parameter_id"]]
        check("value_id", target_id, record["value_id"])
        check("context_id", link_id, record["context_id"])
        check("parameter_id", definition_id, record["parameter_id"])
        check("value_text", row["value_text"], record["value_text"])
        check("ordinal", row["value_order"], record["ordinal"])
        check("data", {"parameter_id": row["parameter_id"]}, record["data"])
        check(
            "key",
            digest({"parameter": definition_id, "text": row["value_text"]}),
            record["key"],
        )


def progress(run, phase, count, total, started, previous=0):
    elapsed = time.monotonic() - started
    log.info(
        json.dumps(
            dict(
                event="verification_progress",
                version=run.id,
                phase=phase,
                processed=count,
                total=total,
                percent=round(100 * count / total, 2) if total else 100,
                elapsed_seconds=round(elapsed, 3),
                total_elapsed_seconds=round(previous + elapsed, 3),
                rows_per_second=round(count / elapsed, 1) if elapsed else 0,
            ),
            ensure_ascii=False,
        )
    )


def verify_values(db, run, snapshot, data_id, context, batch_size, state, started):
    total = run.source_state["values"]["count"]
    chunks = state.get("value_chunks", [])
    # Completed ranges are re-read from both current snapshots. Count/max-ID
    # fingerprints alone cannot detect in-place changes during an interruption.
    # Digest replay avoids repeating per-row validation while detecting changes.
    cursor, count = 0, 0
    for chunk in chunks:
        rows = snapshot.batch("values", cursor, chunk["count"], chunk["through"])
        records = target_batch(db, data_id, cursor, chunk["through"], chunk["count"])
        source_sha, target_sha = batch_digests(rows, records)
        if source_sha != chunk["source_sha"] or target_sha != chunk["target_sha"]:
            # Full comparison identifies an individual record and differing field.
            check_values(rows, records, context)
            mismatch(
                "values",
                chunk["through"],
                None,
                "checkpoint_digest",
                "unchanged checked range",
                "changed source/target range",
                "Verification checkpoint changed; restart verification",
            )
        cursor, count = chunk["through"], count + chunk["count"]
        progress(
            run,
            "values_checkpoint_replay",
            count,
            total,
            started,
            state.get("elapsed_seconds", 0),
        )
    # Source auto-increment IDs are positive. Detect unexpected non-positive rows
    # as well as gaps/extra mappings in every range and beyond the final cursor.
    m = CatalogSourceMapping.__table__
    invalid = db.scalar(
        select(m.c.source_id)
        .where(
            m.c.version_id == data_id,
            m.c.kind == "value",
            m.c.source_key == SOURCE,
            m.c.source_id <= 0,
        )
        .limit(1)
    )
    if invalid is not None:
        mismatch(
            "values",
            invalid,
            None,
            "source_id",
            "positive",
            invalid,
            "Unexpected target mapping",
        )
    previous = state.get("elapsed_seconds", 0)
    while rows := snapshot.batch("values", cursor, batch_size):
        records = target_batch(db, data_id, cursor, rows[-1]["id"], len(rows))
        check_values(rows, records, context)
        source_sha, target_sha = batch_digests(rows, records)
        next_chunks = chunks + [
            dict(
                through=rows[-1]["id"],
                count=len(rows),
                source_sha=source_sha,
                target_sha=target_sha,
            )
        ]
        state = {
            **state,
            "phase": "values",
            "value_chunks": next_chunks,
            "cursor": rows[-1]["id"],
            "processed_values": count + len(rows),
            "elapsed_seconds": previous + time.monotonic() - started,
        }
        run.counters = {
            **run.counters,
            "verification_progress": {**state, "complete": False},
        }
        run.error = None
        db.commit()  # checkpoint only after all actual source/target checks pass
        chunks, cursor, count = next_chunks, rows[-1]["id"], count + len(rows)
        progress(run, "values", count, total, started, previous)
    extra = db.execute(value_statement(data_id, cursor, limit=1)).mappings().first()
    if extra:
        mismatch(
            "values",
            extra["source_id"],
            extra["target_id"],
            "source_id",
            "absent",
            extra["source_id"],
            "Unexpected target mapping",
        )
    if count != total:
        mismatch(
            "values",
            cursor,
            None,
            "count",
            total,
            count,
            "Source/mapping record count mismatch",
        )
    progress(run, "values_complete", count, total, started, previous)
    return count


def check_metadata(phase, row, record, cats, entries, links, definitions, categories):
    from app.unified_categories import normalized
    from app.catalog_import import digest

    def check(field, expected, actual, message):
        if expected != actual:
            mismatch(
                phase, row["id"], record.target_id, field, expected, actual, message
            )

    expected_data = {k: v for k, v in row.items() if k != "raw_json"}
    actual_data = record.data
    if not isinstance(actual_data, dict):
        mismatch(
            phase,
            row["id"],
            record.target_id,
            "source_metadata",
            "JSON object",
            actual_data,
            "Stored source metadata differs",
        )
    if expected_data != actual_data:
        for key in sorted(set(expected_data) ^ set(actual_data)):
            mismatch(
                phase,
                row["id"],
                record.target_id,
                "source_metadata." + key + ".presence",
                key in expected_data,
                key in actual_data,
                "Stored source metadata differs",
            )
        for key in sorted(expected_data):
            check(
                "source_metadata." + key,
                expected_data[key],
                actual_data[key],
                "Stored source metadata differs",
            )
    if record.source_json != row.get("raw_json"):
        check(
            "raw_json_sha256",
            digest(row.get("raw_json")),
            digest(record.source_json),
            "Stored source metadata differs",
        )
    if phase == "categories":
        category = categories.get(record.target_id)
        check(
            "category.key",
            f"{SOURCE}:category:{row['emag_category_id']}",
            category.key if category else None,
            "Missing or incorrect common category",
        )
        check(
            "external_id",
            str(row["emag_category_id"]),
            record.external_id,
            "Missing or incorrect common category",
        )
        return
    message = "Stored category parameter differs"
    entry = entries.get(record.target_id)
    if not entry:
        mismatch(
            phase,
            row["id"],
            record.target_id,
            "category_parameter",
            "present",
            None,
            message,
        )
    check("category_id", cats.get(row["category_id"]), entry.category_id, message)
    check("context_id", entry.category_id, record.context_id, message)
    check(
        "link.key",
        f"{SOURCE}:category_parameter:{row['id']}",
        links.get(record.target_id),
        message,
    )
    definition = definitions.get(entry.parameter_id)
    if not definition:
        mismatch(
            phase,
            row["id"],
            record.target_id,
            "parameter_definition",
            "present",
            None,
            message,
        )
    check("definition.type_id", row["type_id"], definition.type_id, message)
    check(
        "definition.name", normalized(row["name"]), normalized(definition.name), message
    )
    check("external_id", str(row["emag_parameter_id"]), record.external_id, message)
    for key in (
        "name",
        "emag_parameter_id",
        "display_order",
        "is_mandatory",
        "is_filter",
        "allow_new_value",
    ):
        check(key, row[key], getattr(entry, key), message)
