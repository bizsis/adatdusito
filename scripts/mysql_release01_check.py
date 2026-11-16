"""RELEASE-01: Alembic 0008 -> 0009 -> 0010 -> 0011 release check on a THROWAWAY MySQL 8.

Only for an EMPTY database on a loopback MySQL server (loopback host,
empty database). Never run it on the VPS, a shared server or pinfo_db.
It prints counts, short hashes, revisions and permission codes only: no row
contents, passwords, tokens or secrets.

Checks:
  1. 0008 seed (2000 products, import rows, users, memberships, a tenant-local
     admin role copy, a custom role), then step-by-step upgrade to 0011: the
     pre-existing rows must stay byte-identical; a repeated `upgrade head` is a no-op;
  2. the five new permission codes exist; no role_permissions rows are added;
     effective permissions of superadmin / built-in tenant_admin / processor /
     tenant-local admin copy / custom role;
  3. 0011 downgrade: refused while an approval exists; succeeds without one;
  4. interrupted 0011 (MySQL DDL is not transactional): what is left behind and
     whether a plain re-run recovers.

Exit code 1 when a result differs from the expected (released) behaviour.

    export APP_DATABASE_URL='mysql+pymysql://USER:PASS@127.0.0.1:PORT/adatdusito_dev'
    cd backend && PYTHONPATH=. python ../scripts/mysql_release01_check.py
"""

import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import bindparam, create_engine, inspect, make_url, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PRESERVED = {
    "users": "id,username,email,active,superadmin",
    "tenants": "id,name,active",
    "memberships": "tenant_id,user_id,role,active",
    "access_roles": "id,owner,code,permissions,managed,protected",
    "access_bindings": "user_id,context,role_id",
    "role_permissions": "role,permission",
    "supplier_products": "id,tenant_id,supplier_id,identity_key,data,last_run_id,last_line",
    "import_rows": "run_id,line,raw,normalized,state,product_id",
    "import_runs": "id,tenant_id,state,cursor",
}
NEW = ["products.classify", "products.parameters", "parameters.global_aliases.manage",
       "products.bulk", "products.prepare.approve"]
TENANT_NEW = sorted(set(NEW) - {"parameters.global_aliases.manage"})


def guard(url):
    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql" or parsed.host not in LOOPBACK:
        sys.exit("Refusing: APP_DATABASE_URL must be a MySQL server on a loopback host.")
    scratch = create_engine(url)
    with scratch.connect() as c:
        if inspect(c).get_table_names():
            sys.exit("Refusing: the target database is not empty; use a throwaway server.")
        return scratch, c.scalar(text("SELECT VERSION()"))


def seed_products(scratch, n):
    """Pre-0009 data: one tenant, supplier, completed import run, n products and import rows."""
    with scratch.begin() as c:
        c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                       "VALUES (1,'root','root@example.invalid','Root','x',1,1,NOW())"))
        c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Mérés',1,NOW())"))
        c.execute(text("INSERT INTO import_suppliers(id,tenant_id,name) VALUES (1,1,'Mérés')"))
        cols = {col["name"]: col for col in inspect(c).get_columns("import_runs")}
        values = {"id": 1, "tenant_id": 1, "supplier_id": 1, "filename": "seed.csv", "state": "completed",
                  "config": json.dumps({"mapping": {"0": "sku", "1": "name", "2": "category"}}),
                  "analysis": json.dumps({"headers": ["SKU", "NAME", "CATEGORY", "Szín"]}), "cursor": n,
                  "counters": "{}", "created_at": "2026-11-01 10:00:00", "updated_at": "2026-11-01 10:00:00"}
        for extra, col in cols.items():
            if extra not in values and not col["nullable"] and col.get("default") is None:
                values[extra] = 1 if extra.endswith(("_by", "_id")) else "x"
        c.execute(text(f"INSERT INTO import_runs({','.join('`' + k + '`' for k in values)}) "
                       f"VALUES ({','.join(':' + k for k in values)})"), values)
        c.execute(text("INSERT INTO supplier_products(id,tenant_id,supplier_id,identity_key,data,last_run_id,last_line) "
                       "VALUES (:id,1,1,:k,:data,1,:line)"),
                  [{"id": i, "k": f"k{i:08d}", "line": i + 1,
                    "data": json.dumps({"sku": f"SKU-{i:08d}", "name": f"Termék {i}", "category": "A > B"},
                                       ensure_ascii=False)} for i in range(1, n + 1)])
        c.execute(text("INSERT INTO import_rows(run_id,line,raw,normalized,issues,state,product_id) "
                       "VALUES (1,:line,:raw,'{}','[]','imported',:id)"),
                  [{"id": i, "line": i + 1, "raw": json.dumps([f"SKU-{i:08d}", f"Termék {i}", "A > B", "Fehér"],
                                                             ensure_ascii=False)} for i in range(1, n + 1)])


def fingerprint(c):
    out = {}
    for table, cols in PRESERVED.items():
        q = ",".join(f"`{x}`" for x in cols.split(","))
        rows = c.execute(text(f"SELECT {q} FROM {table} ORDER BY {q}")).all()
        out[table] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:16])
    return out


def version(c):
    return c.scalar(text("SELECT version_num FROM alembic_version"))


def error_text(exc):
    return f"{type(exc).__name__}: {getattr(exc, 'orig', exc)}"[:160]


def seed_access(scratch):
    with scratch.begin() as c:
        for uid, name in [(2, "admin"), (3, "proc"), (4, "localadmin"), (5, "custom")]:
            c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                           "VALUES (:i,:n,:e,:n,'x',1,0,NOW())"), {"i": uid, "n": name, "e": f"{name}@example.invalid"})
        # Tenant 2 keeps the built-in template; in tenant 1 the admin template was
        # edited before the upgrade, which creates a tenant-local managed copy.
        c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (2,'Sablon',1,NOW())"))
        c.execute(text("INSERT INTO memberships VALUES (2,2,'tenant_admin',1),(2,3,'processor',1),"
                       "(1,4,'tenant_admin',1),(1,5,'reviewer',1)"))
        tenant_perms = sorted(c.execute(text("SELECT code FROM permissions WHERE code NOT LIKE 'system.%' "
                                             "AND code <> 'tenants.read'")).scalars())
        c.execute(text("INSERT INTO access_roles(owner,code,name,permissions,legacy_code,managed,protected) "
                       "VALUES ('tenant:1','tenant_admin','Helyi admin',:p,NULL,1,0)"), {"p": json.dumps(tenant_perms)})
        c.execute(text("INSERT INTO access_roles(owner,code,name,permissions,legacy_code,managed,protected) "
                       "VALUES ('tenant:1','custom_ops','Egyedi',:p,NULL,1,0)"),
                  {"p": json.dumps(["products.read", "imports.read"])})
        custom = c.scalar(text("SELECT id FROM access_roles WHERE code='custom_ops'"))
        c.execute(text("INSERT INTO access_bindings VALUES (5,'tenant:1',:r)"), {"r": custom})
        c.execute(text("INSERT INTO workspace_resource_access(user_id,tenant_id,mode,companies,shops,roles_managed) "
                       "VALUES (5,1,'all','[]','[]',1)"))


def add_approval(scratch):
    with scratch.begin() as c:
        c.execute(text("INSERT INTO product_jobs(id,tenant_id,kind,state,`cursor`,counters,created_at,updated_at) "
                       "VALUES (900,1,'preparation_check','completed',0,'{}',NOW(),NOW())"))
        c.execute(text("INSERT INTO product_selections(id,tenant_id,created_by,token_hash,mode,filters,rule_version,"
                       "created_at,expires_at) VALUES (900,1,2,REPEAT('a',64),'filter','{}','r',NOW(),NOW())"))
        c.execute(text("INSERT INTO preparation_approvals(tenant_id,state,check_id,selection_id,rule_version,"
                       "schema_fingerprint,counts,idempotency_key,request_hash,approved_by,approved_at) "
                       "VALUES (1,'active',900,900,'r',REPEAT('b',64),'{}','k',REPEAT('c',64),2,NOW())"))


def remove_approval(scratch):
    with scratch.begin() as c:
        c.execute(text("DELETE FROM preparation_approvals"))
        c.execute(text("DELETE FROM product_selections"))
        c.execute(text("DELETE FROM product_jobs WHERE id = 900"))


def try_downgrade(cfg, scratch, target):
    try:
        command.downgrade(cfg, target)
        outcome = "succeeded"
    except RuntimeError as exc:
        outcome = "guard: " + str(exc)[:70]
    except Exception as exc:
        outcome = error_text(exc)
    with scratch.connect() as c:
        return {"outcome": outcome, "version": version(c)}


def main():
    scratch, mysql_version = guard(os.environ.get("APP_DATABASE_URL", ""))
    r = {"mysql": mysql_version}
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0008")
    seed_products(scratch, 2000)
    seed_access(scratch)
    with scratch.connect() as c:
        before = fingerprint(c)
    for rev in ["0009", "0010", "0011"]:
        command.upgrade(cfg, rev)
        with scratch.connect() as c:
            r[f"upgrade_{rev}"] = {"version": version(c), "preserved_data_identical": fingerprint(c) == before}
    command.upgrade(cfg, "head")
    with scratch.connect() as c:
        r["rerun_upgrade_head"] = {"version": version(c), "preserved_data_identical": fingerprint(c) == before}
        r["permissions_present"] = sorted(c.execute(
            text("SELECT code FROM permissions WHERE code IN :c").bindparams(bindparam("c", expanding=True)),
            {"c": NEW}).scalars())
        r["role_permissions_rows_for_new_codes"] = c.scalar(
            text("SELECT COUNT(*) FROM role_permissions WHERE permission IN :c").bindparams(
                bindparam("c", expanding=True)), {"c": NEW})
        sysadmin = json.loads(c.scalar(text("SELECT permissions FROM access_roles WHERE code='system_admin'")))
        r["system_admin_role_new_codes"] = sorted(set(NEW) & set(sysadmin))

    from app import access_control as ac
    from app.db import engine
    from app.models import User

    with Session(engine()) as db:
        r["effective_new_permissions"] = {
            label: sorted(set(NEW) & ac.effective(db, db.get(User, uid), tid)[0])
            for uid, tid, label in [(1, 1, "superadmin"), (2, 2, "tenant_admin (built-in template)"),
                                    (3, 2, "processor (built-in template)"),
                                    (4, 1, "tenant_admin (tenant-local copy made before 0009)"),
                                    (5, 1, "custom tenant role")]
        }

    add_approval(scratch)
    r["downgrade_0011_with_approval"] = try_downgrade(cfg, scratch, "0010")
    remove_approval(scratch)
    r["downgrade_0011_without_approval"] = try_downgrade(cfg, scratch, "0010")

    # Interrupted 0011: rebuild an empty 0010 database, make the 4th CREATE TABLE fail.
    with scratch.begin() as c:
        c.execute(text("DROP DATABASE adatdusito_dev"))
        c.execute(text("CREATE DATABASE adatdusito_dev CHARACTER SET utf8mb4"))
    engine.cache_clear()
    scratch.dispose()
    command.upgrade(cfg, "0010")
    with scratch.begin() as c:
        c.execute(text("CREATE TABLE preparation_approvals (id INT PRIMARY KEY)"))
    try:
        command.upgrade(cfg, "0011")
        r["interrupted_0011"] = {"error": None}
    except Exception as exc:
        with scratch.connect() as c:
            cols = {x["name"] for x in inspect(c).get_columns("product_jobs")}
            r["interrupted_0011"] = {
                "error": type(exc).__name__,
                "version": version(c),
                "left_behind_tables": sorted(set(inspect(c).get_table_names()) & {
                    "product_selections", "product_selection_items", "product_operation_items"}),
                "left_behind_product_jobs_columns": sorted(cols & {"created_by", "idempotency_key", "request_hash"}),
            }
    with scratch.begin() as c:
        c.execute(text("DROP TABLE preparation_approvals"))
    try:
        command.upgrade(cfg, "0011")
        r["rerun_0011_after_interruption"] = "succeeded"
    except Exception as exc:
        r["rerun_0011_after_interruption"] = error_text(exc)

    expected = {
        "upgrade/rerun keep data": all(r[k]["preserved_data_identical"] for k in
                                       ["upgrade_0009", "upgrade_0010", "upgrade_0011", "rerun_upgrade_head"]),
        "permissions present": r["permissions_present"] == sorted(NEW),
        "built-in tenant_admin has tenant permissions":
            r["effective_new_permissions"]["tenant_admin (built-in template)"] == TENANT_NEW,
        "other roles need delegation": not any(
            r["effective_new_permissions"][k] for k in ["processor (built-in template)", "custom tenant role"]),
        "0011 downgrade refused with approval": r["downgrade_0011_with_approval"]["outcome"].startswith("guard"),
        "0011 downgrade works without approval": r["downgrade_0011_without_approval"]["outcome"] == "succeeded",
    }
    r["expectations"] = expected
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0 if all(expected.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
