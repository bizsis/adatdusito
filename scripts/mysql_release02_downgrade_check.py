"""RELEASE-02: MySQL 8 regression for the 0009-0011 downgrades (B1 of RELEASE-01).

On a THROWAWAY local MySQL 8 server only: the target must be a loopback host and
an EMPTY database (the script refuses anything else). Never run it on the VPS, a
shared server or pinfo_db. Output: revisions, counts, short hashes and schema
differences only - no row contents, passwords, tokens or secrets.

What it proves, with pre-0009 data present (products, import rows, users,
memberships, access roles):
  1. a reference snapshot is taken on the first upgrade to each level (0008..0011):
     the whole schema from information_schema (tables, columns with type /
     nullability / default, indexes with columns and uniqueness, foreign keys)
     plus a fingerprint of the pre-0009 data and of the permission catalog;
  2. ROUNDS times: the full cycle 0011 -> 0010 -> 0009 -> 0008 -> 0011, then each
     single step down and up again (0011<->0010, 0010<->0009, 0009<->0008); every
     level matches its reference exactly (no partial schema, no leftover index);
  4. decision guards: an approval (0011), a parameter alias (0010) and a category
     map (0009) each make the downgrade refuse, and the schema and data stay
     unchanged.

Exit code 0 only if every check passes.

    export APP_DATABASE_URL='mysql+pymysql://USER:PASS@127.0.0.1:PORT/adatdusito_dev'
    cd backend && PYTHONPATH=. python ../scripts/mysql_release02_downgrade_check.py [--rounds 3]
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, make_url, text  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
LEVELS = ["0008", "0009", "0010", "0011"]
PRESERVED = {
    "users": "id,username,email,active,superadmin",
    "tenants": "id,name,active",
    "memberships": "tenant_id,user_id,role,active",
    "access_roles": "id,owner,code,permissions,managed,protected",
    "role_permissions": "role,permission",
    "permissions": "code",
    "supplier_products": "id,tenant_id,supplier_id,identity_key,data,last_run_id,last_line",
    "import_rows": "run_id,line,raw,normalized,state,product_id",
    "import_runs": "id,tenant_id,state,cursor",
}


def guard(url):
    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql" or parsed.host not in LOOPBACK:
        sys.exit("Refusing: APP_DATABASE_URL must be a MySQL server on a loopback host.")
    scratch = create_engine(url)
    with scratch.connect() as c:
        if inspect(c).get_table_names():
            sys.exit("Refusing: the target database is not empty; use a throwaway server.")
        return scratch, c.scalar(text("SELECT VERSION()"))


def seed(scratch, n=2000):
    """Pre-0009 data: tenant, supplier, completed import run, products, import rows, roles."""
    with scratch.begin() as c:
        c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                       "VALUES (1,'root','root@example.invalid','Root','x',1,1,NOW()),"
                       "(2,'admin','admin@example.invalid','Admin','x',1,0,NOW())"))
        c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Mérés',1,NOW())"))
        c.execute(text("INSERT INTO memberships VALUES (1,2,'tenant_admin',1)"))
        c.execute(text("INSERT INTO access_roles(owner,code,name,permissions,legacy_code,managed,protected) "
                       "VALUES ('tenant:1','custom_ops','Egyedi','[\"products.read\"]',NULL,1,0)"))
        c.execute(text("INSERT INTO import_suppliers(id,tenant_id,name) VALUES (1,1,'Mérés')"))
        cols = {col["name"]: col for col in inspect(c).get_columns("import_runs")}
        values = {"id": 1, "tenant_id": 1, "supplier_id": 1, "filename": "seed.csv", "state": "completed",
                  "config": json.dumps({"mapping": {"0": "sku", "1": "name", "2": "category"}}),
                  "analysis": json.dumps({"headers": ["SKU", "NAME", "CATEGORY"]}), "cursor": n,
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
                  [{"id": i, "line": i + 1, "raw": json.dumps([f"SKU-{i:08d}", f"Termék {i}", "A > B"],
                                                             ensure_ascii=False)} for i in range(1, n + 1)])


def schema(c):
    db = c.scalar(text("SELECT DATABASE()"))
    q = lambda sql: [tuple(r) for r in c.execute(text(sql), {"db": db}).all()]  # noqa: E731
    return {
        "columns": q("SELECT table_name, column_name, column_type, is_nullable, column_default, extra "
                     "FROM information_schema.columns WHERE table_schema=:db ORDER BY 1, 2"),
        "indexes": q("SELECT table_name, index_name, non_unique, "
                     "GROUP_CONCAT(column_name ORDER BY seq_in_index) FROM information_schema.statistics "
                     "WHERE table_schema=:db GROUP BY table_name, index_name, non_unique ORDER BY 1, 2"),
        "foreign_keys": q("SELECT k.table_name, k.constraint_name, "
                          "GROUP_CONCAT(k.column_name ORDER BY k.ordinal_position), k.referenced_table_name, "
                          "GROUP_CONCAT(k.referenced_column_name ORDER BY k.ordinal_position) "
                          "FROM information_schema.key_column_usage k WHERE k.table_schema=:db "
                          "AND k.referenced_table_name IS NOT NULL "
                          "GROUP BY k.table_name, k.constraint_name, k.referenced_table_name ORDER BY 1, 2"),
        "foreign_key_rules": q("SELECT table_name, constraint_name, update_rule, delete_rule "
                               "FROM information_schema.referential_constraints WHERE constraint_schema=:db "
                               "ORDER BY 1, 2"),
    }


def data(c):
    out = {}
    for table, cols in PRESERVED.items():
        q = ",".join(f"`{x}`" for x in cols.split(","))
        rows = c.execute(text(f"SELECT {q} FROM {table} ORDER BY {q}")).all()
        out[table] = [len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:16]]
    return out


def snapshot(scratch):
    with scratch.connect() as c:
        return {"version": c.scalar(text("SELECT version_num FROM alembic_version")),
                "schema": schema(c), "data": data(c)}


def diff(ref, cur):
    """Short, content-free description of the difference (empty when identical)."""
    out = []
    if ref["version"] != cur["version"]:
        out.append(f"version {ref['version']} != {cur['version']}")
    for part in ["columns", "indexes", "foreign_keys", "foreign_key_rules"]:
        a, b = set(ref["schema"][part]), set(cur["schema"][part])
        out += [f"{part} missing: {x[:2]}" for x in sorted(a - b)][:5]
        out += [f"{part} extra: {x[:2]}" for x in sorted(b - a)][:5]
    for table, value in ref["data"].items():
        if cur["data"].get(table) != value:
            out.append(f"data {table}: {value[0]} rows -> {cur['data'].get(table, [None])[0]} rows / hash changed")
    return out


class Run:
    def __init__(self, cfg, scratch):
        self.cfg, self.scratch, self.ref, self.checks = cfg, scratch, {}, []

    def check(self, label, level):
        cur = snapshot(self.scratch)
        problems = diff(self.ref[level], cur) if level in self.ref else []
        if level not in self.ref:
            self.ref[level] = cur
        self.checks.append({"step": label, "version": cur["version"], "ok": not problems, "problems": problems})
        print(f"{'OK ' if not problems else 'ERR'} {label:<38} -> {cur['version']}"
              + ("" if not problems else "  " + "; ".join(problems)), flush=True)

    def move(self, target, label=None):
        current = snapshot(self.scratch)["version"]
        step = command.upgrade if LEVELS.index(target) > LEVELS.index(current) else command.downgrade
        try:
            step(self.cfg, target)
        except Exception as exc:  # recorded, then the snapshot shows the damage
            self.checks.append({"step": label or f"{current}->{target}", "ok": False,
                                "problems": [f"{type(exc).__name__}: {getattr(exc, 'orig', exc)}"[:200]]})
            print(f"ERR {label or current + '->' + target}: {self.checks[-1]['problems'][0]}", flush=True)
        self.check(label or f"{current} -> {target}", target)

    def guarded(self, level, insert, cleanup, label):
        """A decision exists: the downgrade must refuse and leave schema and data unchanged."""
        with self.scratch.begin() as c:
            for sql in insert:
                c.execute(text(sql))
        before = snapshot(self.scratch)
        target = LEVELS[LEVELS.index(level) - 1]
        try:
            command.downgrade(self.cfg, target)
            outcome, problems = "NOT refused", ["downgrade was not refused"]
        except RuntimeError as exc:
            outcome, problems = "refused", []
            if "backup" not in str(exc):
                problems.append("unexpected guard message")
        except Exception as exc:
            outcome, problems = "error", [f"{type(exc).__name__}: {getattr(exc, 'orig', exc)}"[:200]]
        problems += diff(before, snapshot(self.scratch))
        with self.scratch.begin() as c:
            for sql in cleanup:
                c.execute(text(sql))
        self.checks.append({"step": label, "ok": not problems, "outcome": outcome, "problems": problems})
        print(f"{'OK ' if not problems else 'ERR'} {label:<38} {outcome}"
              + ("" if not problems else "  " + "; ".join(problems)), flush=True)
        self.check(f"after {label} cleanup", level)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--migrations", type=Path, default=BACKEND / "migrations",
                        help="Alembic script directory (default: backend/migrations); the CI negative "
                             "control points this at a copy with a deliberately broken downgrade")
    args = parser.parse_args(argv)
    scratch, mysql_version = guard(os.environ.get("APP_DATABASE_URL", ""))
    print(f"MySQL {mysql_version}", flush=True)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(args.migrations.resolve()))
    started = time.monotonic()
    command.upgrade(cfg, "0008")
    seed(scratch)
    run = Run(cfg, scratch)
    run.check("seeded 0008 (reference)", "0008")
    for level in ["0009", "0010", "0011"]:
        run.move(level, f"first upgrade -> {level} (reference)")
    for i in range(1, args.rounds + 1):
        for level in ["0010", "0009", "0008", "0011"]:
            run.move(level, f"round {i}: -> {level}")
        for upper, lower in [("0011", "0010"), ("0010", "0009"), ("0009", "0008")]:
            run.move(upper, f"round {i} step: -> {upper}")
            run.move(lower, f"round {i} step: {upper} -> {lower}")
            run.move(upper, f"round {i} step: {lower} -> {upper}")
        run.move("0011", f"round {i}: back to head")
    run.guarded("0011", [
        "INSERT INTO product_jobs(id,tenant_id,kind,state,`cursor`,counters,created_at,updated_at) "
        "VALUES (900,1,'preparation_check','completed',0,'{}',NOW(),NOW())",
        "INSERT INTO product_selections(id,tenant_id,created_by,token_hash,mode,filters,rule_version,created_at,"
        "expires_at) VALUES (900,1,2,REPEAT('a',64),'filter','{}','r',NOW(),NOW())",
        "INSERT INTO preparation_approvals(tenant_id,state,check_id,selection_id,rule_version,schema_fingerprint,"
        "counts,idempotency_key,request_hash,approved_by,approved_at) "
        "VALUES (1,'active',900,900,'r',REPEAT('b',64),'{}','k',REPEAT('c',64),2,NOW())",
    ], ["DELETE FROM preparation_approvals", "DELETE FROM product_selections",
        "DELETE FROM product_jobs WHERE id = 900"], "guard 0011: preparation approval")
    run.move("0010", "down to 0010 for the next guard")
    run.guarded("0010", [
        "INSERT INTO parameter_aliases(tenant_id,active_key,label,label_key,unit,emag_parameter_id,"
        "scope_emag_category_id,state,version,created_by,created_at,decided_by,decided_at) "
        "VALUES (1,'k','Zaj','zaj','',1,1,'approved',1,2,NOW(),2,NOW())",
    ], ["DELETE FROM parameter_aliases"], "guard 0010: parameter alias")
    run.move("0009", "down to 0009 for the next guard")
    run.guarded("0009", [
        "INSERT INTO product_source_categories(id,tenant_id,supplier_id,origin,path_key,path_text,created_at) "
        "VALUES (900,1,1,'supplier',REPEAT('d',64),'A > B',NOW())",
        "INSERT INTO category_maps(source_category_id,tenant_id,state,revision,decided_by,decided_at) "
        "VALUES (900,1,'mapped',1,2,NOW())",
    ], ["DELETE FROM category_maps", "DELETE FROM product_source_categories"], "guard 0009: category map")
    run.move("0008", "final -> 0008")
    run.move("0011", "final -> 0011")
    failed = [c for c in run.checks if not c["ok"]]
    # Content-free schema fingerprint per level (reference snapshots), for CI logs.
    schema_fingerprints = {
        level: hashlib.sha256(json.dumps(snap["schema"], sort_keys=True, default=str).encode()).hexdigest()[:16]
        for level, snap in sorted(run.ref.items())
    }
    print(json.dumps({"mysql": mysql_version, "rounds": args.rounds, "checks": len(run.checks),
                      "failed": len(failed), "seconds": round(time.monotonic() - started, 1),
                      "schema_fingerprints": schema_fingerprints}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
