import os
from functools import lru_cache
from sqlalchemy import create_engine, text, event
from contextlib import contextmanager


@lru_cache
def engine(reference=False):
    key = "REFERENCE_DATABASE_URL" if reference else "APP_DATABASE_URL"
    url = os.environ[key]
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    expected = "pinfo_db" if reference else "adatdusito_dev"
    if parsed.database != expected or parsed.get_backend_name() != "mysql":
        raise ValueError("Unexpected database target")
    result = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 3},
    )
    if reference:
        event.listen(result, "before_cursor_execute", enforce_reference_readonly)
    return result


def check_database(reference=False):
    if reference:
        from sqlalchemy.orm import Session
        from app.catalog_store import active_version, data_version_id
        from app.models import CatalogNode, CatalogLinkEntry, CatalogValue
        from sqlalchemy import select

        with Session(engine()) as db:
            version = active_version(db)
            if version:
                db.execute(
                    select(CatalogNode.key)
                    .where(CatalogNode.version_id == version.id)
                    .limit(1)
                )
                db.execute(
                    select(CatalogLinkEntry.link_id)
                    .where(CatalogLinkEntry.version_id == data_version_id(db, version))
                    .limit(1)
                )
                db.execute(select(CatalogValue.id).limit(1))
                return
    with engine(reference).connect() as connection:
        if reference:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            for table in (
                "emag_categories",
                "emag_category_parameters",
                "emag_parameter_values",
            ):
                connection.execute(text(f"SELECT 1 FROM `{table}` LIMIT 1"))
        else:
            connection.execute(text("SELECT 1"))


def enforce_reference_readonly(
    conn, cursor, statement, parameters, context, executemany
):
    # Defence in depth. The SELECT-only DB account remains mandatory.
    normalized = statement.strip().upper()
    if not (
        normalized.startswith("SELECT ") or normalized == "SET TRANSACTION READ ONLY"
    ):
        raise PermissionError("Reference database is read-only")
    if (
        " INTO OUTFILE" in normalized
        or " INTO DUMPFILE" in normalized
        or " FOR UPDATE" in normalized
    ):
        raise PermissionError("Reference database is read-only")


@contextmanager
def reference_database():
    with engine(True).connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        yield connection
