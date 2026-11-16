"""0008 -> 0009 keeps every product, import and access record; guarded downgrade."""

from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from test_access_migration import load

DIRECTORY = Path(__file__).resolve().parents[1] / "migrations/versions"


def seed(c):
    c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                   "VALUES (1,'root','root@example.hu','Root','h',1,1,CURRENT_TIMESTAMP)"))
    c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Ügyfél',1,CURRENT_TIMESTAMP)"))
    c.execute(text("INSERT INTO import_suppliers(id,tenant_id,name) VALUES (1,1,'Beszállító')"))
    columns = {col["name"] for col in inspect(c).get_columns("import_runs")}
    values = {
        "id": 1, "tenant_id": 1, "supplier_id": 1, "filename": "a.csv", "state": "completed",
        "config": "{}", "analysis": "{}", "cursor": 3, "counters": "{}",
        "created_at": "2026-11-01 10:00:00", "updated_at": "2026-11-01 10:00:00",
    }
    for extra in columns - set(values):
        nullable = next(col["nullable"] for col in inspect(c).get_columns("import_runs") if col["name"] == extra)
        if not nullable:
            values[extra] = 1 if extra.endswith("_by") or extra.endswith("_id") else "x"
    c.execute(text(f"INSERT INTO import_runs({','.join(values)}) VALUES ({','.join(':' + k for k in values)})"), values)
    c.execute(text("INSERT INTO supplier_products(id,tenant_id,supplier_id,identity_key,data,last_run_id,last_line) "
                   "VALUES (7,1,1,'k','{\"sku\": \"001\", \"category\": \"Régi\"}',1,2)"))
    c.execute(text("INSERT INTO import_changes(product_id,run_id,line,delta) VALUES (7,1,2,'{}')"))


def test_0009_is_additive_and_downgrade_is_guarded():
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(DIRECTORY.glob("000[1-8]*.py")):
                load(p).upgrade()
            seed(c)
            tables = set(inspect(c).get_table_names())
            migration = load(next(DIRECTORY.glob("0009*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - tables == {
                "product_source_categories", "category_maps", "product_classifications",
                "product_events", "product_jobs",
            }
            row = c.execute(text("SELECT id,identity_key,data,revision,source_category_id,source_attributes "
                                 "FROM supplier_products")).one()
            assert row[:2] == (7, "k") and "Régi" in row[2]
            assert (row[3], row[4], row[5]) == (1, None, None)
            assert c.scalar(text("SELECT COUNT(*) FROM import_changes")) == 1
            assert c.scalar(text("SELECT COUNT(*) FROM permissions WHERE code='products.classify'")) == 1
            # Without decisions the downgrade is clean and repeatable.
            migration.downgrade()
            assert {"revision", "source_attributes"}.isdisjoint(
                {col["name"] for col in inspect(c).get_columns("supplier_products")})
            assert c.scalar(text("SELECT COUNT(*) FROM supplier_products")) == 1
            assert c.scalar(text("SELECT COUNT(*) FROM permissions WHERE code='products.classify'")) == 0
            migration.upgrade()
            c.execute(text("INSERT INTO product_source_categories(id,tenant_id,supplier_id,origin,path_key,path_text,created_at) "
                           "VALUES (1,1,1,'supplier','x','Régi',CURRENT_TIMESTAMP)"))
            c.execute(text("INSERT INTO category_maps(source_category_id,tenant_id,state,revision,decided_by,decided_at) "
                           "VALUES (1,1,'rejected',1,1,CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()
            assert c.scalar(text("SELECT COUNT(*) FROM category_maps")) == 1
