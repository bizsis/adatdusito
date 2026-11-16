"""0009 -> 0010 is additive; downgrade refuses once parameter decisions exist."""

from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from test_access_migration import load
from test_category02a_migration import seed

DIRECTORY = Path(__file__).resolve().parents[1] / "migrations/versions"


def test_0010_is_additive_and_downgrade_is_guarded():
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(DIRECTORY.glob("000[1-9]*.py")):
                load(p).upgrade()
            seed(c)
            tables = set(inspect(c).get_table_names())
            migration = load(next(DIRECTORY.glob("0010*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - tables == {"parameter_aliases", "product_parameter_values"}
            assert c.scalar(text("SELECT COUNT(*) FROM supplier_products")) == 1
            codes = {r[0] for r in c.execute(text("SELECT code FROM permissions"))}
            assert {"products.parameters", "parameters.global_aliases.manage"} <= codes
            indexes = {i["name"] for i in inspect(c).get_indexes("product_parameter_values")}
            assert {"ix_product_parameter_state", "ix_product_parameter_emag"} <= indexes
            # Automatic, unlocked slots only: downgrade is clean and repeatable.
            c.execute(text(
                "INSERT INTO product_parameter_values(product_id,slot_key,tenant_id,name,display_order,state,"
                "origin,reason_codes,details,mandatory,locked,rule_version,updated_at) VALUES "
                "(7,'emag:1',1,'X',0,'missing','added_slot','[]','{}',0,0,'r',CURRENT_TIMESTAMP)"))
            c.execute(text("DELETE FROM product_parameter_values"))
            migration.downgrade()
            assert not {"parameter_aliases", "product_parameter_values"} & set(inspect(c).get_table_names())
            assert c.scalar(text("SELECT COUNT(*) FROM permissions WHERE code='products.parameters'")) == 0
            migration.upgrade()
            c.execute(text(
                "INSERT INTO product_parameter_values(product_id,slot_key,tenant_id,name,display_order,state,"
                "origin,reason_codes,details,mandatory,locked,rule_version,updated_at) VALUES "
                "(7,'emag:1',1,'X',0,'present','user','[]','{}',0,1,'r',CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()
            assert c.scalar(text("SELECT COUNT(*) FROM product_parameter_values")) == 1
