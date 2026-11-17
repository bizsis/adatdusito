"""0014->0015 DDL contract using Claude's real, integrated 0014."""

from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from test_access_migration import load
import pytest


def test_0015_ddl_is_additive_and_upload_downgrade_is_guarded():
    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for file in sorted(directory.glob("00*.py")):
                if file.name < "0015":
                    load(file).upgrade()
            before = set(inspect(connection).get_table_names())
            migration = load(next(directory.glob("0015*.py")))
            assert migration.down_revision == "0014"
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) - before == {
                "reference_import_chunks"
            }
            assert {
                c["name"]
                for c in inspect(connection).get_columns("reference_import_runs")
            } >= {"ui_config", "ui_cursor", "ui_task_token", "ui_lease_until"}
            connection.execute(
                text(
                    "INSERT INTO reference_import_chunks(run_id,ordinal,data) VALUES(999,0,X'00')"
                )
            )
            with pytest.raises(RuntimeError, match="Stored reference uploads"):
                migration.downgrade()
            connection.execute(text("DELETE FROM reference_import_chunks"))
            migration.downgrade()
            assert set(inspect(connection).get_table_names()) == before


def test_0015_preflights_knowledge_decisions_before_cross_revision_ddl(monkeypatch):
    from types import SimpleNamespace

    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    migration = load(next(directory.glob("0015*.py")))
    executed = []

    def scalar(query):
        return 1 if "knowledge_values" in str(query) else 0

    monkeypatch.setattr(
        migration.op, "get_bind", lambda: SimpleNamespace(scalar=scalar)
    )
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: SimpleNamespace(opts={"destination_rev": "0013"}),
    )
    monkeypatch.setattr(migration.op, "drop_table", executed.append)
    with pytest.raises(RuntimeError, match="Protected decisions"):
        migration.downgrade()
    assert executed == []
