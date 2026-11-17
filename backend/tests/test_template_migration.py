"""0012 is additive and its downgrade preserves the earlier application tables."""

from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from test_import_migration import load


def test_template_migration_round_trip_preserves_rc02():
    e = create_engine("sqlite://")
    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(directory.glob("*.py")):
                if p.name < "0012":
                    load(p).upgrade()
            tables = set(inspect(c).get_table_names())
            c.execute(
                text(
                    "INSERT INTO tenants (id,name,active,created_at) VALUES (999,'Keep',1,CURRENT_TIMESTAMP)"
                )
            )
            migration = load(next(directory.glob("0012*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - tables == {
                "import_templates",
                "import_template_chunks",
            }
            migration.downgrade()
            assert set(inspect(c).get_table_names()) == tables
            assert c.scalar(text("SELECT name FROM tenants WHERE id=999")) == "Keep"
