"""KNOWLEDGE-01 API for the KNOWLEDGE-UI-01 administration screens (Codex) and for the
enrichment step. Contract: docs/design/KNOWLEDGE-01.md.

Administration (cross-tenant provenance) needs the system-level reference.manage; every
decision is a knowledge event plus an audit entry. The enrichment plan needs products.read
and returns consolidated values only, never other tenants' records.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import knowledge as kb
from app.knowledge_models import (
    KnowledgeConflict,
    KnowledgeEvent,
    KnowledgeIdentity,
    KnowledgeLink,
    KnowledgeMerge,
    KnowledgeObservation,
    KnowledgeProduct,
    KnowledgeSourceRelation,
    KnowledgeText,
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
            "rejected_values": v.rejected_values or [], "updated_at": v.updated_at,
            "independent_sources": v.independent_sources}


def conflict_dto(c):
    return {"id": c.id, "value_id": c.value_id, "knowledge_product_id": c.knowledge_product_id,
            "attribute_key": c.attribute_key, "kind": c.kind, "candidates": c.candidates,
            "state": c.state, "resolution": c.resolution, "reason": c.reason,
            "resolved_by": c.resolved_by, "resolved_at": c.resolved_at,
            "created_at": c.created_at}


def product_dto(db, p, counts=True):
    out = {"id": p.id, "status": p.status, "display_name": p.display_name, "brand": p.brand,
           "merged_into_id": p.merged_into_id, "created_at": p.created_at,
           "updated_at": p.updated_at}
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
    threshold: Decimal | None = Field(None, ge=0, le=1)  # default: knowledge settings
    texts: list[str] = Field(default_factory=list, max_length=3)


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
    if set(body.texts) - set(kb.TEXT_KINDS):
        raise HTTPException(422, "Ismeretlen szövegtípus.")
    return kb.enrichment_plan(db, body.attributes, body.gtin, body.mpn, body.brand, body.name,
                              body.threshold, tuple(body.texts))


# --- KNOWLEDGE-02 ---------------------------------------------------------------------------------

MERGE_ERRORS = {
    "same_product": "A két termék azonos.",
    "not_found": "A termék nem található.",
    "not_active": "Csak aktív (nem összevont) termékek vonhatók össze.",
    "stale_preview": "Az előnézet óta változott az adat; kérj új előnézetet.",
    "blocked": "Az összevonás nem végezhető el (lásd: blocking).",
    "variant_risk_not_acknowledged": "Változatgyanú: kifejezett nyugtázás szükséges.",
    "not_applied": "Ez az összevonás már vissza van vonva.",
    "later_merge_first": "Előbb a későbbi, érintett összevonást kell visszavonni.",
}


def merge_error(exc):
    """Same envelope as every other error ({"error": {"code", "message"}}, message stays a
    Hungarian string); `merge_error` and `details` are the machine-readable additions."""
    return JSONResponse({"error": {"code": str(exc.status), "message": MERGE_ERRORS[exc.code],
                                   "merge_error": exc.code, "details": exc.details}},
                        status_code=exc.status, headers={"Cache-Control": "no-store"})


def relation_dto(r):
    return {"id": r.id, "source_a_id": r.source_a_id, "source_b_id": r.source_b_id,
            "shared_values": r.shared_values, "identical_values": r.identical_values,
            "identical_texts": r.identical_texts, "ratio": dec(r.ratio), "state": r.state,
            "reason": r.reason, "decided_by": r.decided_by, "decided_at": r.decided_at,
            "updated_at": r.updated_at}


def merge_dto(m):
    return {"id": m.id, "survivor_id": m.survivor_id, "merged_id": m.merged_id,
            "state": m.state, "variant_risk_acknowledged": m.variant_risk_acknowledged,
            "moved": {k: len(v) for k, v in m.moved.items()}, "reason": m.reason,
            "applied_by": m.applied_by, "applied_at": m.applied_at,
            "reverted_by": m.reverted_by, "reverted_at": m.reverted_at,
            "revert_reason": m.revert_reason}


def text_dto(t, source):
    return {"id": t.id, "knowledge_product_id": t.knowledge_product_id, "link_id": t.link_id,
            "source_id": t.source_id, "source_key": source.key, "kind": t.kind,
            "text": t.text, "format": t.format, "language": t.language,
            "language_confidence": dec(t.language_confidence),
            "language_method": t.language_method, "verification": t.verification,
            "usage": t.usage, "pii_flags": t.pii_flags or [],
            "pii_reviewed_by": t.pii_reviewed_by, "current": t.current,
            "observed_at": t.observed_at, "superseded_at": t.superseded_at,
            "usable_for_ai": kb.text_usable(t, source)}


class Required(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class RelationDecision(Required):
    state: str = Field(pattern="^(confirmed_dependent|confirmed_independent)$")


class Lineage(Required):
    lineage_group: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class MergePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    survivor_id: int = Field(gt=0)
    merged_id: int = Field(gt=0)


class MergeApply(MergePreview, Required):
    preview_token: str = Field(min_length=64, max_length=64)
    acknowledge_variant_risk: bool = False


class TextDecision(Required):
    verification: str | None = Field(None, pattern="^(unverified|verified|rejected)$")
    usage: str | None = Field(None, pattern="^(inherited|reuse_allowed|internal_only|restricted)$")
    language: str | None = Field(None, pattern="^([a-z]{2,3}|unknown)$")
    pii_release: bool | None = None


class PiiReview(Required):
    release: bool


@router.get("/source-relations")
def source_relations(state: str | None = Query(None, pattern="^(suspected|below_threshold|"
                                                            "confirmed_dependent|"
                                                            "confirmed_independent)$"),
                     who=Depends(require("reference.manage")), db: Session = Depends(database)):
    stmt = select(KnowledgeSourceRelation)
    if state:
        stmt = stmt.where(KnowledgeSourceRelation.state == state)
    return [relation_dto(r) for r in db.scalars(stmt.order_by(KnowledgeSourceRelation.id))]


@router.post("/source-relations/detect")
def detect(who=Depends(require("reference.manage")), db: Session = Depends(database)):
    changed = kb.detect_relations(db, kb.Context(db))
    if changed:
        kb.refresh_sources(db, changed)
    audit(db, who, "knowledge.relations_detect", "all", changed=len(changed))
    db.commit()
    return {"changed": len(changed)}


@router.post("/source-relations/{id}/decision")
def relation_decision(id: int, body: RelationDecision, who=Depends(require("reference.manage")),
                      db: Session = Depends(database)):
    relation = db.get(KnowledgeSourceRelation, id)
    if relation is None:
        raise HTTPException(404, "A forráskapcsolat nem található.")
    before = relation.state
    relation.state, relation.reason = body.state, body.reason
    relation.decided_by, relation.decided_at = who.user.id, kb.now()
    kb.event(db, "copy_relation_decided", actor_id=who.user.id, relation_id=id,
             before=before, after=body.state, reason=body.reason)
    audit(db, who, "knowledge.relation_decision", id, before=before, after=body.state)
    db.flush()
    kb.refresh_sources(db, [(relation.source_a_id, relation.source_b_id)])
    db.commit()
    return relation_dto(relation)


@router.put("/sources/{id}/lineage")
def lineage(id: int, body: Lineage, who=Depends(require("reference.manage")),
            db: Session = Depends(database)):
    source = db.get(ReferenceProductSource, id)
    if source is None:
        raise HTTPException(404, "A forrás nem található.")
    before = source.lineage_group
    source.lineage_group = body.lineage_group
    kb.event(db, "lineage_changed", actor_id=who.user.id, source_id=id, before=before,
             after=body.lineage_group, reason=body.reason)
    audit(db, who, "knowledge.lineage", id, before=before, after=body.lineage_group)
    db.flush()
    family = {s.id for s in db.scalars(select(ReferenceProductSource).where(
        ReferenceProductSource.lineage_group.in_([g for g in (before, body.lineage_group) if g])))}
    kb.refresh_sources(db, [(id, other) for other in family | {id}])
    db.commit()
    return {"id": id, "lineage_group": source.lineage_group}


@router.post("/merges/preview")
def merges_preview(body: MergePreview, who=Depends(require("reference.manage")),
                   db: Session = Depends(database)):
    try:
        return kb.merge_preview(db, body.survivor_id, body.merged_id)
    except kb.MergeError as exc:
        return merge_error(exc)


@router.post("/merges")
def merges_apply(body: MergeApply, who=Depends(require("reference.manage")),
                 db: Session = Depends(database)):
    for pid in sorted((body.survivor_id, body.merged_id)):  # serialise concurrent merges
        db.scalar(select(KnowledgeProduct).where(KnowledgeProduct.id == pid).with_for_update())
    try:
        record = kb.merge_apply(db, body.survivor_id, body.merged_id, body.preview_token,
                                body.reason, who.user.id, body.acknowledge_variant_risk)
    except kb.MergeError as exc:
        db.rollback()
        return merge_error(exc)
    audit(db, who, "knowledge.merge", record.id, survivor=body.survivor_id,
          merged=body.merged_id, variant_risk_acknowledged=body.acknowledge_variant_risk)
    db.commit()
    return merge_dto(record)


@router.get("/merges")
def merges(state: str | None = Query(None, pattern="^(applied|reverted)$"),
           offset: int = Query(0, ge=0), who=Depends(require("reference.manage")),
           db: Session = Depends(database)):
    stmt = select(KnowledgeMerge)
    if state:
        stmt = stmt.where(KnowledgeMerge.state == state)
    return [merge_dto(m) for m in db.scalars(stmt.order_by(KnowledgeMerge.id.desc())
                                             .offset(offset).limit(100))]


@router.post("/merges/{id}/revert")
def merge_revert(id: int, body: Required, who=Depends(require("reference.manage")),
                 db: Session = Depends(database)):
    record = db.scalar(select(KnowledgeMerge).where(KnowledgeMerge.id == id).with_for_update())
    if record is None:
        raise HTTPException(404, "Az összevonás nem található.")
    try:
        kb.merge_revert(db, record, who.user.id, body.reason)
    except kb.MergeError as exc:
        db.rollback()
        return merge_error(exc)
    audit(db, who, "knowledge.merge_revert", id)
    db.commit()
    return merge_dto(record)


@router.get("/products/{id}/texts")
def texts(id: int, kind: str | None = Query(None, pattern="^(name|short_description|"
                                                           "long_description)$"),
          language: str | None = Query(None, max_length=8),
          usable: str | None = Query(None, pattern="^ai_generation$"),
          include_history: bool = False,
          who=Depends(require("reference.manage")), db: Session = Depends(database)):
    if db.get(KnowledgeProduct, id) is None:
        raise HTTPException(404, "A termék nem található.")
    sources = {s.id: s for s in db.scalars(select(ReferenceProductSource))}
    stmt = select(KnowledgeText).where(KnowledgeText.knowledge_product_id == id)
    if not include_history:
        stmt = stmt.where(KnowledgeText.current.is_(True))
    if kind:
        stmt = stmt.where(KnowledgeText.kind == kind)
    if language:
        stmt = stmt.where(KnowledgeText.language == language)
    items = [text_dto(t, sources[t.source_id]) for t in db.scalars(stmt.order_by(KnowledgeText.id))]
    if usable:
        items = [t for t in items if t["usable_for_ai"]]
    return items


@router.put("/texts/{id}")
def text_decision(id: int, body: TextDecision, who=Depends(require("reference.manage")),
                  db: Session = Depends(database)):
    text = db.scalar(select(KnowledgeText).where(KnowledgeText.id == id).with_for_update())
    if text is None:
        raise HTTPException(404, "A szöveg nem található.")
    kb.decide_text(db, text, who.user.id, body.reason, body.verification, body.usage,
                   body.language, body.pii_release)
    audit(db, who, "knowledge.text", id, verification=text.verification, usage=text.usage,
          language=text.language, pii_reviewed=text.pii_reviewed_by is not None)
    db.commit()
    return text_dto(text, db.get(ReferenceProductSource, text.source_id))


@router.get("/pii-holds")
def pii_holds(offset: int = Query(0, ge=0), who=Depends(require("reference.manage")),
              db: Session = Depends(database)):
    """Values and texts held back because they look like personal data (not yet reviewed)."""
    observations = [{"type": "observation", "id": o.id,
                     "knowledge_product_id": o.knowledge_product_id,
                     "attribute_key": o.attribute_key, "value": o.value_raw,
                     "pii_flags": o.pii_flags, "source_id": o.source_id}
                    for o in db.scalars(select(KnowledgeObservation).where(
                        KnowledgeObservation.current.is_(True),
                        KnowledgeObservation.pii_flags.is_not(None),
                        KnowledgeObservation.pii_reviewed_by.is_(None))
                        .order_by(KnowledgeObservation.id).offset(offset).limit(100))]
    held_texts = [{"type": "text", "id": t.id, "knowledge_product_id": t.knowledge_product_id,
                   "kind": t.kind, "pii_flags": t.pii_flags, "source_id": t.source_id}
                  for t in db.scalars(select(KnowledgeText).where(
                      KnowledgeText.current.is_(True), KnowledgeText.pii_flags.is_not(None),
                      KnowledgeText.pii_reviewed_by.is_(None))
                      .order_by(KnowledgeText.id).offset(offset).limit(100))]
    return {"observations": observations, "texts": held_texts}


@router.post("/observations/{id}/pii-review")
def observation_pii_review(id: int, body: PiiReview, who=Depends(require("reference.manage")),
                           db: Session = Depends(database)):
    obs = db.scalar(select(KnowledgeObservation).where(KnowledgeObservation.id == id)
                    .with_for_update())
    if obs is None or not obs.pii_flags:
        raise HTTPException(404, "Felülvizsgálandó érték nem található.")
    if obs.pii_reviewed_by is not None:
        raise HTTPException(409, "Ezt az értéket már felülvizsgálták.")
    kb.review_observation_pii(db, obs, who.user.id, body.release, body.reason)
    audit(db, who, "knowledge.pii_review", id, released=body.release)
    db.commit()
    return {"id": id, "released": body.release}
