"""CATEGORY-03C: reproducible MySQL 8 measurement of bulk preview/apply and approval.

On a THROWAWAY local MySQL 8 server only (same guard as the 03A script):
  1. alembic upgrade to head (0011) with the production engine timeouts,
  2. N classified products (default 60 000: more than one 50 000-product run),
  3. selection snapshot of the full set,
  4. bulk preview (several runs), bulk apply, idempotent replay, retry run,
  5. preparation check and approval creation, revalidation, revoke,
  6. the guarded 0011 downgrade.

Numbers are measurements of one machine, not guarantees.

    export APP_DATABASE_URL='mysql+pymysql://root:scratch@127.0.0.1:33306/adatdusito_dev'
    cd backend && PYTHONPATH=. python ../scripts/mysql_category03c_check.py --products 60000
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("m03a", SCRIPTS / "mysql_category03a_check.py")
m03a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m03a)  # guard, seed, timed, BACKEND on sys.path

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

PERMISSIONS = {"products.read", "products.parameters", "products.bulk", "products.prepare.approve"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=int, default=60_000)
    args = parser.parse_args(argv)
    scratch, version = m03a.guard(os.environ.get("APP_DATABASE_URL", ""))
    results = {"mysql_version": version, "products": args.products}
    timed = m03a.timed
    cfg = Config(str(m03a.BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(m03a.BACKEND / "migrations"))
    timed("alembic_upgrade_head", results, lambda: command.upgrade(cfg, "head"))
    timed("seed", results, lambda: m03a.seed(scratch, args.products))
    with scratch.begin() as c:
        # Two thirds of the products lose the unit-less "Zajszint" column, so the
        # preparation check has both approvable and blocked (unit_conflict) items.
        c.execute(text("UPDATE supplier_products SET source_attributes = "
                       "JSON_REMOVE(source_attributes, '$.\"Zajszint\"') WHERE id % 3 <> 0"))

    from app import bulk_operations as bo
    from app import bulk_views
    from app import product_parameters as pp
    from app.db import engine
    from app.product_models import ProductJob

    who = SimpleNamespace(full_resources=True, session=SimpleNamespace(tenant_id=1),
                          user=SimpleNamespace(id=1), permissions=PERMISSIONS)
    state = {}

    def run_job(job_id):
        runs = 0
        with Session(engine()) as db:
            while (s := bo.advance(db, job_id)) == "pending":
                runs += 1
            return {"state": s, "advance_calls": runs + 1,
                    **bo.operation_dto(db.get(ProductJob, job_id))}

    def selection():
        with Session(engine()) as db:
            sel = bulk_views.create_selection(bulk_views.SelectionInput(filters=bulk_views.Filters()), who=who, db=db)
            state["selection"] = sel
            return sel["total"]

    results["selection_total"] = timed("selection_snapshot", results, selection)
    bo.enqueue = lambda job_id: None  # the measurement drives the jobs itself

    def preview():
        with Session(engine()) as db:
            body = bulk_views.create_preview(bulk_views.TokenInput(
                selection_token=state["selection"]["selection_token"]), who=who, db=db)
        state["preview"] = body
        return run_job(body["preview"]["id"])

    results["preview"] = timed("bulk_preview", results, preview)

    def apply(key):
        with Session(engine()) as db:
            eligible = results["preview"]["outcomes"].get("eligible", 0)
            body = bulk_views.apply_preview(state["preview"]["preview"]["id"], bulk_views.ApplyInput(
                preview_token=state["preview"]["preview_token"], confirm=True, expected_eligible=eligible,
                idempotency_key=key), who=who, db=db)
        if body.get("replayed"):
            return {"replayed": True, "id": body["apply"]["id"]}
        return run_job(body["apply"]["id"])

    request = time.perf_counter()
    results["apply"] = timed("bulk_apply", results, lambda: apply("measure-apply-1"))
    results["apply_replay"] = timed("bulk_apply_replay", results, lambda: apply("measure-apply-1"))
    results["apply_retry"] = timed("bulk_apply_retry_nothing_left", results, lambda: apply("measure-apply-2"))
    results["apply_wall_seconds"] = round(time.perf_counter() - request, 2)

    def check():
        with Session(engine()) as db:
            sel = bulk_views.create_selection(bulk_views.SelectionInput(filters=bulk_views.Filters()), who=who, db=db)
            body = bulk_views.create_check(bulk_views.TokenInput(selection_token=sel["selection_token"]),
                                           who=who, db=db)
        state["check"] = body
        return run_job(body["check"]["id"])

    results["check"] = timed("preparation_check", results, check)

    def approve():
        with Session(engine()) as db:
            return bulk_views.approve(bulk_views.ApprovalInput(
                check_id=state["check"]["check"]["id"], check_token=state["check"]["check_token"], confirm=True,
                expected_approvable=results["check"]["outcomes"].get("approvable", 0),
                idempotency_key="measure-approval-1"), who=who, db=db)

    if results["check"]["outcomes"].get("approvable"):
        results["approval"] = timed("preparation_approve", results, approve)
        with Session(engine()) as db:
            results["approval_detail"] = timed("approval_detail_live_validity", results,
                                               lambda: bulk_views.approval(results["approval"]["id"], who=who, db=db))
            timed("approval_revalidate", results, lambda: bulk_views.revalidate(results["approval"]["id"],
                                                                                 who=who, db=db))
    results["rule_version"] = pp.RULE_VERSION

    def downgrade_guard():
        try:
            command.downgrade(cfg, "0010")
        except RuntimeError as exc:
            return {"refused": True, "message": str(exc)}
        return {"refused": False}

    results["downgrade"] = timed("downgrade_guard", results, downgrade_guard)
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    ok = all(v.get("ok", True) for v in results.values() if isinstance(v, dict) and "seconds" in v)
    return 0 if ok and results["apply"]["source_overwrites"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
