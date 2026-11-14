"""Upgrade only application import tables, preserving earlier data and grants."""

import importlib.util
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_migration_round_trip():
    e = create_engine("sqlite://")
    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(directory.glob("000[1-5]*.py")):
                load(p).upgrade()
            before = set(inspect(c).get_table_names())
            c.execute(
                text(
                    "INSERT INTO tenants (id,name,active,created_at) VALUES (999,'Preserved',1,CURRENT_TIMESTAMP)"
                )
            )
            m = load(next(directory.glob("0006*.py")))
            m.upgrade()
            assert (
                c.scalar(text("SELECT name FROM tenants WHERE id=999")) == "Preserved"
            )
            assert (
                c.scalar(text("SELECT name FROM store_engines WHERE `key`='unas'"))
                == "UNAS"
            )
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM role_permissions WHERE permission='imports.manage'"
                    )
                )
                == 3
            )
            assert len(set(inspect(c).get_table_names()) - before) == 9
            m.downgrade()
            assert set(inspect(c).get_table_names()) == before
            assert (
                c.scalar(text("SELECT name FROM tenants WHERE id=999")) == "Preserved"
            )
