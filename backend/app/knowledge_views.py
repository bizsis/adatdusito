"""KNOWLEDGE-01 API for the KNOWLEDGE-UI-01 administration screens (Codex) and for the
enrichment step. Contract: docs/design/KNOWLEDGE-01.md.

Administration (cross-tenant provenance) needs the system-level reference.manage; every
decision is a knowledge event plus an audit entry. The enrichment plan needs products.read
and returns consolidated values only, never other tenants' records.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import knowledge as kb
from app.knowledge_models import (
    KnowledgeConflict,
    KnowledgeEvent,
    KnowledgeIdentity,
    KnowledgeLink,
    KnowledgeObservation,
    KnowledgeProduct,
    KnowledgeValue,
)
from app.security import audit, database, require
from app.unas_models import ReferenceProductSource

router = APIRouter(prefix="/api/v1/knowledge", tags=["Terméktudásbázis"])
ERRORS = {"unknown_candidate": (422, "Ismeretlen jelölt érték."),
          "no_value": (409, "Ennek a tulajdonságnak nincs értéke.")}


def dec(value):
    return str(value) if value is not None else None


def value_dto(v):
    return {"id": v.id, "attribute_key": v.attribute_key, "label": v.attribute_label,
            "value": v.value_display, "value_norm": v.value_norm, "status": v.status,
            "confidence": dec(v.confidence), "support_sources": v.support_sources,
            "observations": v.observations, "verification_basis": v.verification_basis,
            "verified_by": v.verified_by, "verified_at": v.verified_at,
            "rejected_values": v.rejected_values or [], "updated_at": v.updated_at}


def conflict_dto(c):
    return {"id": c.id, "value_id": c.value_id, "knowledge_product_id": c.knowledge_product_id,
            "attribute_key": c.attribute_key, "kind": c.kind, "candidates": c.candidates,
            "state": c.state, "resolution": c.resolution, "reason": c.reason,
            "resolved_by": c.resolved_by, "resolved_at": c.resolved_at,
            "created_at": c.created_at}


def product_dto(db, p, counts=True):
    out = {"id": p.id, "status": p.status, "display_name": p.display_name, "brand": p.brand,
           "created_at": p.created_at, "updated_at": p.updated_at}
    if counts:
        out["links"] = db.scalar(select(func.count()).select_from(KnowledgeLink).where(
            KnowledgeLink.knowledge_product_id == p.id))
        out["open_conflicts"] = db.scalar(select(func.count()).select_from(KnowledgeConflict)
                                          .where(KnowledgeConflict.knowledge_product_id == p.id,
                                                 KnowledgeConflict.state == "open"))
    return out


def get_value(db, id):
    value = db.scalar(select(KnowledgeValue).where(KnowledgeValue.id == id).with_for_update())
    if value is None:
        raise HTTPException(404, "Az érték nem található.")
    return value


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, max_length=500)


class Verify(Reason):
    value_norm: str | None = Field(None, max_length=1000)


class Rebuild(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: int | None = Field(None, gt=0)
    tenant_id: int | None = Field(None, gt=0)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gtin: str | None = Field(None, max_length=32)
    mpn: str | None = Field(None, max_length=120)
    brand: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=500)
    attributes: list[str] = Field(min_length=1, max_length=500)
    threshold: Decimal = Field(Decimal("0.8"), ge=0, le=1)


@router.get("/stats")
def stats(who=Depends(require("reference.manage")), db: Session = Depends(database)):
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where))

    return {
        "products": count(KnowledgeProduct, KnowledgeProduct.status == "active"),
        "links": count(KnowledgeLink),
        "values": {s: count(KnowledgeValue, KnowledgeValue.status == s)
                   for s in ("candidate", "conflict", "verified")},
        "open_conflicts": count(KnowledgeConflict, KnowledgeConflict.state == "open"),
        "sources": [{"id": s.id, "key": s.key, "kind": s.kind, "usage_status": s.usage_status,
                     "contribution": s.contribution, "permitted": kb.permitted(s),
                     "links": count(KnowledgeLink, KnowledgeLink.source_id == s.id)}
                    for s in db.scalars(select(ReferenceProductSource)
                                        .order_by(ReferenceProductSource.id))],
    }


@router.get("/products")
def products(
    q: str = Query("", max_length=120),
    conflicts: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    who=Depends(require("reference.manage")),
    db: Session = Depends(database),
):
    stmt = select(KnowledgeProduct).where(KnowledgeProduct.status == "active")
    if q:
        folded = kb.fold(q)
        stmt = stmt.where(or_(
            KnowledgeProduct.display_name.contains(q, autoescape=True),
            KnowledgeProduct.id.in_(select(KnowledgeIdentity.knowledge_product_id).where(
                KnowledgeIdentity.value.contains(folded, autoescape=True)))))
    if conflicts:
        stmt = stmt.where(KnowledgeProduct.id.in_(select(
            KnowledgeConflict.knowledge_product_id).where(KnowledgeConflict.state == "open")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(KnowledgeProduct.id).offset(offset).limit(limit))
    return {"items": [product_dto(db, p) for p in items], "total": total, "offset": offset}


@router.get("/products/{id}")
def product(id: int, who=Depends(require("reference.manage")), db: Session = Depends(database)):
    p = db.get(KnowledgeProduct, id)
    if p is None:
        raise HTTPException(404, "A termék nem található.")
    sources = {s.id: s for s in db.scalars(select(ReferenceProductSource))}
    observations = {}
    for o in db.scalars(select(KnowledgeObservation).where(
            KnowledgeObservation.knowledge_product_id == id).order_by(KnowledgeObservation.id)):
        observations.setdefault(o.attribute_key, []).append({
            "id": o.id, "link_id": o.link_id, "source_id": o.source_id,
            "source_key": sources[o.source_id].key, "value": o.value_raw, "unit": o.unit,
            "value_norm": o.value_norm, "origin": o.origin, "confidence": dec(o.confidence),
            "current": o.current, "observed_at": o.observed_at,
            "superseded_at": o.superseded_at})
    return {
        **product_dto(db, p),
        "identities": [{"kind": i.kind, "value": i.value} for i in db.scalars(
            select(KnowledgeIdentity).where(KnowledgeIdentity.knowledge_product_id == id))],
        "links": [{"id": link.id, "member_kind": link.member_kind, "member_id": link.member_id,
                   "source_id": link.source_id, "source_key": sources[link.source_id].key,
                   "tenant_id": link.tenant_id, "method": link.method,
                   "confidence": dec(link.confidence), "decided_by": link.decided_by}
                  for link in db.scalars(select(KnowledgeLink).where(
                      KnowledgeLink.knowledge_product_id == id))],
        "values": [value_dto(v) | {"observations_detail": observations.get(v.attribute_key, [])}
                   for v in db.scalars(select(KnowledgeValue).where(
                       KnowledgeValue.knowledge_product_id == id)
                       .order_by(KnowledgeValue.attribute_key))],
        "conflicts": [conflict_dto(c) for c in db.scalars(select(KnowledgeConflict).where(
            KnowledgeConflict.knowledge_product_id == id).order_by(KnowledgeConflict.id))],
    }


@router.get("/products/{id}/events")
def product_events(id: int, offset: int = Query(0, ge=0),
                   who=Depends(require("reference.manage")), db: Session = Depends(database)):
    return [{"id": e.id, "kind": e.kind, "value_id": e.value_id, "link_id": e.link_id,
             "actor_id": e.actor_id, "details": e.details, "created_at": e.created_at}
            for e in db.scalars(select(KnowledgeEvent).where(
                KnowledgeEvent.knowledge_product_id == id)
                .order_by(KnowledgeEvent.id).offset(offset).limit(100))]


@router.get("/conflicts")
def conflicts(state: str = Query("open", pattern="^(open|resolved)$"),
              offset: int = Query(0, ge=0), who=Depends(require("reference.manage")),
              db: Session = Depends(database)):
    return [conflict_dto(c) for c in db.scalars(
        select(KnowledgeConflict).where(KnowledgeConflict.state == state)
        .order_by(KnowledgeConflict.id).offset(offset).limit(100))]


@router.post("/values/{id}/verify")
def verify(id: int, body: Verify, who=Depends(require("reference.manage")),
           db: Session = Depends(database)):
    value = get_value(db, id)
    try:
        kb.verify_value(db, value, who.user.id, body.value_norm, body.reason)
    except ValueError as exc:
        raise HTTPException(*ERRORS[str(exc)])
    audit(db, who, "knowledge.verify", value.id, value=value.value_norm)
    db.commit()
    return value_dto(value)


@router.post("/values/{id}/reject")
def reject(id: int, body: Reason, who=Depends(require("reference.manage")),
           db: Session = Depends(database)):
    value = get_value(db, id)
    try:
        kb.reject_value(db, value, who.user.id, body.reason)
    except ValueError as exc:
        raise HTTPException(*ERRORS[str(exc)])
    audit(db, who, "knowledge.reject", value.id)
    db.commit()
    return value_dto(value)


@router.post("/conflicts/{id}/resolve")
def resolve(id: int, body: Verify, who=Depends(require("reference.manage")),
            db: Session = Depends(database)):
    conflict = db.get(KnowledgeConflict, id)
    if conflict is None:
        raise HTTPException(404, "Az ellentmondás nem található.")
    if conflict.state != "open":
        raise HTTPException(409, "Az ellentmondás már le van zárva.")
    if body.value_norm is None:
        raise HTTPException(422, "Válassz egy jelölt értéket.")
    if body.value_norm not in {c["value_norm"] for c in conflict.candidates}:
        raise HTTPException(422, "Ismeretlen jelölt érték.")
    value = get_value(db, conflict.value_id)
    kb.verify_value(db, value, who.user.id, body.value_norm, body.reason)
    audit(db, who, "knowledge.resolve", conflict.id, value=body.value_norm)
    db.commit()
    return conflict_dto(conflict) | {"value": value_dto(value)}


@router.post("/links/{id}/unlink")
def unlink(id: int, body: Reason, who=Depends(require("reference.manage")),
           db: Session = Depends(database)):
    link = db.scalar(select(KnowledgeLink).where(KnowledgeLink.id == id).with_for_update())
    if link is None:
        raise HTTPException(404, "A kapcsolat nem található.")
    product = kb.unlink(db, link, who.user.id, body.reason)
    audit(db, who, "knowledge.unlink", link.id, new_product=product.id)
    db.commit()
    return {"link_id": link.id, "knowledge_product_id": product.id}


@router.post("/rebuild")
def rebuild(body: Rebuild, who=Depends(require("reference.manage")),
            db: Session = Depends(database)):
    """Synchronous for one source/tenant; a full rebuild is queued for the worker."""
    if body.source_id is None and body.tenant_id is None:
        kb.schedule()
        audit(db, who, "knowledge.rebuild", "all", queued=True)
        db.commit()
        return {"queued": True}
    counters = kb.rebuild(db, source_id=body.source_id, tenant_id=body.tenant_id)
    audit(db, who, "knowledge.rebuild", body.source_id or f"tenant:{body.tenant_id}",
          **counters)
    db.commit()
    return {"queued": False, "counters": counters}


@router.post("/enrichment-plan")
def enrichment_plan(body: PlanInput, who=Depends(require("products.read")),
                    db: Session = Depends(database)):
    if not any((body.gtin, body.mpn and body.brand, body.brand and body.name)):
        raise HTTPException(422, "GTIN, márka+gyártói cikkszám vagy márka+név szükséges.")
    return kb.enrichment_plan(db, body.attributes, body.gtin, body.mpn, body.brand, body.name,
                              body.threshold)
