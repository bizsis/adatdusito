"""Verification of existing staged data: bounded SQL, durable resume and diagnostics."""

import json
import logging
import math
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select, func, update, insert, event
from sqlalchemy.orm import Session
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from pymysql.err import OperationalError as DriverError
from app import catalog_import as importer, catalog_verification as checker, reference
from app.db import enforce_reference_readonly
from app.models import Base, CatalogVersion, CatalogSourceMapping, CatalogValue, Setting
from app.catalog_constants import ACTIVE_KEY, SOURCE
from test_owned_catalog import synthetic_source


def staged(count=151):
    source, target = synthetic_source(count), create_engine("sqlite://")
    Base.metadata.create_all(target)
    # Test-only staging of a completed load, stopped before verification.
    with patch.object(importer, "verify_version", return_value={}):
        version = importer.import_catalog(
            target, importer.SourceReader(source), pause_ms=0
        )
    return target, source, version


def pending(target, version):
    with Session(target) as db:
        run = db.get(CatalogVersion, version)
        assert run.status == "building" and run.phase == "verify"
        assert not run.verification
        assert not db.get(Setting, ACTIVE_KEY)
        return run.counters.get("verification_progress", {}), run.error


def test_mysql_value_range_uses_full_primary_prefix_and_single_pk_join():
    sql = str(
        checker.value_statement(1, 2000, 4000, 2001).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FORCE INDEX (PRIMARY)" in sql
    assert (
        "LEFT OUTER JOIN catalog_parameter_values ON catalog_parameter_values.id = catalog_source_mappings.target_id"
        in sql
    )
    assert "catalog_source_mappings.source_key = 'emag_marketplace'" in sql
    assert (
        "catalog_source_mappings.source_id > 2000" in sql
        and "catalog_source_mappings.source_id <= 4000" in sql
    )
    assert "LIMIT 2001" in sql
    assert " IN (" not in sql and "source_json" not in sql


def test_interruption_resumes_checked_batches_without_reimport_or_automatic_activation(
    monkeypatch, caplog
):
    target, source, version = staged()
    caplog.set_level(logging.INFO, logger="catalog_import")
    original = checker.check_values
    calls = []

    def stop(rows, records, context):
        calls.append(rows[0]["id"])
        if len(calls) == 3:
            raise KeyboardInterrupt()
        original(rows, records, context)

    monkeypatch.setattr(checker, "check_values", stop)
    with pytest.raises(KeyboardInterrupt):
        importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=37
        )
    state, error = pending(target, version)
    assert state["cursor"] == state["processed_values"] == 74
    assert len(state["value_chunks"]) == 2
    assert state["phase"] == "values"
    assert "KeyboardInterrupt" in error
    with pytest.raises(ValueError, match="verified"):
        importer.activate(target, version)
    checked = []

    def track(rows, records, context):
        checked.extend(r["id"] for r in rows)
        original(rows, records, context)

    monkeypatch.setattr(checker, "check_values", track)
    with patch.object(importer, "value_batch", side_effect=AssertionError("Reimport")):
        report = importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=17
        )
    assert checked == list(
        range(75, 152)
    )  # old ranges replay via fingerprints, new batch size supported
    assert report["processed"]["values"] == 151 and report["complete"]
    with Session(target) as db:
        run = db.get(CatalogVersion, version)
        assert run.status == "ready" and run.error is None
        assert not db.get(Setting, ACTIVE_KEY)
        assert db.scalar(select(func.count()).select_from(CatalogVersion)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(CatalogSourceMapping)
                .where(CatalogSourceMapping.kind == "value")
            )
            == 151
        )
    events = [
        json.loads(r.message) for r in caplog.records if r.message.startswith("{")
    ]
    assert any(
        r["event"] == "verification_progress"
        and r["phase"] == "values_checkpoint_replay"
        for r in events
    )
    done = next(r for r in events if r["event"] == "verification_completed")
    assert done["elapsed_seconds"] > 0
    importer.activate(target, version)  # only explicitly, after successful completion


@pytest.mark.parametrize("side", ["source", "target"])
def test_resume_detects_changes_in_previously_verified_prefix_with_exact_record(
    monkeypatch, caplog, side
):
    target, source, version = staged()
    original = checker.check_values

    def stop(rows, records, context):
        if rows[0]["id"] > 37:
            raise KeyboardInterrupt()
        original(rows, records, context)

    monkeypatch.setattr(checker, "check_values", stop)
    with pytest.raises(KeyboardInterrupt):
        importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=37
        )
    monkeypatch.setattr(checker, "check_values", original)
    if side == "source":
        event.remove(source, "before_cursor_execute", enforce_reference_readonly)
        with source.begin() as conn:
            conn.execute(
                update(reference.values)
                .where(reference.values.c.id == 1)
                .values(value_text="changed source")
            )
        event.listen(source, "before_cursor_execute", enforce_reference_readonly)
    else:
        with Session(target) as db:
            record = db.get(CatalogSourceMapping, (version, "value", SOURCE, 1))
            db.get(CatalogValue, record.target_id).value_text = "changed target"
            db.commit()
    with pytest.raises(ValueError, match="source_id=1"):
        importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=37
        )
    state, error = pending(target, version)
    assert state["cursor"] == 37 and "source_id=1" in error
    mismatch = next(
        json.loads(r.message)
        for r in caplog.records
        if "verification_mismatch" in r.message
    )
    assert mismatch["source_id"] == 1 and mismatch["target_id"] >= 1_000_000_000
    assert mismatch["field"] == ("payload_sha256" if side == "source" else "value_text")


def test_sql_failure_preserves_original_driver_error_and_last_successful_checkpoint(
    monkeypatch,
):
    target, source, version = staged()
    original = checker.target_batch

    def broken(db, data_id, after, through, count):
        if after >= 37:
            raise OperationalError(
                "SELECT ...",
                {},
                DriverError(
                    2013, "Lost connection to MySQL server during query (timed out)"
                ),
            )
        return original(db, data_id, after, through, count)

    monkeypatch.setattr(checker, "target_batch", broken)
    with pytest.raises(OperationalError, match="2013"):
        importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=37
        )
    state, error = pending(target, version)
    assert state["cursor"] == 37
    assert "2013" in error and "Lost connection" in error and "timed out" in error
    monkeypatch.setattr(checker, "target_batch", original)
    assert (
        importer.verify_version(target, importer.SourceReader(source), version)[
            "processed"
        ]["values"]
        == 151
    )


@pytest.mark.parametrize("extra_id", [0, 999999])
def test_extra_target_mapping_is_detected_without_full_table_count(extra_id):
    target, source, version = staged()
    with Session(target) as db:
        original = db.get(CatalogSourceMapping, (version, "value", SOURCE, 1))
        db.execute(
            insert(CatalogSourceMapping).values(
                version_id=version,
                kind="value",
                source_key=SOURCE,
                source_id=extra_id,
                target_id=original.target_id,
                context_id=original.context_id,
                payload_sha256=original.payload_sha256,
                data=original.data,
            )
        )
        db.commit()
    with pytest.raises(ValueError, match=f"source_id={extra_id}"):
        importer.verify_version(target, importer.SourceReader(source), version)
    pending(target, version)


def test_value_processing_is_bounded_and_uses_one_target_range_query_per_batch(
    monkeypatch,
):
    count, size = 25001, 997
    target, source, version = staged(count)
    original = checker.target_batch
    batch_sizes = []

    def track(*args):
        rows = original(*args)
        batch_sizes.append(len(rows))
        return rows

    monkeypatch.setattr(checker, "target_batch", track)
    sql = []
    event.listen(
        target,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: sql.append(statement),
    )
    result = importer.verify_version(
        target, importer.SourceReader(source), version, batch_size=size
    )
    assert result["processed"]["values"] == count
    assert result["unified_value_count"] == 101
    assert len(batch_sizes) == math.ceil(count / size) and max(batch_sizes) <= size
    joined = [s for s in sql if "JOIN catalog_parameter_values" in s]
    assert len(joined) == len(batch_sizes) + 1  # one indexed tail check
    assert all(" IN (" not in s and "source_json" not in s for s in joined)


def test_restart_rechecks_from_first_value_after_interruption(monkeypatch):
    target, source, version = staged()
    original = checker.check_values

    def stop(rows, records, context):
        if rows[0]["id"] > 37:
            raise KeyboardInterrupt()
        original(rows, records, context)

    monkeypatch.setattr(checker, "check_values", stop)
    with pytest.raises(KeyboardInterrupt):
        importer.verify_version(
            target, importer.SourceReader(source), version, batch_size=37
        )
    seen = []

    def track(rows, records, context):
        seen.extend(r["id"] for r in rows)
        original(rows, records, context)

    monkeypatch.setattr(checker, "check_values", track)
    importer.verify_version(
        target, importer.SourceReader(source), version, restart=True
    )
    assert seen == list(range(1, 152))


def test_parameter_flag_difference_logs_exact_source_and_field(caplog):
    from app.models import CatalogLinkEntry

    target, source, version = staged()
    with Session(target) as db:
        mapping = db.get(CatalogSourceMapping, (version, "parameter", SOURCE, 31))
        db.get(CatalogLinkEntry, (version, mapping.target_id)).is_mandatory = False
        db.commit()
    with pytest.raises(ValueError, match="source_id=31.*field=is_mandatory"):
        importer.verify_version(target, importer.SourceReader(source), version)
    event = next(
        json.loads(r.message)
        for r in caplog.records
        if "verification_mismatch" in r.message
    )
    assert event["phase"] == "parameters" and event["field"] == "is_mandatory"
    pending(target, version)


def test_original_sql_error_is_not_masked_if_error_status_cannot_be_saved(
    monkeypatch, caplog
):
    target = create_engine("sqlite://")
    original = OperationalError(
        "SELECT ...", {}, DriverError(2013, "Lost connection during query")
    )

    def fail(*args):
        raise original

    monkeypatch.setattr(importer, "_verify_version", fail)

    def cannot_save(*args):
        raise RuntimeError("status connection unavailable")

    monkeypatch.setattr(importer, "Session", cannot_save)
    with pytest.raises(OperationalError) as caught:
        importer.verify_version(target, None, 1)
    assert caught.value is original
    assert any(
        "verification_error_persistence_failed" in r.message for r in caplog.records
    )
    assert any(
        "2013" in r.message and "Lost connection during query" in r.message
        for r in caplog.records
    )


def test_failed_reverification_blocks_activation_even_with_an_old_success_report(
    monkeypatch,
):
    target, source, version = staged()
    importer.verify_version(target, importer.SourceReader(source), version)
    original = checker.target_batch

    def fail(*args):
        raise OperationalError("SELECT ...", {}, DriverError(2013, "timed out"))

    monkeypatch.setattr(checker, "target_batch", fail)
    with pytest.raises(OperationalError):
        importer.verify_version(target, importer.SourceReader(source), version)
    with pytest.raises(ValueError, match="verified"):
        importer.activate(target, version)
    monkeypatch.setattr(checker, "target_batch", original)
    importer.verify_version(target, importer.SourceReader(source), version)
    assert importer.activate(target, version)["current"] == str(version)


def test_metadata_extra_null_key_is_not_confused_with_missing_key():
    target, source, version = staged()
    with Session(target) as db:
        record = db.get(CatalogSourceMapping, (version, "category", SOURCE, 11))
        record.data = {**record.data, "unexpected": None}
        db.commit()
    with pytest.raises(ValueError, match="source_id=11.*source_metadata.unexpected"):
        importer.verify_version(target, importer.SourceReader(source), version)
    pending(target, version)
