"""The production MySQL aggregate must use the covering index and a scoped timeout."""

from unittest.mock import MagicMock
import pytest
from sqlalchemy.dialects import mysql, sqlite
from app.catalog_import import count_unique_values


@pytest.mark.parametrize("failed", [False, True])
def test_mysql_count_forces_covering_index_and_scopes_timeout(monkeypatch, failed):
    import sqlalchemy

    db = MagicMock()
    db.get_bind.return_value.dialect.name = "mysql"
    db.get_bind.return_value.url = "mysql+pymysql://test@localhost/test"
    aggregate = MagicMock()
    connection = aggregate.connect.return_value.__enter__.return_value
    if failed:
        connection.scalar.side_effect = RuntimeError("query interrupted")
    else:
        connection.scalar.return_value = 613410
    factory = MagicMock(return_value=aggregate)
    monkeypatch.setattr(sqlalchemy, "create_engine", factory)
    if failed:
        with pytest.raises(RuntimeError, match="query interrupted"):
            count_unique_values(db, 7)
    else:
        assert count_unique_values(db, 7) == 613410
    statement = connection.scalar.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FORCE INDEX (ix_catalog_mapping_targets)" in sql
    assert "count(distinct(catalog_source_mappings.target_id))" in sql.lower()
    assert "catalog_source_mappings.version_id = 7" in sql
    assert "catalog_source_mappings.kind = 'value'" in sql
    assert "FORCE INDEX" not in str(statement.compile(dialect=sqlite.dialect()))
    assert factory.call_args.kwargs["connect_args"]["read_timeout"] == 60
    aggregate.dispose.assert_called_once()
    db.scalar.assert_not_called()
    db.commit.assert_not_called()
    db.get_bind.return_value.dispose.assert_not_called()


def test_sqlite_keeps_existing_session_without_new_connections(monkeypatch):
    import sqlalchemy

    db = MagicMock()
    db.get_bind.return_value.dialect.name = "sqlite"
    db.scalar.return_value = 101
    factory = MagicMock(side_effect=AssertionError("Unexpected connection"))
    monkeypatch.setattr(sqlalchemy, "create_engine", factory)
    assert count_unique_values(db, 2) == 101
    factory.assert_not_called()
