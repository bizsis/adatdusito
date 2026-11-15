"""CATEGORY-03A: reproducible MySQL 8 measurement of the parameter-slot run.

Measures on a THROWAWAY local MySQL 8 server only:
  1. alembic upgrade to head (0010) through app.db.engine() (production timeouts),
  2. a parameter run in apply mode over N classified products (≤ 50 000 per run),
  3. the same run again (idempotency: nothing may change),
  4. the paginated parameter diff (plain, state filter, mandatory-missing filter),
  5. the guarded 0010 downgrade once a manual decision exists.

Numbers are measurements of one machine, not guarantees.

Safety: refuses unless APP_DATABASE_URL points to a loopback host and the
database is empty. Never run it on the VPS, the shared development database
or pinfo_db (AGENTS.md rules 8 and 9).

    export APP_DATABASE_URL='mysql+pymysql://root:scratch@127.0.0.1:33306/adatdusito_dev'
    cd backend && PYTHONPATH=. python ../scripts/mysql_category03a_check.py --products 50000
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, make_url, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
NODE, DONOR = "web-item-114-3490", 385  # Elöltöltős mosógépek -> Mosógépek (reviewed)
COMMON = 1_000_000_000
PARAMS = [  # (emag_parameter_id, name, mandatory, allow_new_value, value count)
    (6506, "Teljesítmény (W)", 1, 1, 0), (6507, "Szín", 0, 0, 40), (6508, "Kapacitás (kg)", 1, 1, 0),
    (6509, "Energiaosztály", 1, 0, 10), (6510, "Zajszint (dB)", 0, 1, 0), (6511, "Szélesség (cm)", 0, 1, 0),
] + [(7000 + i, f"Egyéb jellemző {i}", i % 3 == 0, 1, 0) for i in range(24)]
HEADERS = ["SKU", "NAME", "CATEGORY", "Teljesítmény (kW)", "Szín", "Kapacitás (kg)", "Zajszint",
           "Szélesség (mm)", "Garancia"]


def guard(url):
    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql" or parsed.host not in LOOPBACK:
        sys.exit("Refusing: APP_DATABASE_URL must be a MySQL server on a loopback host.")
    scratch = create_engine(url)
    with scratch.connect() as c:
        if inspect(c).get_table_names():
            sys.exit("Refusing: the target database is not empty; use a throwaway server.")
        version = c.scalar(text("SELECT VERSION()"))
    return scratch, version


def timed(label, results, fn):
    start = time.perf_counter()
    try:
        value = fn()
        results[label] = {"seconds": round(time.perf_counter() - start, 2), "ok": True}
        return value
    except Exception as exc:
        results[label] = {"seconds": round(time.perf_counter() - start, 2), "ok": False,
                          "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        raise


def seed(scratch, n, chunk=5000):
    with scratch.begin() as c:
        c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                       "VALUES (1,'root','root@example.invalid','Root','x',1,1,NOW())"))
        c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Mérés',1,NOW())"))
        c.execute(text("INSERT INTO import_suppliers(id,tenant_id,name) VALUES (1,1,'Mérés')"))
        cols = {col["name"]: col for col in inspect(c).get_columns("import_runs")}
        values = {"id": 1, "tenant_id": 1, "supplier_id": 1, "filename": "seed.csv", "state": "completed",
                  "config": "{}", "analysis": json.dumps({"headers": HEADERS}), "cursor": n, "counters": "{}",
                  "created_at": "2026-11-01 10:00:00", "updated_at": "2026-11-01 10:00:00"}
        for extra, col in cols.items():
            if extra not in values and not col["nullable"] and col.get("default") is None:
                values[extra] = 1 if extra.endswith(("_by", "_id")) else "x"
        c.execute(text(f"INSERT INTO import_runs({','.join('`' + k + '`' for k in values)}) "
                       f"VALUES ({','.join(':' + k for k in values)})"), values)
        c.execute(text("INSERT INTO product_source_categories(id,tenant_id,supplier_id,origin,path_key,path_text,"
                       "created_at) VALUES (1,1,1,'supplier','k','Gépek',NOW())"))
        # Owned catalog: one ready, verified version with the donor's parameters.
        c.execute(text("INSERT INTO catalog_versions(id,source_key,status,phase,`cursor`,source_state,counters,"
                       "verification,created_at,updated_at) VALUES (1,'emag_marketplace','ready','done',0,'{}',"
                       "'{}','{\"complete\": true}',NOW(),NOW())"))
        c.execute(text("INSERT INTO system_settings(`key`,value) VALUES ('reference_catalog_active','1')"))
        c.execute(text("INSERT INTO catalog_categories(id,`key`,name) VALUES (:id,:k,'Mosógépek')"),
                  {"id": COMMON + 1, "k": f"emag_marketplace:category:{DONOR}"})
        value_id = COMMON + 100_000
        for order, (emag_id, name, mandatory, allow, count) in enumerate(PARAMS):
            link = COMMON + 1000 + order
            c.execute(text("INSERT INTO catalog_parameters(id,`key`,name,type_id) VALUES (:i,:k,:n,1)"),
                      {"i": link, "k": f"p{link}", "n": name})
            c.execute(text("INSERT INTO catalog_category_parameters(id,`key`) VALUES (:i,:k)"),
                      {"i": link, "k": f"l{link}"})
            c.execute(text("INSERT INTO catalog_category_parameter_entries(version_id,link_id,category_id,"
                           "parameter_id,name,emag_parameter_id,display_order,is_mandatory,is_filter,"
                           "allow_new_value) VALUES (1,:l,:c,:l,:n,:e,:o,:m,0,:a)"),
                      {"l": link, "c": COMMON + 1, "n": name, "e": emag_id, "o": order, "m": mandatory, "a": allow})
            texts = ["Fehér", "Fekete"] + [f"Szín {i}" for i in range(count - 2)] if emag_id == 6507 else \
                [chr(65 + i) for i in range(count)]
            for t in texts:
                value_id += 1
                c.execute(text("INSERT INTO catalog_parameter_values(id,`key`,parameter_id,value_text) "
                               "VALUES (:i,:k,:p,:t)"), {"i": value_id, "k": f"v{value_id}", "p": link, "t": t})
                c.execute(text("INSERT INTO catalog_source_mappings(version_id,kind,source_key,source_id,target_id,"
                               "context_id,payload_sha256) VALUES (1,'value','emag_marketplace',:i,:i,:l,'x')"),
                          {"i": value_id, "l": link})
    for start in range(0, n, chunk):
        ids = range(start + 1, min(n, start + chunk) + 1)
        with scratch.begin() as c:
            products, classes = [], []
            for i in ids:
                attrs = {h: {"raw": v, "column": col, "run_id": 1, "line": i + 1, "present": True}
                         for col, (h, v) in enumerate(zip(HEADERS[3:], [
                             f"{1 + i % 3},{i % 10}", "fehér" if i % 2 else "fekete", str(6 + i % 4),
                             str(48 + i % 8), "600", "2 év"]), start=3)}
                products.append({"id": i, "k": f"k{i:08d}", "line": i + 1, "attrs": json.dumps(attrs, ensure_ascii=False),
                                 "data": json.dumps({"sku": f"SKU-{i:08d}", "name": f"Mosógép {i}",
                                                     "category": "Gépek"}, ensure_ascii=False),
                                 "st": f"mosogep {i}\tsku-{i:08d}\t"})
                classes.append({"id": i})
            c.execute(text("INSERT INTO supplier_products(id,tenant_id,supplier_id,identity_key,data,last_run_id,"
                           "last_line,revision,source_category_id,source_attributes,search_text) VALUES "
                           "(:id,1,1,:k,:data,1,:line,1,1,:attrs,:st)"), products)
            c.execute(text("INSERT INTO product_classifications(product_id,tenant_id,status,origin,method,"
                           "rule_version,reason_codes,navigation_node_id,donor_emag_category_id,alternatives,"
                           f"locked,decided_at) VALUES (:id,1,'auto_classified','category_map','category_map',"
                           f"'category-02a.1','[]','{NODE}',{DONOR},'[]',0,NOW())"), classes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=int, default=50_000)
    args = parser.parse_args(argv)
    scratch, version = guard(os.environ.get("APP_DATABASE_URL", ""))
    results = {"mysql_version": version, "products": args.products, "donor_parameters": len(PARAMS)}
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    timed("alembic_upgrade_head", results, lambda: command.upgrade(cfg, "head"))
    timed("seed", results, lambda: seed(scratch, args.products))

    from app import parameter_views, product_jobs
    from app.db import engine
    from app.product_models import ProductJob

    def parameter_run():
        with Session(engine()) as db:
            job = product_jobs.create_parameter_job(db, 1, "apply", {"source_category_id": None,
                                                                    "navigation_node_id": None,
                                                                    "supplier_id": None}, 0)
            db.commit()
            job_id = job.id
            state = product_jobs.advance_parameters(db, job_id)
            return {"state": state, **product_jobs.parameter_job_dto(db.get(ProductJob, job_id))}

    results["first_run"] = timed("parameter_run_apply", results, parameter_run)
    results["second_run"] = timed("parameter_run_idempotent", results, parameter_run)
    who = SimpleNamespace(full_resources=True, session=SimpleNamespace(tenant_id=1),
                          user=SimpleNamespace(id=1), permissions={"products.read"})

    def diff(**filters):
        with Session(engine()) as db:
            args = dict(cursor=0, limit=25, state=None, mandatory_missing=None, navigation_node_id=None,
                        source_category_id=None, supplier_id=None, parameter_profile_state=None, q=None)
            args.update(filters)
            return len(parameter_views.parameter_diff(**args, who=who, db=db)["items"])

    results["diff_items"] = timed("diff_page", results, diff)
    results["diff_review_items"] = timed("diff_state_review", results, lambda: diff(state="review"))
    results["diff_mandatory_items"] = timed("diff_mandatory_missing", results, lambda: diff(mandatory_missing=True))
    results["diff_ready_items"] = timed("diff_profile_ready", results, lambda: diff(parameter_profile_state="ready"))
    with scratch.begin() as c:
        c.execute(text("UPDATE product_parameter_values SET locked=1, origin='user' "
                       "WHERE product_id=1 AND slot_key='emag:6506'"))
        results["slot_rows"] = c.scalar(text("SELECT COUNT(*) FROM product_parameter_values"))

    def downgrade_guard():
        try:
            command.downgrade(cfg, "0009")
        except RuntimeError as exc:
            return {"refused": True, "message": str(exc)}
        return {"refused": False}

    results["downgrade"] = timed("downgrade_guard", results, downgrade_guard)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(v.get("ok", True) for v in results.values() if isinstance(v, dict) and "seconds" in v)
    return 0 if ok and results["downgrade"]["refused"] and results["second_run"]["products_changed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
