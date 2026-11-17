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


def resumable(db, kinds=(KIND,)):
    jobs = db.scalars(select(ProductJob).where(ProductJob.kind.in_(kinds), ProductJob.state.in_(ACTIVE))
                      .order_by(ProductJob.id))
    return [(j.id, j.kind) for j in jobs
            if j.state == "pending" or not j.lease_until or j.lease_until < now()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run pending category-map and parameter jobs.")
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args(argv)
    from app.db import engine

    with Session(engine()) as db:
        from app import bulk_operations

        size = max(1, min(args.batch, 5000))
        for job_id, kind in resumable(db, (KIND, PARAM_KIND, *bulk_operations.KINDS)):
            step = {KIND: advance, PARAM_KIND: advance_parameters}.get(kind, bulk_operations.advance)
            print(job_id, kind, step(db, job_id, batch=size))
    return 0



# --- CATEGORY-03A: resumable parameter-slot runs ------------------------------

PARAM_KIND = "parameter_slots"


def parameter_scope_query(tenant_id, scope, cursor):
    from app.product_models import ProductClassification

    query = select(SupplierProduct).where(SupplierProduct.tenant_id == tenant_id,
                                          SupplierProduct.id > cursor)
    if scope.get("supplier_id"):
        query = query.where(SupplierProduct.supplier_id == scope["supplier_id"])
    if scope.get("source_category_id"):
        query = query.where(SupplierProduct.source_category_id == scope["source_category_id"])
    if scope.get("navigation_node_id"):
        query = query.join(ProductClassification, ProductClassification.product_id == SupplierProduct.id) \
            .where(ProductClassification.navigation_node_id == scope["navigation_node_id"])
    return query.order_by(SupplierProduct.id)


def create_parameter_job(db, tenant_id, mode, scope, start_after):
    from app.import_engine import run_product_limit

    for old in db.scalars(select(ProductJob).where(
            ProductJob.kind == PARAM_KIND, ProductJob.tenant_id == tenant_id,
            ProductJob.state.in_(ACTIVE)).with_for_update()):
        if (old.counters or {}).get("scope") == scope:
            old.state, old.lease_until, old.task_token = "superseded", None, None
    job = ProductJob(kind=PARAM_KIND, tenant_id=tenant_id, state="pending", cursor=start_after, counters={
        "mode": mode, "scope": scope, "start_after_product_id": start_after,
        "limit": run_product_limit(), "processed": 0, "has_more": False,
        "next_start_after_product_id": None, "products_changed": 0, "products_not_ready": 0,
        "slots": {"create": 0, "update": 0, "remove": 0, "keep": 0, "blocked_locked": 0},
        "states": {}})
    db.add(job)
    db.flush()
    return job


def parameter_job_dto(job):
    c = job.counters or {}
    stalled = job.state == "running" and (job.lease_until is None or job.lease_until < now())
    return {"id": job.id, "kind": job.kind, "state": job.state, "stalled": stalled,
            **{k: c.get(k) for k in ("mode", "scope", "start_after_product_id", "processed", "limit",
                                     "has_more", "next_start_after_product_id", "products_changed",
                                     "products_not_ready", "slots", "states")},
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None}


def claim_kind(db, job_id, kind):
    job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
    if job is None or job.kind != kind or job.state not in ACTIVE:
        db.rollback()
        return None
    if job.state == "running" and job.lease_until and job.lease_until > now():
        db.rollback()
        return None
    token = secrets.token_hex(16)
    job.state, job.task_token, job.lease_until = "running", token, now() + LEASE
    db.commit()
    return token


def advance_parameters(db: Session, job_id, batch=BATCH, max_batches=None):
    """Process a parameter run batch by batch (≤ limit products per run)."""
    from app import product_parameters as pp
    from app.catalog_store import active_version

    token = claim_kind(db, job_id, PARAM_KIND)
    if token is None:
        job = db.get(ProductJob, job_id)
        return job.state if job else "missing"
    done = 0
    try:
        while max_batches is None or done < max_batches:
            job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
            if job.task_token != token or job.state != "running":
                db.rollback()
                return job.state
            version = active_version(db)
            counters = json_copy(job.counters)
            room = counters["limit"] - counters["processed"]
            query = parameter_scope_query(job.tenant_id, counters["scope"], job.cursor)
            products = list(db.scalars(query.limit(min(batch, room)))) if room > 0 else []
            if not products:
                if room <= 0 and db.scalar(query.with_only_columns(SupplierProduct.id).limit(1)):
                    counters["has_more"] = True
                    counters["next_start_after_product_id"] = job.cursor
                job.counters = counters
                job.state, job.lease_until, job.task_token = "completed", None, None
                db.commit()
                return "completed"
            catalog = pp.Catalog(db, version) if version is not None else None
            alias_cache = {}
            existing = pp.stored_slots(db, [p.id for p in products])
            list(db.scalars(select(ProductClassification).where(
                ProductClassification.product_id.in_([p.id for p in products]))))
            for product in products:
                inputs, slots, decisions = pp.compute(db, product, catalog, alias_cache, existing[product.id])
                if not inputs["ready"]:
                    counters["products_not_ready"] += 1
                for key, value in pp.summary(decisions).items():
                    counters["slots"][key] += value
                for _, change, before, after in decisions:
                    state = (after or before or {}).get("state") if change != "remove" else None
                    if state:
                        counters["states"][state] = counters["states"].get(state, 0) + 1
                if counters["mode"] == "apply" and pp.apply(db, product, decisions, slots, run_id=job.id):
                    counters["products_changed"] += 1
                elif counters["mode"] == "preview" and any(
                        c not in ("keep", "blocked_locked") for _, c, _, _ in decisions):
                    counters["products_changed"] += 1
                counters["processed"] += 1
            job.cursor = products[-1].id
            job.counters = counters
            job.lease_until = now() + LEASE
            db.commit()
            db.expunge_all()
            done += 1
    except Exception:
        db.rollback()
        job = db.get(ProductJob, job_id)
        if job is not None and job.task_token == token:
            job.state, job.lease_until, job.task_token = "pending", None, None
            job.error = "A paraméterfutás megszakadt; újraindítható."
            db.commit()
        raise
    job = db.get(ProductJob, job_id)
    if job.task_token == token:
        job.state, job.lease_until, job.task_token = "pending", None, None
        db.commit()
    return job.state


def json_copy(value):
    import json

    return json.loads(json.dumps(value))


@celery.task(name="products.parameter_run", acks_late=True, reject_on_worker_lost=True)
def process_parameter_job(job_id):
    from app.db import engine

    with Session(engine()) as db:
        advance_parameters(db, job_id)


def enqueue_parameters(job_id):
    process_parameter_job.delay(job_id)


# CATEGORY-03C: register the bulk-operation Celery task wherever product jobs are
# loaded (the worker imports this module), without another worker.py change.
from app import bulk_operations  # noqa: E402,F401
# KNOWLEDGE-01: the knowledge.rebuild task is registered through the same import.
from app import knowledge  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main())
