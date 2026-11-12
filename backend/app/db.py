import os
from functools import lru_cache
from sqlalchemy import create_engine, text

@lru_cache
def engine(reference=False):
    key = "REFERENCE_DATABASE_URL" if reference else "APP_DATABASE_URL"
    url = os.environ[key]
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    expected = "pinfo_db" if reference else "adatdusito_dev"
    if parsed.database != expected or parsed.get_backend_name() != "mysql":
        raise ValueError("Unexpected database target")
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3})

def check_database(reference=False):
    with engine(reference).connect() as connection:
        if reference:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            for table in ("emag_categories", "emag_category_parameters", "emag_parameter_values"):
                connection.execute(text(f"SELECT 1 FROM `{table}` LIMIT 1"))
        else:
            connection.execute(text("SELECT 1"))
