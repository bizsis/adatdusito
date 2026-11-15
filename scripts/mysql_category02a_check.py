"""CATEGORY-02C: reproducible MySQL 8 measurement of the CATEGORY-02A risks.

Measures, on a THROWAWAY local MySQL 8 server only:
  1. alembic 0008 -> 0009 on N existing products (through app.db.engine(),
     i.e. with the production connect/read/write timeouts),
  2. the resumable backfill (python -m app.product_backfill equivalent),
  3. one category-map decision on a single own category holding all N
     products (synchronous path or background job, as the API decides),
  4. the product list with status counts and the server-side search q,
  5. the guarded downgrade (must refuse once decisions exist).

The numbers are measurements of one machine, not guarantees.

Safety: refuses unless APP_DATABASE_URL points to a loopback host and the
database is completely empty (no tables). Never run it on the VPS, on the
shared development database or on pinfo_db (AGENTS.md rules 8 and 9).

    # throwaway server, e.g. docker run --rm -d -p 127.0.0.1:33306:3306 \
    #   -e MYSQL_ROOT_PASSWORD=scratch -e MYSQL_DATABASE=adatdusito_dev mysql:8.0
    export APP_DATABASE_URL='mysql+pymysql://root:scratch@127.0.0.1:33306/adatdusito_dev'
    cd backend && PYTHONPATH=. python ../scripts/mysql_category02a_check.py --products 50000
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
CATEGORY = "Háztartás > Gépek > Mosó-szárítógépek ellenőrzés"


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
    except Exception as exc:  # report, do not hide
        results[label] = {"seconds": round(time.perf_counter() - start, 2), "ok": False,
                          "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        raise


def seed(scratch, n, chunk=5000):
    headers = ["SKU", "NAME", "CATEGORY", "Teljesítmény (W)", "Szín", "Garancia"]
    with scratch.begin() as c:
        c.execute(text("INSERT INTO users(id,username,email,name,password_hash,active,superadmin,created_at) "
                       "VALUES (1,'root','root@example.invalid','Root','x',1,1,NOW())"))
        c.execute(text("INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Mérés',1,NOW())"))
        c.execute(text("INSERT INTO import_suppliers(id,tenant_id,name) VALUES (1,1,'Mérés')"))
        cols = {col["name"]: col for col in inspect(c).get_columns("import_runs")}
        values = {"id": 1, "tenant_id": 1, "supplier_id": 1, "filename": "seed.csv", "state": "completed",
                  "config": json.dumps({"mapping": {"0": "sku", "1": "name", "2": "category"}}),
                  "analysis": json.dumps({"headers": headers}), "cursor": n, "counters": "{}",
                  "created_at": "2026-11-01 10:00:00", "updated_at": "2026-11-01 10:00:00"}
        for extra, col in cols.items():
            if extra not in values and not col["nullable"] and col.get("default") is None:
                values[extra] = 1 if extra.endswith(("_by", "_id")) else "x"
        c.execute(text(f"INSERT INTO import_runs({','.join('`' + k + '`' for k in values)}) VALUES ({','.join(':' + k for k in values)})"),
                  values)
    for start in range(0, n, chunk):
        ids = range(start + 1, min(n, start + chunk) + 1)
        with scratch.begin() as c:
            c.execute(text("INSERT INTO supplier_products(id,tenant_id,supplier_id,identity_key,data,last_run_id,last_line) "
                           "VALUES (:id,1,1,:k,:data,1,:line)"),
                      [{"id": i, "k": f"k{i:08d}", "line": i + 1,
                        "data": json.dumps({"sku": f"SKU-{i:08d}", "name": f"Mosó-szárítógép {i}",
                                            "category": CATEGORY}, ensure_ascii=False)} for i in ids])
            c.execute(text("INSERT INTO import_rows(run_id,line,raw,normalized,issues,state,product_id) "
                           "VALUES (1,:line,:raw,'{}','[]','imported',:id)"),
                      [{"id": i, "line": i + 1,
                        "raw": json.dumps([f"SKU-{i:08d}", f"Mosó-szárítógép {i}", CATEGORY, "2100", "Fehér", "2 év"],
                                          ensure_ascii=False)} for i in ids])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=int, default=50_000)
    args = parser.parse_args(argv)
    url = os.environ.get("APP_DATABASE_URL", "")
    scratch, version = guard(url)
    results = {"mysql_version": version, "products": args.products}
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))

    timed("alembic_upgrade_0008", results, lambda: command.upgrade(cfg, "0008"))
    timed("seed", results, lambda: seed(scratch, args.products))
    timed("alembic_upgrade_0009", results, lambda: command.upgrade(cfg, "0009"))

    from app import product_backfill, product_jobs, workspace_views
    from app.db import engine
    from app.product_models import CategoryMap, ProductJob, ProductSourceCategory

    def backfill():
        with Session(engine()) as db:
            return product_backfill.run(db, batch=500)

    results["backfill_result"] = timed("backfill", results, backfill)

    who = SimpleNamespace(full_resources=True, session=SimpleNamespace(tenant_id=1),
                          user=SimpleNamespace(id=1))

    def decide_map():
        with Session(engine()) as db:
            source = db.query(ProductSourceCategory).one()
            sent = []
            product_jobs.enqueue, original = sent.append, product_jobs.enqueue
            try:
                body = workspace_views.CategoryMapInput(
                    expected_revision=None, state="approved", navigation_node_id="web-item-114-3490")
                start = time.perf_counter()
                response = workspace_views.put_category_map(source.id, body, who=who, db=db)
                request = round(time.perf_counter() - start, 2)
            finally:
                product_jobs.enqueue = original
            job = None
            if sent:
                start = time.perf_counter()
                state = product_jobs.advance(db, sent[0])
                job = {"state": state, "seconds": round(time.perf_counter() - start, 2),
                       **product_jobs.job_dto(db.get(ProductJob, sent[0]))}
            return {"request_seconds": request, "reapply": response["reapply"], "job": job}

    results["category_map"] = timed("category_map", results, decide_map)

    def listing(q=None):
        with Session(engine()) as db:
            body = workspace_views.products(
                cursor=0, limit=25, status=None, origin=None, locked=None, supplier_id=None,
                source_category_id=None, without_source_category=False, navigation_node_id=None,
                q=q, who=who, db=db)
            return body["status_counts"]

    results["list_counts"] = timed("product_list", results, listing)
    results["search_counts"] = timed("product_search_q", results, lambda: listing("szárítógép 999"))

    def downgrade_guard():
        try:
            command.downgrade(cfg, "0008")
        except RuntimeError as exc:
            return {"refused": True, "message": str(exc)}
        return {"refused": False}

    results["downgrade"] = timed("downgrade_guard", results, downgrade_guard)
    with Session(engine()) as db:
        results["category_maps"] = db.query(CategoryMap).count()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(v.get("ok", True) for v in results.values() if isinstance(v, dict) and "seconds" in v)
    return 0 if ok and results["downgrade"]["refused"] else 1


if __name__ == "__main__":
    sys.exit(main())
