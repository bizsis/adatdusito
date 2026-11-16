"""CATEGORY-03C: server-side selections, bulk preview/apply and preparation checks.

* A selection is a server-side snapshot of the full filtered product set of one
  tenant (product id + revision). The browser only holds an opaque token.
* A bulk preview computes, per product, exactly what the CATEGORY-03A engine
  would change (no writes) and stores a fingerprint of that change.
* A bulk apply only touches products whose preview was "eligible", whose
  revision is unchanged (atomic compare-and-set) and whose recomputed change
  equals the previewed fingerprint. Everything else is skipped and counted.
* A preparation check classifies products as approvable/blocked for later
  research; approval itself is created by the API from a completed check.

All three are resumable ProductJobs: 500 products per batch, one commit per
batch with the cursor, a savepoint per product (one failure never stops the
rest), at most run_product_limit() products per processing run (several runs
per job for larger selections), lease + cancel + permission re-check before
every write batch. No AI, no network, no pinfo_db.
"""

import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app import product_parameters as pp
from app.import_models import SupplierProduct
from app.models import now
from app.product_models import (
    ProductClassification,
    ProductEvent,
    ProductJob,
    ProductOperationItem,
    ProductSelection,
    ProductSelectionItem,
)
from app.worker import celery

PREVIEW, APPLY, CHECK = "bulk_preview", "bulk_apply", "preparation_check"
KINDS = (PREVIEW, APPLY, CHECK)
SELECTION_TTL = timedelta(hours=2)
SELECTION_MAX = 250_000
SELECTION_CHUNK = 5_000
BATCH = 500
LEASE = timedelta(minutes=5)
ACTIVE = ("pending", "running")
APPLY_PERMISSIONS = {"products.parameters", "products.bulk"}
UNIT_REASONS = {"unit_unverified", "ambiguous_number"}


def new_token():
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def request_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def schema_fingerprint():
    """Rules a preparation approval depends on (bindings, donor review, engine)."""
    root = Path(__file__).resolve().parents[1] / "reference_data"
    digest = hashlib.sha256(pp.RULE_VERSION.encode("utf-8"))
    for name in ("reviewed_parameter_bindings.json", "donor_review.json"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def fingerprint(decisions):
    payload = [(k, "blocked_locked" if c.startswith("blocked") else c, pp.short(a)) for k, c, _, a in decisions]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()


# --- selections ----------------------------------------------------------------


def create_selection(db, who, tid, filters, product_ids, exclude, catalog):
    from fastapi import HTTPException

    from app.import_models import Supplier
    from app.parameter_views import diff_conditions

    token, digest = new_token()
    selection = ProductSelection(
        tenant_id=tid, created_by=who.user.id, token_hash=digest,
        mode="product_ids" if product_ids is not None else "filters",
        filters=filters if product_ids is None else {}, excluded=len(exclude), total=0,
        catalog_version_id=catalog.version.id, rule_version=pp.RULE_VERSION,
        created_at=now(), expires_at=now() + SELECTION_TTL)
    db.add(selection)
    db.flush()
    excluded = set(exclude)
    if product_ids is not None:
        rows = db.execute(select(SupplierProduct.id, SupplierProduct.revision).join(
            Supplier, Supplier.id == SupplierProduct.supplier_id).where(
            SupplierProduct.id.in_(product_ids), SupplierProduct.tenant_id == tid,
            Supplier.tenant_id == tid)).all()
        if len(rows) != len(set(product_ids)):
            raise HTTPException(404, "Egy vagy több termék nem található.")
        rows = [r for r in rows if r[0] not in excluded]
        db.bulk_insert_mappings(ProductSelectionItem, [
            {"selection_id": selection.id, "product_id": pid, "revision": rev} for pid, rev in rows])
        selection.total = len(rows)
    else:
        cursor = 0
        conditions = diff_conditions(tid, filters)
        while True:
            rows = db.execute(
                select(SupplierProduct.id, SupplierProduct.revision)
                .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
                .outerjoin(ProductClassification, ProductClassification.product_id == SupplierProduct.id)
                .where(*conditions, SupplierProduct.id > cursor)
                .order_by(SupplierProduct.id).limit(SELECTION_CHUNK)
            ).all()
            if not rows:
                break
            cursor = rows[-1][0]
            rows = [r for r in rows if r[0] not in excluded]
            selection.total += len(rows)
            if selection.total > SELECTION_MAX:
                db.rollback()
                raise HTTPException(422, f"A kiválasztás legfeljebb {SELECTION_MAX} terméket tartalmazhat. "
                                         "Szűkítsd a szűrést.")
            db.bulk_insert_mappings(ProductSelectionItem, [
                {"selection_id": selection.id, "product_id": pid, "revision": rev} for pid, rev in rows])
    if selection.total == 0:
        db.rollback()
        raise HTTPException(422, "A kiválasztás üres.")
    return selection, token


def selection_dto(s, token=None):
    result = {"id": s.id, "total": s.total, "expires_at": s.expires_at.isoformat(), "filters": s.filters,
              "excluded": s.excluded, "mode": s.mode, "catalog_version_id": s.catalog_version_id,
              "rule_version": s.rule_version, "created_at": s.created_at.isoformat(),
              "expired": s.expires_at <= now()}
    if token is not None:
        result["selection_token"] = token
    return result


# --- jobs ------------------------------------------------------------------------


def empty_counters(kind, total, run_limit):
    counters = {"total": total, "processed": 0, "runs": 0, "run_processed": 0, "run_limit": run_limit,
                "outcomes": {}, "error_count": 0}
    if kind in (PREVIEW, APPLY):
        counters.update(slots={"create": 0, "update": 0, "remove": 0, "keep": 0, "blocked_locked": 0},
                        new_slots={}, accepted_present=0, source_refresh=0, source_overwrites=0,
                        revision_changed_since_selection=0)
    else:
        counters.update(blocked_reasons={}, research_targets=0, mandatory_research_targets=0)
    return counters


def create_job(db, kind, tid, user_id, selection, total, extra=None, idempotency_key=None, req_hash=None):
    from app.import_engine import run_product_limit

    job = ProductJob(kind=kind, tenant_id=tid, state="pending", cursor=0, created_by=user_id,
                     idempotency_key=idempotency_key, request_hash=req_hash,
                     counters={**empty_counters(kind, total, run_product_limit()),
                               "selection_id": selection.id, "expires_at": selection.expires_at.isoformat(),
                               **(extra or {})})
    db.add(job)
    db.flush()
    return job


def operation_dto(job):
    c = job.counters or {}
    stalled = job.state == "running" and (job.lease_until is None or job.lease_until < now())
    keys = ("selection_id", "preview_id", "check_id", "expires_at", "total", "processed", "runs", "run_limit",
            "outcomes", "slots", "new_slots", "accepted_present", "source_refresh", "source_overwrites",
            "revision_changed_since_selection", "blocked_reasons", "research_targets",
            "mandatory_research_targets", "error_count", "stopped_reason")
    return {"id": job.id, "kind": job.kind, "state": job.state, "stalled": stalled,
            **{k: c[k] for k in keys if k in c},
            "error": job.error, "created_by": job.created_by,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None}


def bump(counter, key, n=1):
    counter[key] = counter.get(key, 0) + n


def count_decisions(c, decisions):
    for key, value in pp.summary(decisions).items():
        c["slots"][key] += value
    for _, change, before, after in decisions:
        if change == "create":
            bump(c["new_slots"], after["state"])
        elif change == "keep" and after and after["state"] == "present":
            c["accepted_present"] += 1
        elif change == "update":
            if "source_refreshed" in after["reason_codes"] and "source_refreshed" not in before["reason_codes"]:
                c["source_refresh"] += 1
            elif before["value"] is not None and (after["value"], after["unit"], after["value_id"]) != (
                    before["value"], before["unit"], before["value_id"]):
                c["source_overwrites"] += 1  # must stay 0 by the engine's rules


def skip_outcome(state):
    return {"pending_review": "skipped_pending_review", "choice_required": "skipped_choice_required"}.get(
        state, "skipped_no_donor")


def preview_product(db, job, c, p, sel_revision, catalog, alias_cache, existing):
    inputs, slots, decisions = pp.compute(db, p, catalog, alias_cache, existing)
    if sel_revision is not None and sel_revision != p.revision:
        c["revision_changed_since_selection"] += 1
    if not inputs["ready"]:
        return skip_outcome(inputs["profile_state"]), None, {"reasons": [inputs["profile_state"]]}
    summary = pp.summary(decisions)
    count_decisions(c, decisions)
    outcome = "eligible" if summary["create"] or summary["update"] or summary["remove"] else "unchanged"
    return outcome, fingerprint(decisions), {"summary": summary, "reasons": []}


def check_product(db, job, c, p, catalog, alias_cache, existing):
    cls = db.get(ProductClassification, p.id)
    node = cls.navigation_node_id if cls else None
    state = pc.parameter_profile_state(node, cls.donor_emag_category_id if cls else None)
    reasons = []
    if not node:
        reasons.append("unclassified")
    elif state == "pending_review":
        reasons.append("donor_pending_review")
    elif state == "choice_required":
        reasons.append("donor_choice_required")
    elif state != "ready":
        reasons.append("donor_missing")
    rows = list(existing.values())
    if not reasons:
        if not any(r.slot_key.startswith("emag:") for r in rows):
            reasons.append("not_prepared")
        _, _, decisions = pp.compute(db, p, catalog, alias_cache, existing)
        if any(ch not in ("keep", "blocked_locked") for _, ch, _, _ in decisions):
            reasons.append("stale_diff")
        for r in rows:
            codes = set(r.reason_codes or [])
            if r.state == "conflict" and "meaning_conflict" not in reasons:
                reasons.append("meaning_conflict")
            if r.state == "review" and "similar_label" in codes and "meaning_uncertain" not in reasons:
                reasons.append("meaning_uncertain")
            if (r.state == "invalid" or (r.state == "review" and codes & UNIT_REASONS)) \
                    and "unit_conflict" not in reasons:
                reasons.append("unit_conflict")
    missing = [r for r in rows if r.state == "missing" and r.slot_key.startswith("emag:")]
    detail = {"reasons": reasons, "summary": {"research_targets": len(missing),
                                              "mandatory_research_targets": sum(r.mandatory for r in missing)}}
    for reason in reasons:
        bump(c["blocked_reasons"], reason)
    if not reasons:
        c["research_targets"] += detail["summary"]["research_targets"]
        c["mandatory_research_targets"] += detail["summary"]["mandatory_research_targets"]
    return ("blocked" if reasons else "approvable"), str(p.revision), detail


def apply_item(db, job, c, item, p, catalog, alias_cache, existing):
    if p.revision != item.revision_before:
        return "stale", None
    _, slots, decisions = pp.compute(db, p, catalog, alias_cache, existing)
    if fingerprint(decisions) != item.fingerprint:
        return "changed_since_preview", None
    if not any(ch not in ("keep", "blocked_locked") for _, ch, _, _ in decisions):
        return "unchanged", None
    result = db.execute(update(SupplierProduct).where(
        SupplierProduct.id == p.id, SupplierProduct.revision == item.revision_before
    ).values(revision=SupplierProduct.revision + 1))
    if result.rowcount != 1:
        return "stale", None
    p.revision = item.revision_before + 1
    count_decisions(c, decisions)
    pp.apply(db, p, decisions, slots, actor_id=job.created_by, run_id=job.id, bump=False)
    return "applied", p.revision


def still_allowed(db, job):
    from app.access_control import can_access, effective
    from app.models import User

    user = db.get(User, job.created_by) if job.created_by else None
    if user is None or not user.active:
        return False
    if not user.superadmin and not can_access(db, user, job.tenant_id):
        return False
    permissions, _ = effective(db, user, job.tenant_id)
    return APPLY_PERMISSIONS <= set(permissions)


def claim(db, job_id):
    job = db.scalar(select(ProductJob).where(ProductJob.id == job_id).with_for_update())
    if job is None or job.kind not in KINDS or job.state not in ACTIVE:
        db.rollback()
        return None
    if job.state == "running" and job.lease_until and job.lease_until > now():
        db.rollback()
        return None
    token = secrets.token_hex(16)
    job.state, job.task_token, job.lease_until = "running", token, now() + LEASE
    db.commit()
    return token


def next_batch(db, job, c, batch):
    if job.kind == APPLY:
        items = list(db.scalars(select(ProductOperationItem).where(
            ProductOperationItem.job_id == c["preview_id"], ProductOperationItem.outcome == "eligible",
            ProductOperationItem.product_id > job.cursor,
            (ProductOperationItem.apply_outcome.is_(None)) | (ProductOperationItem.apply_outcome == "error"),
        ).order_by(ProductOperationItem.product_id).limit(batch)))
        return [(i.product_id, i) for i in items]
    rows = db.execute(select(ProductSelectionItem.product_id, ProductSelectionItem.revision).where(
        ProductSelectionItem.selection_id == c["selection_id"], ProductSelectionItem.product_id > job.cursor,
    ).order_by(ProductSelectionItem.product_id).limit(batch)).all()
    return [(pid, rev) for pid, rev in rows]


def finish(db, job, c, state="completed", reason=None):
    if reason:
        c["stopped_reason"] = reason
    job.counters = c
    job.state, job.lease_until, job.task_token = state, None, None
    db.add(ProductEvent(tenant_id=job.tenant_id, kind="bulk_operation", actor_id=job.created_by,
                        after={"job_id": job.id, "kind": job.kind, "state": state,
                               "outcomes": c.get("outcomes"), "processed": c.get("processed")}))
    db.commit()
    return state


def advance(db: Session, job_id, batch=BATCH, max_batches=None):
    """Process one operation job; returns its state when this call stops."""
    from app.catalog_store import active_version

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
                return job.state  # cancelled or lease lost
            c = json.loads(json.dumps(job.counters))
            if job.kind == APPLY and not still_allowed(db, job):
                return finish(db, job, c, "cancelled", "permission_revoked")
            if c["run_processed"] >= c["run_limit"]:
                # One processing run is full: release; the next run continues.
                c["run_processed"] = 0
                job.counters = c
                job.state, job.lease_until, job.task_token = "pending", None, None
                db.commit()
                try:
                    enqueue(job.id)
                except Exception:  # resumable via /resume or the CLI
                    pass
                return "pending"
            size = min(batch, c["run_limit"] - c["run_processed"])
            items = next_batch(db, job, c, size)
            if not items:
                return finish(db, job, c)
            if c["run_processed"] == 0:
                c["runs"] += 1
            version = active_version(db)
            catalog = pp.Catalog(db, version) if version is not None else None
            if catalog is None:
                return finish(db, job, c, "failed", "catalog_unavailable")
            ids = [pid for pid, _ in items]
            products = {p.id: p for p in db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(ids)))}
            list(db.scalars(select(ProductClassification).where(ProductClassification.product_id.in_(ids))))
            existing = pp.stored_slots(db, ids)
            alias_cache = {}
            for pid, extra in items:
                p = products.get(pid)
                savepoint = db.begin_nested()
                try:
                    if job.kind == APPLY:
                        outcome, revision_after = apply_item(db, job, c, extra, p, catalog, alias_cache,
                                                             existing[pid])
                        extra.apply_job_id, extra.apply_outcome = job.id, outcome
                        extra.revision_after = revision_after
                    else:
                        if job.kind == PREVIEW:
                            outcome, fp, detail = preview_product(db, job, c, p, extra, catalog, alias_cache,
                                                                  existing[pid])
                        else:
                            outcome, fp, detail = check_product(db, job, c, p, catalog, alias_cache,
                                                                existing[pid])
                        db.add(ProductOperationItem(job_id=job.id, product_id=pid, tenant_id=job.tenant_id,
                                                      revision_before=p.revision, fingerprint=fp,
                                                      outcome=outcome, detail=detail))
                    savepoint.commit()
                except Exception as exc:  # one product never stops the batch
                    savepoint.rollback()
                    outcome = "error"
                    c["error_count"] += 1
                    if job.kind == APPLY:
                        db.execute(update(ProductOperationItem).where(
                            ProductOperationItem.job_id == extra.job_id,
                            ProductOperationItem.product_id == pid).values(
                            apply_job_id=job.id, apply_outcome="error"))
                    else:
                        db.merge(ProductOperationItem(
                            job_id=job.id, product_id=pid, tenant_id=job.tenant_id,
                            revision_before=p.revision if p is not None else 0, fingerprint=None,
                            outcome="error", detail={"reasons": [type(exc).__name__]}))
                bump(c["outcomes"], outcome)
                c["processed"] += 1
                c["run_processed"] += 1
            job.cursor = ids[-1]
            job.counters = c
            job.lease_until = now() + LEASE
            db.commit()
            db.expunge_all()
            done += 1
    except Exception:
        db.rollback()
        job = db.get(ProductJob, job_id)
        if job is not None and job.task_token == token:
            job.state, job.lease_until, job.task_token = "pending", None, None
            job.error = "A tömeges művelet megszakadt; folytatható."
            db.commit()
        raise
    job = db.get(ProductJob, job_id)
    if job.task_token == token:
        job.state, job.lease_until, job.task_token = "pending", None, None
        db.commit()
    return job.state


@celery.task(name="products.operation", acks_late=True, reject_on_worker_lost=True)
def process_operation(job_id):
    from app.db import engine

    with Session(engine()) as db:
        advance(db, job_id)


def enqueue(job_id):
    process_operation.delay(job_id)
