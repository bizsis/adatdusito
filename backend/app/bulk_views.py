"""CATEGORY-03C API: selections, bulk preview/apply, preparation checks/approvals.

Contract: docs/design/CATEGORY-03C-API.md. Mounted under /api/v1/workspace by
app.workspace_views. Tenant from the session only; tokens are opaque, stored
hashed and bound to their creator. No AI, credits, payment or export.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import bulk_operations as bo
from app import product_catalog as pc
from app import product_parameters as pp
from app.import_api import tenant
from app.import_models import SupplierProduct
from app.models import now
from app.parameter_views import DIFF_FILTERS
from app.product_models import (
    PreparationApproval,
    PreparationApprovalItem,
    ProductClassification,
    ProductJob,
    ProductOperationItem,
    ProductSelection,
)
from app.security import audit, database, require

router = APIRouter()
MAX_PAGE = 100
STALE = "A tömeges művelet lejárt vagy a token érvénytelen. Készíts új kiválasztást."


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["present", "missing", "review", "conflict", "invalid", "source_only", "detached"] | None = None
    mandatory_missing: bool | None = None
    navigation_node_id: str | None = Field(default=None, max_length=160)
    source_category_id: int | None = Field(default=None, ge=1)
    supplier_id: int | None = Field(default=None, ge=1)
    parameter_profile_state: Literal["ready", "choice_required", "pending_review", "none"] | None = None
    q: str | None = Field(default=None, max_length=120)


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: Filters | None = None
    exclude_product_ids: list[int] = Field(default_factory=list, max_length=1000)
    product_ids: list[int] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def one_mode(self):
        if self.filters is not None and self.product_ids is not None:
            raise ValueError("A filters és a product_ids együtt nem adható meg.")
        return self


def selection_for(db, who, token):
    selection = db.scalar(select(ProductSelection).where(ProductSelection.token_hash == bo.token_hash(token)))
    if selection is None or selection.tenant_id != tenant(who) or selection.created_by != who.user.id \
            or selection.expires_at <= now():
        raise HTTPException(409, STALE)
    return selection


def job_for(db, who, id, kinds=bo.KINDS):
    job = db.get(ProductJob, id)
    if job is None or job.kind not in kinds or job.tenant_id != tenant(who):
        raise HTTPException(404, "A tömeges művelet nem található.")
    return job


def expired(job):
    return (job.counters or {}).get("expires_at", "") <= now().isoformat()


def start(job, result):
    try:
        bo.enqueue(job.id)
    except Exception:  # broker down: pending and resumable
        result["enqueue_failed"] = True
    return result


# --- selections -------------------------------------------------------------------


@router.post("/product-selections")
def create_selection(body: SelectionInput, who=Depends(require("products.read")),
                     db: Session = Depends(database)):
    tid = tenant(who)
    catalog = pp.active_catalog(db)
    filters = (body.filters or Filters()).model_dump()
    filters = {k: filters[k] for k in DIFF_FILTERS}
    if filters["navigation_node_id"] and not pc.internal_category(filters["navigation_node_id"]):
        raise HTTPException(422, "Ismeretlen vagy nem besorolható belső kategória.")
    selection, token = bo.create_selection(db, who, tid, filters, body.product_ids, body.exclude_product_ids,
                                           catalog)
    audit(db, who, "products.selection_create", str(selection.id), tid, mode=selection.mode,
          filters=selection.filters, total=selection.total, excluded=selection.excluded)
    db.commit()
    return bo.selection_dto(selection, token)


@router.get("/product-selections/{id}")
def selection(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    row = db.get(ProductSelection, id)
    if row is None or row.tenant_id != tenant(who) or row.created_by != who.user.id:
        raise HTTPException(404, "A kiválasztás nem található.")
    return bo.selection_dto(row)


# --- bulk preview / apply -------------------------------------------------------------


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_token: str = Field(min_length=20, max_length=100)


@router.post("/parameter-bulk-previews")
def create_preview(body: TokenInput, who=Depends(require("products.read")), db: Session = Depends(database)):
    tid = tenant(who)
    pp.active_catalog(db)
    sel = selection_for(db, who, body.selection_token)
    token, digest = bo.new_token()
    job = bo.create_job(db, bo.PREVIEW, tid, who.user.id, sel, sel.total, {"token_hash": digest})
    audit(db, who, "products.bulk_preview", str(job.id), tid, selection_id=sel.id, total=sel.total)
    db.commit()
    return start(job, {"preview": bo.operation_dto(job), "preview_token": token})


class ApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_token: str = Field(min_length=20, max_length=100)
    confirm: bool
    expected_eligible: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=80)
    reason: str | None = Field(default=None, max_length=500)


def require_all(who, permissions):
    missing = set(permissions) - set(who.permissions)
    if missing:
        raise HTTPException(403, "Nincs jogosultság ehhez a tömeges művelethez.")


def replay(db, tid, kind, key, req_hash):
    existing = db.scalar(select(ProductJob).where(ProductJob.tenant_id == tid, ProductJob.kind == kind,
                                                  ProductJob.idempotency_key == key))
    if existing is None:
        return None
    if existing.request_hash != req_hash:
        raise HTTPException(409, "Ez az idempotenciakulcs már egy másik kéréshez tartozik.")
    return existing


@router.post("/parameter-bulk-previews/{id}/apply")
def apply_preview(id: int, body: ApplyInput, who=Depends(require("products.parameters")),
                  db: Session = Depends(database)):
    require_all(who, bo.APPLY_PERMISSIONS)
    tid = tenant(who)
    req_hash = bo.request_hash({"preview_id": id, **body.model_dump(exclude={"preview_token"})})
    existing = replay(db, tid, bo.APPLY, body.idempotency_key, req_hash)
    if existing is not None:
        return {"apply": bo.operation_dto(existing), "replayed": True}
    if not body.confirm:
        raise HTTPException(422, "A tömeges alkalmazáshoz kifejezett megerősítés kell (confirm).")
    preview = job_for(db, who, id, (bo.PREVIEW,))
    c = preview.counters or {}
    if preview.created_by != who.user.id or c.get("token_hash") != bo.token_hash(body.preview_token) \
            or expired(preview):
        raise HTTPException(409, STALE)
    if preview.state != "completed":
        raise HTTPException(409, "Az előnézet még nem készült el.")
    eligible = c.get("outcomes", {}).get("eligible", 0)
    if body.expected_eligible != eligible:
        raise HTTPException(409, f"A megerősített darabszám ({body.expected_eligible}) eltér az előnézettől "
                                 f"({eligible}). Töltsd be újra az előnézetet.")
    running = [j for j in db.scalars(select(ProductJob).where(
        ProductJob.tenant_id == tid, ProductJob.kind == bo.APPLY, ProductJob.state.in_(bo.ACTIVE)))
        if (j.counters or {}).get("preview_id") == preview.id]
    if running:
        raise HTTPException(409, "Ehhez az előnézethez már fut alkalmazás.")
    remaining = db.scalar(select(func.count()).select_from(ProductOperationItem).where(
        ProductOperationItem.job_id == preview.id, ProductOperationItem.outcome == "eligible",
        (ProductOperationItem.apply_outcome.is_(None)) | (ProductOperationItem.apply_outcome == "error")))
    selection = db.get(ProductSelection, c["selection_id"])
    try:
        job = bo.create_job(db, bo.APPLY, tid, who.user.id, selection, remaining,
                            {"preview_id": preview.id, "reason": body.reason},
                            idempotency_key=body.idempotency_key, req_hash=req_hash)
    except IntegrityError:
        db.rollback()
        existing = replay(db, tid, bo.APPLY, body.idempotency_key, req_hash)
        return {"apply": bo.operation_dto(existing), "replayed": True}
    audit(db, who, "products.bulk_apply", str(job.id), tid, preview_id=preview.id, eligible=eligible,
          remaining=remaining, reason=body.reason)
    db.commit()
    return start(job, {"apply": bo.operation_dto(job)})


# --- jobs: status, items, cancel, resume -----------------------------------------------


@router.get("/product-jobs/{id}/items")
def job_items(
    id: int,
    outcome: str | None = Query(None, max_length=32),
    apply_outcome: str | None = Query(None, max_length=32),
    cursor: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    job = job_for(db, who, id)
    item = ProductOperationItem
    if job.kind == bo.APPLY:
        query = select(item).where(item.apply_job_id == job.id)
    else:
        query = select(item).where(item.job_id == job.id)
    if outcome is not None:
        query = query.where(item.outcome == outcome)
    if apply_outcome is not None:
        query = query.where(item.apply_outcome == apply_outcome)
    rows = list(db.scalars(query.where(item.product_id > cursor).order_by(item.product_id).limit(limit + 1)))
    page = rows[:limit]
    data = {p.id: p.data or {} for p in db.scalars(select(SupplierProduct).where(
        SupplierProduct.id.in_([r.product_id for r in page])))} if page else {}
    return {"items": [{"product_id": r.product_id, "name": data.get(r.product_id, {}).get("name"),
                       "sku": data.get(r.product_id, {}).get("sku"), "outcome": r.outcome,
                       "apply_outcome": r.apply_outcome, "revision_before": r.revision_before,
                       "revision_after": r.revision_after, "summary": (r.detail or {}).get("summary", {}),
                       "reasons": (r.detail or {}).get("reasons", [])} for r in page],
            "next_cursor": page[-1].product_id if len(rows) > limit else None}


def may_control(who, job):
    needed = {bo.APPLY: bo.APPLY_PERMISSIONS, bo.CHECK: {"products.read"},
              bo.PREVIEW: {"products.read"}}[job.kind]
    if job.created_by != who.user.id and not needed <= set(who.permissions):
        raise HTTPException(403, "Nincs jogosultság a művelet vezérléséhez.")
    if job.kind == bo.APPLY:
        require_all(who, bo.APPLY_PERMISSIONS)


@router.post("/product-jobs/{id}/cancel")
def cancel(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    job = job_for(db, who, id)
    may_control(who, job)
    if job.state not in bo.ACTIVE:
        raise HTTPException(409, "A művelet már nem fut.")
    c = dict(job.counters or {})
    c["stopped_reason"] = "cancelled_by_user"
    job.counters = c
    job.state, job.lease_until, job.task_token = "cancelled", None, None
    audit(db, who, "products.job_cancel", str(job.id), job.tenant_id, processed=c.get("processed"))
    db.commit()
    return bo.operation_dto(job)


@router.post("/product-jobs/{id}/resume")
def resume(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    job = job_for(db, who, id)
    may_control(who, job)
    stalled = job.state == "running" and (job.lease_until is None or job.lease_until < now())
    if job.state != "pending" and not stalled:
        raise HTTPException(409, "Csak várakozó vagy elakadt művelet folytatható.")
    if stalled:
        job.state, job.task_token, job.lease_until = "pending", None, None
    audit(db, who, "products.job_resume", str(job.id), job.tenant_id, processed=job.counters.get("processed"))
    db.commit()
    return start(job, bo.operation_dto(job))


# --- preparation checks and approvals -----------------------------------------------------


@router.post("/preparation-checks")
def create_check(body: TokenInput, who=Depends(require("products.read")), db: Session = Depends(database)):
    tid = tenant(who)
    pp.active_catalog(db)
    sel = selection_for(db, who, body.selection_token)
    token, digest = bo.new_token()
    job = bo.create_job(db, bo.CHECK, tid, who.user.id, sel, sel.total, {"token_hash": digest})
    audit(db, who, "products.preparation_check", str(job.id), tid, selection_id=sel.id, total=sel.total)
    db.commit()
    return start(job, {"check": bo.operation_dto(job), "check_token": token})


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: int = Field(ge=1)
    check_token: str = Field(min_length=20, max_length=100)
    confirm: bool
    expected_approvable: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=80)
    reason: str | None = Field(default=None, max_length=500)


def schema_current(db, approval):
    from app.catalog_store import active_version

    version = active_version(db)
    return (version is not None and version.id == approval.catalog_version_id
            and approval.rule_version == pp.RULE_VERSION
            and approval.schema_fingerprint == bo.schema_fingerprint())


def validity_counts(db, approval):
    item = PreparationApprovalItem
    if approval.state != "active" or not schema_current(db, approval):
        return 0, approval.counts.get("approved", 0)
    valid = db.scalar(select(func.count()).select_from(item).join(
        SupplierProduct, SupplierProduct.id == item.product_id).where(
        item.approval_id == approval.id, item.invalidated_at.is_(None),
        SupplierProduct.revision == item.product_revision))
    return valid, approval.counts.get("approved", 0) - valid


def approval_dto(db, a, live=True):
    valid, invalid = validity_counts(db, a) if live else (a.counts.get("valid"), a.counts.get("invalid"))
    return {"id": a.id, "version": a.version, "state": a.state, "check_id": a.check_id,
            "selection_id": a.selection_id, **{k: a.counts.get(k, 0) for k in (
                "approved", "skipped_stale", "research_targets", "mandatory_research_targets")},
            "valid": valid, "invalid": invalid, "catalog_version_id": a.catalog_version_id,
            "rule_version": a.rule_version, "schema_fingerprint": a.schema_fingerprint,
            "schema_current": schema_current(db, a) if live else None, "reason": a.reason,
            "approved_by": a.approved_by, "approved_at": a.approved_at.isoformat(),
            "revoked_by": a.revoked_by, "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
            "revoke_reason": a.revoke_reason,
            "revalidated_at": a.revalidated_at.isoformat() if a.revalidated_at else None}


@router.post("/preparation-approvals")
def approve(body: ApprovalInput, who=Depends(require("products.prepare.approve")),
            db: Session = Depends(database)):
    from app.catalog_store import active_version

    tid = tenant(who)
    req_hash = bo.request_hash(body.model_dump(exclude={"check_token"}))
    existing = db.scalar(select(PreparationApproval).where(
        PreparationApproval.tenant_id == tid, PreparationApproval.idempotency_key == body.idempotency_key))
    if existing is not None:
        if existing.request_hash != req_hash:
            raise HTTPException(409, "Ez az idempotenciakulcs már egy másik kéréshez tartozik.")
        return {**approval_dto(db, existing), "replayed": True}
    if not body.confirm:
        raise HTTPException(422, "A jóváhagyáshoz kifejezett megerősítés kell (confirm).")
    check = job_for(db, who, body.check_id, (bo.CHECK,))
    c = check.counters or {}
    if check.created_by != who.user.id or c.get("token_hash") != bo.token_hash(body.check_token) \
            or expired(check):
        raise HTTPException(409, STALE)
    if check.state != "completed":
        raise HTTPException(409, "Az előkészítési ellenőrzés még nem készült el.")
    approvable = c.get("outcomes", {}).get("approvable", 0)
    if body.expected_approvable != approvable:
        raise HTTPException(409, f"A megerősített darabszám ({body.expected_approvable}) eltér az "
                                 f"ellenőrzéstől ({approvable}). Töltsd be újra az ellenőrzést.")
    if approvable == 0:
        raise HTTPException(422, "Nincs jóváhagyható termék.")
    version = active_version(db)
    approval = PreparationApproval(
        tenant_id=tid, state="active", version=1, check_id=check.id, selection_id=c["selection_id"],
        catalog_version_id=version.id if version else None, rule_version=pp.RULE_VERSION,
        schema_fingerprint=bo.schema_fingerprint(), counts={}, reason=body.reason,
        idempotency_key=body.idempotency_key, request_hash=req_hash, approved_by=who.user.id,
        approved_at=now())
    db.add(approval)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ez az idempotenciakulcs már foglalt. Ismételd meg a kérést.")
    counts = {"approved": 0, "skipped_stale": 0, "research_targets": 0, "mandatory_research_targets": 0}
    cursor = 0
    while True:
        rows = db.execute(
            select(ProductOperationItem, SupplierProduct.revision, ProductClassification.navigation_node_id,
                   ProductClassification.donor_emag_category_id)
            .join(SupplierProduct, SupplierProduct.id == ProductOperationItem.product_id)
            .outerjoin(ProductClassification, ProductClassification.product_id == ProductOperationItem.product_id)
            .where(ProductOperationItem.job_id == check.id, ProductOperationItem.outcome == "approvable",
                   ProductOperationItem.product_id > cursor)
            .order_by(ProductOperationItem.product_id).limit(1000)
        ).all()
        if not rows:
            break
        cursor = rows[-1][0].product_id
        batch = []
        for item, revision, node, donor in rows:
            if revision != item.revision_before:
                counts["skipped_stale"] += 1
                continue
            s = (item.detail or {}).get("summary", {})
            batch.append({"approval_id": approval.id, "product_id": item.product_id, "tenant_id": tid,
                          "product_revision": revision, "navigation_node_id": node,
                          "donor_emag_category_id": donor,
                          "research_targets": s.get("research_targets", 0),
                          "mandatory_research_targets": s.get("mandatory_research_targets", 0)})
            counts["approved"] += 1
            counts["research_targets"] += s.get("research_targets", 0)
            counts["mandatory_research_targets"] += s.get("mandatory_research_targets", 0)
        db.bulk_insert_mappings(PreparationApprovalItem, batch)
    approval.counts = {**counts, "valid": counts["approved"], "invalid": 0}
    audit(db, who, "products.preparation_approve", str(approval.id), tid, check_id=check.id,
          reason=body.reason, **counts)
    db.commit()
    return approval_dto(db, approval)


def approval_for(db, who, id):
    row = db.get(PreparationApproval, id)
    if row is None or row.tenant_id != tenant(who):
        raise HTTPException(404, "A jóváhagyás nem található.")
    return row


@router.get("/preparation-approvals")
def approvals(state: Literal["active", "revoked"] | None = None, cursor: int = Query(0, ge=0),
              limit: int = Query(25, ge=1, le=MAX_PAGE), who=Depends(require("products.read")),
              db: Session = Depends(database)):
    query = select(PreparationApproval).where(PreparationApproval.tenant_id == tenant(who),
                                              PreparationApproval.id > cursor)
    if state:
        query = query.where(PreparationApproval.state == state)
    rows = list(db.scalars(query.order_by(PreparationApproval.id).limit(limit + 1)))
    return {"items": [approval_dto(db, a, live=False) for a in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


@router.get("/preparation-approvals/{id}")
def approval(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    return approval_dto(db, approval_for(db, who, id))


def item_validity(a, item, current_revision, schema_ok):
    if a.state != "active":
        return False, "revoked"
    if item.invalidated_at is not None:
        return False, item.invalid_reason
    if not schema_ok:
        return False, "schema_changed"
    if current_revision != item.product_revision:
        return False, "product_changed"
    return True, None


@router.get("/preparation-approvals/{id}/items")
def approval_items(id: int, valid: bool | None = None, cursor: int = Query(0, ge=0),
                   limit: int = Query(25, ge=1, le=MAX_PAGE), who=Depends(require("products.read")),
                   db: Session = Depends(database)):
    a = approval_for(db, who, id)
    item = PreparationApprovalItem
    query = select(item, SupplierProduct.revision).join(SupplierProduct, SupplierProduct.id == item.product_id) \
        .where(item.approval_id == a.id, item.product_id > cursor)
    schema_ok = schema_current(db, a)
    if valid is not None:
        ok = (item.invalidated_at.is_(None)) & (SupplierProduct.revision == item.product_revision)
        if valid:
            if a.state != "active" or not schema_ok:
                return {"items": [], "next_cursor": None}
            query = query.where(ok)
        elif a.state == "active" and schema_ok:
            query = query.where(~ok)
    rows = db.execute(query.order_by(item.product_id).limit(limit + 1)).all()
    page = rows[:limit]
    result = []
    for i, revision in page:
        ok, why = item_validity(a, i, revision, schema_ok)
        result.append({"product_id": i.product_id, "product_revision": i.product_revision,
                       "current_revision": revision, "valid": ok, "invalid_reason": why,
                       "navigation_node_id": i.navigation_node_id,
                       "donor_emag_category_id": i.donor_emag_category_id,
                       "research_targets": i.research_targets,
                       "mandatory_research_targets": i.mandatory_research_targets})
    return {"items": result, "next_cursor": page[-1][0].product_id if len(rows) > limit else None}


@router.post("/preparation-approvals/{id}/revalidate")
def revalidate(id: int, who=Depends(require("products.prepare.approve")), db: Session = Depends(database)):
    a = approval_for(db, who, id)
    if a.state != "active":
        raise HTTPException(409, "Visszavont jóváhagyás nem mérhető újra.")
    item = PreparationApprovalItem
    reason = None if schema_current(db, a) else "schema_changed"
    stamp = now()
    cursor, invalidated = 0, 0
    while True:
        rows = db.execute(select(item, SupplierProduct.revision).join(
            SupplierProduct, SupplierProduct.id == item.product_id).where(
            item.approval_id == a.id, item.invalidated_at.is_(None), item.product_id > cursor)
            .order_by(item.product_id).limit(1000)).all()
        if not rows:
            break
        cursor = rows[-1][0].product_id
        for i, revision in rows:
            why = reason or ("product_changed" if revision != i.product_revision else None)
            if why:
                i.invalidated_at, i.invalid_reason = stamp, why
                invalidated += 1
        db.flush()
    valid, invalid = validity_counts(db, a)
    a.counts = {**a.counts, "valid": valid, "invalid": invalid}
    a.revalidated_at = stamp
    audit(db, who, "products.preparation_revalidate", str(a.id), a.tenant_id, invalidated=invalidated,
          valid=valid, invalid=invalid)
    db.commit()
    return approval_dto(db, a)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/preparation-approvals/{id}/revoke")
def revoke(id: int, body: RevokeInput, who=Depends(require("products.prepare.approve")),
           db: Session = Depends(database)):
    a = approval_for(db, who, id)
    if a.version != body.expected_version or a.state != "active":
        raise HTTPException(409, "A jóváhagyást időközben módosították. Töltsd be újra.")
    a.state, a.version = "revoked", a.version + 1
    a.revoked_by, a.revoked_at, a.revoke_reason = who.user.id, now(), body.reason
    a.counts = {**a.counts, "valid": 0, "invalid": a.counts.get("approved", 0)}
    audit(db, who, "products.preparation_revoke", str(a.id), a.tenant_id, reason=body.reason)
    db.commit()
    return approval_dto(db, a)


@router.get("/products/{id}/preparation")
def product_preparation(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    from app.workspace_views import load_product

    p, _, _, _ = load_product(db, who, id)
    row = db.execute(
        select(PreparationApprovalItem, PreparationApproval)
        .join(PreparationApproval, PreparationApproval.id == PreparationApprovalItem.approval_id)
        .where(PreparationApprovalItem.tenant_id == p.tenant_id, PreparationApprovalItem.product_id == p.id,
               PreparationApproval.state == "active")
        .order_by(PreparationApproval.id.desc()).limit(1)
    ).first()
    result = {"product_id": p.id, "revision": p.revision, "approval": None}
    if row is not None:
        i, a = row
        ok, why = item_validity(a, i, p.revision, schema_current(db, a))
        result["approval"] = {"id": a.id, "approved_at": a.approved_at.isoformat(),
                              "product_revision": i.product_revision, "valid": ok, "invalid_reason": why,
                              "research_targets": i.research_targets,
                              "mandatory_research_targets": i.mandatory_research_targets}
    return result
