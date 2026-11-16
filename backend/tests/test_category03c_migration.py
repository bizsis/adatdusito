"""0010 -> 0011 is additive; downgrade refuses once preparation approvals exist."""

from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from test_access_migration import load
from test_category02a_migration import seed

DIRECTORY = Path(__file__).resolve().parents[1] / "migrations/versions"
NEW = {"product_selections", "product_selection_items", "product_operation_items",
       "preparation_approvals", "preparation_approval_items"}


def test_0011_is_additive_and_downgrade_is_guarded():
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(DIRECTORY.glob("00*.py")):
                if p.name < "0011":
                    load(p).upgrade()
            seed(c)
            c.execute(text("INSERT INTO product_jobs(id,tenant_id,kind,state,cursor,counters,created_at,updated_at) "
                           "VALUES (1,1,'backfill_category_02a','completed',7,'{}',CURRENT_TIMESTAMP,"
                           "CURRENT_TIMESTAMP)"))
            tables = set(inspect(c).get_table_names())
            migration = load(next(DIRECTORY.glob("0011*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - tables == NEW
            columns = {col["name"] for col in inspect(c).get_columns("product_jobs")}
            assert {"created_by", "idempotency_key", "request_hash"} <= columns
            assert c.scalar(text("SELECT cursor FROM product_jobs WHERE id=1")) == 7  # existing job kept
            codes = {r[0] for r in c.execute(text("SELECT code FROM permissions"))}
            assert {"products.bulk", "products.prepare.approve"} <= codes
            migration.downgrade()
            assert not NEW & set(inspect(c).get_table_names())
            assert c.scalar(text("SELECT COUNT(*) FROM product_jobs")) == 1
            migration.upgrade()
            c.execute(text("INSERT INTO product_selections(id,tenant_id,created_by,token_hash,mode,filters,"
                           "excluded,total,rule_version,created_at,expires_at) VALUES "
                           "(1,1,1,'h','filters','{}',0,1,'r',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            c.execute(text("INSERT INTO product_jobs(id,tenant_id,kind,state,cursor,counters,created_at,updated_at) "
                           "VALUES (2,1,'preparation_check','completed',0,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            c.execute(text("INSERT INTO preparation_approvals(id,tenant_id,state,version,check_id,selection_id,"
                           "rule_version,schema_fingerprint,counts,idempotency_key,request_hash,approved_by,"
                           "approved_at) VALUES (1,1,'active',1,2,1,'r','f','{}','k','h',1,CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()
