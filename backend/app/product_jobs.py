"""CATEGORY-02C: background re-classification after a category-map decision.

Saving or deleting a category map re-runs the automatic decision for every
unlocked product of that own category. Up to SYNC_REAPPLY_LIMIT products this
happens inside the request (unchanged CATEGORY-02A behaviour). Larger own
categories (10 000+ products, at most 50 000 per run) get a resumable, leased
ProductJob instead, so the HTTP request never runs into the proxy timeout and
no single transaction holds tens of thousands of row locks against imports.

Guarantees:
* The map decision is committed first; the job only re-applies it.
* Each batch commits together with the job cursor, so a stopped worker resumes
  exactly after the last finished batch and classify() is idempotent.
* A newer decision for the same own category supersedes an older job; the
  superseded job stops at its next batch and the new job starts from the
  beginning, so the final state always reflects the latest map.
* Locked (manual) classifications are never touched.

Run pending/stalled jobs manually (inside the backend container or venv):
    python -m app.product_jobs
"""

import argparse
import secrets
import sys
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app.import_models import SupplierProduct
from app.models import now
from app.product_models import ProductClassification, ProductEvent, ProductJob
from app.worker import celery

KIND = "category_map_reapply"
SYNC_REAPPLY_LIMIT = 2_000
BATCH = 500
LEASE = timedelta(minutes=5)
ACTIVE = ("pending", "running")


def product_count(db, source):
    return db.scalar(
        select(func.count()).select_from(SupplierProduct).where(
            SupplierProduct.tenant_id == source.tenant_id,
            SupplierProduct.source_category_id == source.id,
        )
    )


def batches(db, source, cursor=0, size=BATCH):
    """Yield (products, classifications) per batch: two queries per batch."""
    while True:
        products = list(
            db.scalars(
                select(SupplierProduct)
                .where(
                    SupplierProduct.tenant_id == source.tenant_id,
                    SupplierProduct.source_category_id == source.id,
                    SupplierProduct.id > cursor,
                )
                .order_by(SupplierProduct.id)
                .limit(size)
            )
        )
        if not products:
            return
        # Prefetch: classify() then finds every row in the identity map.
        list(db.scalars(select(ProductClassification).where(
            ProductClassification.product_id.in_([p.id for p in products]))))
        yield products
        cursor = products[-1].id


def reapply_batch(db, source, products, maps, threshold, counters):
    for p in products:
        current = db.get(ProductClassification, p.id)
        if current is not None and current.locked:
            counters["locked_skipped"] += 1
        elif pc.classify(db, p, maps, threshold, source.path_text, record_event=False):
            counters["products_changed"] += 1
        counters["processed"] += 1


def reapply_now(db, source):
    """Synchronous path for small own categories (inside the request)."""
    maps, threshold = pc.maps_for(db, source.tenant_id), pc.auto_threshold(db)
    counters = {"processed": 0, "products_changed": 0, "locked_skipped": 0}
    for products in batches(db, source):
        reapply_batch(db, source, products, maps, threshold, counters)
        db.flush()
    return counters


def active_jobs(db, tenant_id, source_category_id):
    jobs = db.scalars(
        select(ProductJob).where(
            ProductJob.kind == KIND, ProductJob.tenant_id == tenant_id, ProductJob.state.in_(ACTIVE)
        ).with_for_update()
    )
    return [j for j in jobs if (j.counters or {}).get("source_category_id") == source_category_id]


def create_job(db, source, map_revision, total):
    """Supersede older jobs of this own category and queue a new one (no commit)."""
    for old in active_jobs(db, source.tenant_id, source.id):
        old.state, old.lease_until, old.task_token = "superseded", None, None
    job = ProductJob(
        kind=KIND, tenant_id=source.tenant_id, state="pending", cursor=0,
        counters={"source_category_id": source.id, "map_revision": map_revision, "total": total,
                  "processed": 0, "products_changed": 0, "locked_skipped": 0},
    )
    db.add(job)
    db.flush()
    return job


def job_dto(job):
    c = job.counters or {}
    stalled = job.state == "running" and (job.lease_until is None or job.lease_until < now())
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "stalled": stalled,
        "source_category_id": c.get("source_category_id"),
        "map_revision": c.get("map_revision"),
        "total": c.get("total"),
        "processed": c.get("processed", 0),
        "products_changed": c.get("products_changed", 0),
        "locked_skipped": c.get("locked_skipped", 0),
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def claim(db, job_id):
    job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
    if job is None or job.kind != KIND or job.state not in ACTIVE:
        db.rollback()
        return None
    if job.state == "running" and job.lease_until and job.lease_until > now():
        db.rollback()
        return None  # another worker holds a valid lease
    token = secrets.token_hex(16)
    job.state, job.task_token, job.lease_until = "running", token, now() + LEASE
    db.commit()
    return token


def advance(db: Session, job_id, batch=BATCH, max_batches=None):
    """Process a reapply job batch by batch; returns the final job state."""
    from app.product_models import ProductSourceCategory

    token = claim(db, job_id)
    if token is None:
        job = db.get(ProductJob, job_id)
        return job.state if job else "missing"
    done = 0
    try:
        while max_batches is None or done < max_batches:
            job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
            if job.task_token != token or job.state != "running":
                db.rollback()
                return job.state  # superseded or lease lost
            counters = dict(job.counters)
            source = db.get(ProductSourceCategory, counters["source_category_id"])
            products = next(batches(db, source, job.cursor, batch), None) if source else None
            if not products:
                job.state, job.lease_until, job.task_token = "completed", None, None
                db.add(ProductEvent(
                    tenant_id=job.tenant_id, source_category_id=counters["source_category_id"],
                    kind="category_map_reapplied",
                    after={"job_id": job.id, "map_revision": counters.get("map_revision"),
                           "products_changed": counters["products_changed"],
                           "locked_skipped": counters["locked_skipped"]},
                ))
                db.commit()
                return "completed"
            maps, threshold = pc.maps_for(db, source.tenant_id), pc.auto_threshold(db)
            reapply_batch(db, source, products, maps, threshold, counters)
            job.cursor = products[-1].id
            job.counters = counters
            job.lease_until = now() + LEASE
            db.commit()  # the cursor advances only together with its batch
            db.expunge_all()  # bounded memory for 50 000 products
            done += 1
    except Exception:
        db.rollback()
        job = db.get(ProductJob, job_id)
        if job is not None and job.task_token == token:
            job.state, job.lease_until, job.task_token = "pending", None, None
            job.error = "A háttérbeli újrabesorolás megszakadt; újraindítható."
            db.commit()
        raise
    job = db.get(ProductJob, job_id)
    if job.task_token == token:
        job.state, job.lease_until, job.task_token = "pending", None, None
        db.commit()
    return job.state


@celery.task(name="products.reapply_category_map", acks_late=True, reject_on_worker_lost=True)
def process_job(job_id):
    from app.db import engine

    with Session(engine()) as db:
        advance(db, job_id)


def enqueue(job_id):
    process_job.delay(job_id)


def resumable(db):
    jobs = db.scalars(select(ProductJob).where(ProductJob.kind == KIND, ProductJob.state.in_(ACTIVE))
                      .order_by(ProductJob.id))
    return [j.id for j in jobs if j.state == "pending" or not j.lease_until or j.lease_until < now()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run pending category-map reapply jobs.")
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args(argv)
    from app.db import engine

    with Session(engine()) as db:
        for job_id in resumable(db):
            print(job_id, advance(db, job_id, batch=max(1, min(args.batch, 5000))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
