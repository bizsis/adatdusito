"""Isolated 0015 DDL contract. Full 0013->0014->0015 awaits Claude's real 0014.

No fake or substitute 0014 is created by this test.
"""

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
            # Existing known schema only: this is a DDL unit test, not chain validation.
            for file in sorted(directory.glob("00*.py")):
                if file.name < "0014":
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
