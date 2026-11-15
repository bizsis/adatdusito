"""CATEGORY-02A backfill for products imported before migration 0009.

Resumable and idempotent: a leased ProductJob keeps the last processed product
id, so a stopped run continues where it left off and a finished run is a no-op.
For each product it fills only what is missing:
* source_attributes from the product's last import row (raw cells + run headers
  and mapping). If that row no longer exists, nothing is invented.
* source_category_id from data["category"] (text kept verbatim).
* search_text (folded name/SKU/GTIN) for server-side search.
* an initial classification (automatic decision rules; locked rows untouched).

Run (inside the backend container or venv):
    python -m app.product_backfill [--batch 500]
"""

import argparse
import secrets
import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app.import_models import ImportRow, ImportRun, SupplierProduct
from app.models import now
from app.product_models import ProductClassification, ProductJob

KIND = "backfill_category_02a"


def claim(db):
    job = db.scalar(select(ProductJob).where(ProductJob.kind == KIND).with_for_update())
    if job is None:
        job = ProductJob(kind=KIND, state="pending", cursor=0, counters={})
        db.add(job)
        db.flush()
    if job.state == "completed":
        db.commit()
        return None, None
    if job.lease_until and job.lease_until > now():
        db.rollback()
        raise RuntimeError("A backfill már fut (érvényes bérlet).")
    token = secrets.token_hex(16)
    job.state, job.task_token = "running", token
    job.lease_until = now() + timedelta(minutes=5)
    db.commit()
    return job.id, token


def fill(db, product, runs, category_cache, maps, threshold, counters):
    changed = False
    if product.source_attributes is None:
        row = db.get(ImportRow, (product.last_run_id, product.last_line))
        run = runs.get(product.last_run_id) or db.get(ImportRun, product.last_run_id)
        runs[product.last_run_id] = run
        if row is not None and run is not None and run.analysis and run.analysis.get("headers"):
            mapped = {int(c) for c in (run.config or {}).get("mapping", {})}
            product.source_attributes = pc.source_attributes(
                run.analysis["headers"], row.raw, mapped, run.id, row.line
            )
            counters["attributes_filled"] = counters.get("attributes_filled", 0) + 1
            changed = True
        else:
            counters["source_row_unavailable"] = counters.get("source_row_unavailable", 0) + 1
    text = product.data.get("category")
    if product.source_category_id is None and text not in (None, ""):
        product.source_category_id = pc.source_category_id(
            db, category_cache, product.tenant_id, product.supplier_id, str(text)
        )
        counters["source_category_linked"] = counters.get("source_category_linked", 0) + 1
        changed = True
    if product.search_text is None:
        product.search_text = pc.search_text(product.data)
        counters["search_text_filled"] = counters.get("search_text_filled", 0) + 1
    if changed:
        product.revision = (product.revision or 1) + 1
    if db.get(ProductClassification, product.id) is None:
        db.flush()
        pc.classify(db, product, maps.setdefault(product.tenant_id, pc.maps_for(db, product.tenant_id)),
                    threshold, str(text or ""), record_event=False)
        counters["classified"] = counters.get("classified", 0) + 1


def run(db: Session, batch=500, max_batches=None):
    job_id, token = claim(db)
    if job_id is None:
        return {"state": "completed", "message": "already completed"}
    threshold = pc.auto_threshold(db)
    runs, category_cache, maps = {}, {}, {}
    done = 0
    while max_batches is None or done < max_batches:
        job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
        if job.task_token != token:
            return {"state": "lost_lease"}
        products = list(
            db.scalars(
                select(SupplierProduct).where(SupplierProduct.id > job.cursor).order_by(SupplierProduct.id).limit(batch)
            )
        )
        if not products:
            job.state, job.lease_until, job.task_token = "completed", None, None
            db.commit()
            return {"state": "completed", **job.counters}
        counters = dict(job.counters or {})
        for product in products:
            fill(db, product, runs, category_cache, maps, threshold, counters)
            counters["processed"] = counters.get("processed", 0) + 1
        job.cursor = products[-1].id
        job.counters = counters
        job.lease_until = now() + timedelta(minutes=5)
        db.commit()  # cursor advances only together with the batch
        done += 1
    job = db.get(ProductJob, job_id)
    job.state, job.lease_until, job.task_token = "pending", None, None
    db.commit()
    return {"state": "paused", **job.counters}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args(argv)
    from app.db import engine

    with Session(engine) as db:
        print(run(db, batch=max(1, min(args.batch, 5000))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
