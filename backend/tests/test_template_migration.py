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


def test_downgrade_preflights_lower_guard_before_any_ddl(monkeypatch):
    from types import SimpleNamespace
    import pytest

    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    migration = load(next(directory.glob("0012*.py")))
    statements = []
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: SimpleNamespace(opts={"destination_rev": "0010"}),
    )
    monkeypatch.setattr(
        migration.op, "get_bind", lambda: SimpleNamespace(scalar=lambda query: 1)
    )
    monkeypatch.setattr(migration.op, "drop_table", statements.append)
    with pytest.raises(RuntimeError, match="Preparation approvals exist"):
        migration.downgrade()
    assert statements == []


def test_mysql_downgrade_drops_tables_with_their_fk_indexes(monkeypatch):
    from types import SimpleNamespace

    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    migration = load(next(directory.glob("0012*.py")))
    statements = []
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: SimpleNamespace(opts={"destination_rev": "0011"}),
    )
    monkeypatch.setattr(
        migration.op, "get_bind", lambda: SimpleNamespace(scalar=lambda query: 0)
    )
    monkeypatch.setattr(migration.op, "drop_table", statements.append)
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("MySQL FK-backed index must be dropped with its table")
        ),
    )
    migration.downgrade()
    assert statements == ["import_template_chunks", "import_templates"]
