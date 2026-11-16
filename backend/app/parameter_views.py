"""CATEGORY-03A API: parameter diff, slots, manual decisions, aliases, runs.

Contract: docs/design/CATEGORY-03A-API.md. Mounted under /api/v1/workspace by
app.workspace_views. Every endpoint is tenant-scoped (session workspace) and
permission-checked; no AI, no network, no pinfo_db access.
"""

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, not_, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app import product_jobs
from app import product_parameters as pp
from app.import_api import tenant
from app.import_models import Supplier, SupplierProduct
from app.models import CatalogSourceMapping, now
from app.product_models import (
    ParameterAlias,
    ProductClassification,
    ProductEvent,
    ProductParameterValue,
    ProductSourceCategory,
)
from app.security import audit, database, require

router = APIRouter()
MAX_PAGE = 100
GLOBAL_PERMISSION = "parameters.global_aliases.manage"


def load(db, who, id):
    from app.workspace_views import load_product

    return load_product(db, who, id)


def classification_ref(c):
    node = c.navigation_node_id if c else None
    donor = c.donor_emag_category_id if c else None
    return {"navigation_node_id": node, "donor_emag_category_id": donor,
            "parameter_profile_state": pc.parameter_profile_state(node, donor)}


def product_parameters_dto(db, who, p, c, rows=None):
    if rows is None:
        rows = pp.stored_slots(db, [p.id])[p.id].values()
    rows = pp.ordered(list(rows))
    return {
        "product_id": p.id,
        "revision": p.revision,
        "classification": classification_ref(c),
        "catalog_version_id": max((r.catalog_version_id or 0 for r in rows), default=None) or None,
        "rule_version": pp.RULE_VERSION,
        "slots": [pp.slot_dto(r) for r in rows],
        "capabilities": {"edit": "products.parameters" in who.permissions},
    }


# --- profile-state filter (mirrors product_catalog.parameter_profile_state) ---


def profile_state_condition(state):
    cats = pc.internal_categories()
    ready = [(k, d["emag_category_id"]) for k, n in cats.items() for d in n["donors"]
             if d["review_state"] == "reviewed"]
    pending_pairs = [(k, d["emag_category_id"]) for k, n in cats.items() for d in n["donors"]
                     if d["review_state"] == pc.PENDING]
    single_pending = [k for k, n in cats.items()
                      if len(n["donors"]) == 1 and n["donors"][0]["review_state"] == pc.PENDING]
    multi = [k for k, n in cats.items() if len(n["donors"]) > 1]
    pair = tuple_(ProductClassification.navigation_node_id, ProductClassification.donor_emag_category_id)
    no_donor = ProductClassification.donor_emag_category_id.is_(None)
    conditions = {
        "ready": pair.in_(ready),
        "choice_required": and_(no_donor, ProductClassification.navigation_node_id.in_(multi)),
        "pending_review": or_(pair.in_(pending_pairs) if pending_pairs else False,
                              and_(no_donor, ProductClassification.navigation_node_id.in_(single_pending))),
    }
    if state in conditions:
        return conditions[state]
    return or_(ProductClassification.product_id.is_(None),
               not_(or_(*conditions.values())))


# --- diff ---------------------------------------------------------------------

DIFF_FILTERS = ("state", "mandatory_missing", "navigation_node_id", "source_category_id", "supplier_id",
                "parameter_profile_state", "q")


def diff_conditions(tid, filters):
    """WHERE conditions of the parameter diff (also used by 03C selections).

    The query must join Supplier and outer-join ProductClassification.
    """
    slot = ProductParameterValue
    conditions = [SupplierProduct.tenant_id == tid, Supplier.tenant_id == tid]
    for term in pc.search_terms(filters.get("q")):
        conditions.append(SupplierProduct.search_text.contains(term, autoescape=True))
    if filters.get("supplier_id") is not None:
        conditions.append(SupplierProduct.supplier_id == filters["supplier_id"])
    if filters.get("source_category_id") is not None:
        conditions.append(SupplierProduct.source_category_id == filters["source_category_id"])
    if filters.get("navigation_node_id") is not None:
        conditions.append(ProductClassification.navigation_node_id == filters["navigation_node_id"])
    if filters.get("parameter_profile_state") is not None:
        conditions.append(profile_state_condition(filters["parameter_profile_state"]))
    # Filters are driven by ix_product_parameter_state (tenant, state, mandatory, product).
    if filters.get("state") is not None:
        conditions.append(SupplierProduct.id.in_(
            select(slot.product_id).where(slot.tenant_id == tid, slot.state == filters["state"])))
    if filters.get("mandatory_missing") is not None:
        missing = SupplierProduct.id.in_(select(slot.product_id).where(
            slot.tenant_id == tid, slot.state == "missing", slot.mandatory.is_(True)))
        conditions.append(missing if filters["mandatory_missing"] else not_(missing))
    return conditions



@router.get("/parameter-diff")
def parameter_diff(
    cursor: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    state: Literal["present", "missing", "review", "conflict", "invalid", "source_only", "detached"]
    | None = None,
    mandatory_missing: bool | None = None,
    navigation_node_id: str | None = Query(None, max_length=160),
    source_category_id: int | None = Query(None, ge=1),
    supplier_id: int | None = Query(None, ge=1),
    parameter_profile_state: Literal["ready", "choice_required", "pending_review", "none"] | None = None,
    q: str | None = Query(None, max_length=120),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    tid = tenant(who)
    slot = ProductParameterValue
    conditions = diff_conditions(tid, dict(
        state=state, mandatory_missing=mandatory_missing, navigation_node_id=navigation_node_id,
        source_category_id=source_category_id, supplier_id=supplier_id,
        parameter_profile_state=parameter_profile_state, q=q)) + [SupplierProduct.id > cursor]
    rows = db.execute(
        select(SupplierProduct, ProductClassification)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .outerjoin(ProductClassification, ProductClassification.product_id == SupplierProduct.id)
        .where(*conditions)
        .order_by(SupplierProduct.id)
        .limit(limit + 1)
    ).all()
    page = rows[:limit]
    ids = [p.id for p, _ in page]
    counts, mandatory, versions = {}, {}, {}
    if ids:
        for pid, st, is_mandatory, n in db.execute(
            select(slot.product_id, slot.state, slot.mandatory, func.count())
            .where(slot.product_id.in_(ids))
            .group_by(slot.product_id, slot.state, slot.mandatory)
        ):
            counts.setdefault(pid, {})[st] = counts.get(pid, {}).get(st, 0) + n
            if st == "missing" and is_mandatory:
                mandatory[pid] = mandatory.get(pid, 0) + n
        for pid, rule, catalog in db.execute(
            select(slot.product_id, func.max(slot.rule_version), func.max(slot.catalog_version_id))
            .where(slot.product_id.in_(ids)).group_by(slot.product_id)
        ):
            versions[pid] = (rule, catalog)
    items = []
    for p, c in page:
        ref = classification_ref(c)
        node = pc.internal_category(ref["navigation_node_id"])
        items.append({
            "product_id": p.id, "revision": p.revision,
            "name": (p.data or {}).get("name"), "sku": (p.data or {}).get("sku"),
            **ref, "navigation_path": node["path"] if node else None,
            "counts": {s: counts.get(p.id, {}).get(s, 0) for s in pp.STATES},
            "mandatory_missing": mandatory.get(p.id, 0),
            "prepared": p.id in counts,
            "rule_version": versions.get(p.id, (None, None))[0],
            "catalog_version_id": versions.get(p.id, (None, None))[1],
        })
    return {"items": items, "next_cursor": page[-1][0].id if len(rows) > limit else None,
            "state_labels": pp.STATE_LABELS}


# --- one product --------------------------------------------------------------


@router.get("/products/{id}/parameters")
def product_parameters(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    p, _, _, c = load(db, who, id)
    return product_parameters_dto(db, who, p, c)


@router.post("/products/{id}/parameters/preview")
def preview(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    p, _, _, c = load(db, who, id)
    catalog = pp.active_catalog(db)
    _, existing, decisions = pp.compute(db, p, catalog, {})
    rows = []
    for key, change, before, after in decisions:
        if after is not None:
            locked = existing[key].locked if key in existing else False
            rows.append(pp.Row(key, after, locked))
    result = product_parameters_dto(db, who, p, c, rows)
    result["changes"] = [{"slot_key": k, "change": "blocked_locked" if ch.startswith("blocked") else ch,
                          "before": pp.short(b), "after": pp.short(a)} for k, ch, b, a in decisions]
    result["summary"] = pp.summary(decisions)
    db.rollback()
    return result


class ApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


@router.post("/products/{id}/parameters/apply")
def apply_product(id: int, body: ApplyInput, who=Depends(require("products.parameters")),
                  db: Session = Depends(database)):
    p, _, _, c = load(db, who, id)
    catalog = pp.active_catalog(db)
    _, existing, decisions = pp.compute(db, p, catalog, {})
    if any(change not in ("keep", "blocked_locked") for _, change, _, _ in decisions):
        pc.bump_revision(db, p, body.expected_revision)  # atomic; 409 when stale
        pp.apply(db, p, decisions, existing, actor_id=who.user.id, bump=False)
        audit(db, who, "products.parameter_apply", str(p.id), p.tenant_id, summary=pp.summary(decisions))
    elif p.revision != body.expected_revision:
        raise HTTPException(409, "A terméket időközben módosították. Töltsd be újra a friss állapotot.")
    db.commit()
    p, _, _, c = load(db, who, id)
    result = product_parameters_dto(db, who, p, c)
    result["applied"] = pp.summary(decisions)
    return result


class SlotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["set", "accept_candidate", "lock", "unlock", "reset"]
    value: str | None = Field(default=None, max_length=1000)
    unit: str | None = Field(default=None, max_length=24)
    value_id: int | None = Field(default=None, ge=1)
    source_key: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


def allowed_value(db, catalog, link_id, value_id):
    from app.models import CatalogValue

    row = db.execute(
        select(CatalogValue.id, CatalogValue.value_text)
        .join(CatalogSourceMapping, CatalogSourceMapping.target_id == CatalogValue.id)
        .where(CatalogSourceMapping.version_id == catalog.data_version, CatalogSourceMapping.kind == "value",
               CatalogSourceMapping.context_id == link_id, CatalogValue.id == value_id)
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(422, "A megadott érték nem szerepel a paraméter megengedett értékei között.")
    return row


@router.patch("/products/{id}/parameters/{slot_key:path}")
def set_slot(id: int, slot_key: str, body: SlotInput, who=Depends(require("products.parameters")),
             db: Session = Depends(database)):
    p, _, _, c = load(db, who, id)
    row = db.get(ProductParameterValue, (p.id, slot_key))
    if row is None or row.tenant_id != p.tenant_id:
        raise HTTPException(404, "A paraméterhely nem található.")
    before = pp.view(row)
    before_locked = row.locked
    if body.action == "set":
        if body.value in (None, "") and body.value_id is None:
            raise HTTPException(422, "Adj meg értéket.")
        value, value_id = body.value, None
        if row.catalog_link_id is not None and (row.details or {}).get("allow_new_value") is False:
            if body.value_id is None:
                raise HTTPException(422, "Kötött értékkészlet: válassz megengedett értéket (value_id).")
            value_id, value = allowed_value(db, pp.active_catalog(db), row.catalog_link_id, body.value_id)
        pc.bump_revision(db, p, body.expected_revision)
        row.value, row.unit, row.value_id = value, body.unit, value_id
        row.state, row.origin, row.locked = "present", "user", True
        row.reason_codes = ["manual_decision"]
    elif body.action == "accept_candidate":
        if not body.source_key:
            raise HTTPException(422, "Válassz forrást (source_key).")
        details = row.details or {}
        known = {x.get("source_key") for x in details.get("candidates", [])} | {
            s["key"] for s in details.get("sources", [])}
        source = next((s for s in pp.sources_of(p) if s["key"] == body.source_key), None)
        if body.source_key not in known or source is None:
            raise HTTPException(422, "A forrás nem jelöltje ennek a helynek.")
        result = {"value": source["raw"], "unit": source["unit"], "value_id": None, "state": "present"}
        if row.catalog_link_id is not None:
            catalog = pp.active_catalog(db)
            param = next((x for x in catalog.parameters(row.donor_emag_category_id)
                          if x["emag_parameter_id"] == row.emag_parameter_id), None)
            if param is None:
                raise HTTPException(422, "A paraméter már nem része a donorprofilnak.")
            result = pp.evaluate(source, param, catalog)
            if result["state"] == "invalid":
                raise HTTPException(422, "A forrásérték ehhez a paraméterhez érvénytelen.")
        pc.bump_revision(db, p, body.expected_revision)
        row.value, row.unit, row.value_id = result["value"], result["unit"], result["value_id"]
        row.state, row.origin, row.locked = "present", "user", True
        row.reason_codes = ["manual_decision"]
        row.details = {**details, "sources": [pp.public_source(source)], "candidates": [],
                       "unit_conversion": result.get("conversion")}
    elif body.action in ("lock", "unlock"):
        pc.bump_revision(db, p, body.expected_revision)
        row.locked = body.action == "lock"
    else:  # reset
        catalog = pp.active_catalog(db)
        pc.bump_revision(db, p, body.expected_revision)
        row.locked = False
        db.flush()
        _, existing, decisions = pp.compute(db, p, catalog, {})
        decision = [d for d in decisions if d[0] == slot_key]
        pp.apply(db, p, decision, existing, actor_id=who.user.id, bump=False)
        row = db.get(ProductParameterValue, (p.id, slot_key))
    if row is not None and body.action != "reset":
        row.updated_by, row.updated_at = who.user.id, now()
    after = pp.view(row) if row is not None else None
    event_before = {**pp.short(before), "locked": before_locked}
    event_after = {**pp.short(after), "locked": row.locked} if row is not None else None
    db.add(ProductEvent(tenant_id=p.tenant_id, product_id=p.id, revision=p.revision, kind="parameter_manual",
                        actor_id=who.user.id, reason=body.reason, before={"slot_key": slot_key, **event_before},
                        after={"slot_key": slot_key, "action": body.action, **(event_after or {})}))
    audit(db, who, "products.parameter_" + body.action, f"{p.id}:{slot_key}", p.tenant_id,
          before=event_before, after=event_after, reason=body.reason)
    db.commit()
    p, _, _, c = load(db, who, id)
    return product_parameters_dto(db, who, p, c)


# --- aliases ------------------------------------------------------------------


def alias_dto(a):
    return {"id": a.id, "version": a.version, "scope": "global" if a.tenant_id is None else "tenant",
            "state": a.state, "label": a.label, "label_key": a.label_key, "unit": a.unit or None,
            "emag_parameter_id": a.emag_parameter_id, "scope_emag_category_id": a.scope_emag_category_id,
            "reason": a.reason, "decided_by": a.decided_by,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None}


def require_alias_permission(who, scope):
    needed = GLOBAL_PERMISSION if scope == "global" else "products.parameters"
    if needed not in who.permissions:
        raise HTTPException(403, "Nincs jogosultság ehhez az aliashoz.")


@router.get("/parameter-aliases")
def aliases(
    scope: Literal["tenant", "global", "all"] = "all",
    state: Literal["approved", "revoked"] = "approved",
    emag_parameter_id: int | None = Query(None, ge=1),
    q: str | None = Query(None, max_length=160),
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    tid = tenant(who)
    scopes = {"tenant": ParameterAlias.tenant_id == tid, "global": ParameterAlias.tenant_id.is_(None),
              "all": or_(ParameterAlias.tenant_id == tid, ParameterAlias.tenant_id.is_(None))}
    query = select(ParameterAlias).where(scopes[scope], ParameterAlias.state == state,
                                         ParameterAlias.id > cursor)
    if emag_parameter_id is not None:
        query = query.where(ParameterAlias.emag_parameter_id == emag_parameter_id)
    if q:
        query = query.where(ParameterAlias.label_key.contains(pp.label_key(q), autoescape=True))
    rows = list(db.scalars(query.order_by(ParameterAlias.id).limit(limit + 1)))
    return {"items": [alias_dto(a) for a in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


class AliasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["tenant", "global"]
    label: str = Field(min_length=1, max_length=160)
    unit: str | None = Field(default=None, max_length=24)
    emag_parameter_id: int = Field(ge=1)
    scope_emag_category_id: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


def active_key(tenant_id, donor, key, unit):
    raw = f"{tenant_id if tenant_id is not None else 'global'}|{donor}|{key}|{pp.unit_key(unit)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post("/parameter-aliases")
def create_alias(body: AliasInput, who=Depends(require("products.read")), db: Session = Depends(database)):
    require_alias_permission(who, body.scope)
    tid = tenant(who)
    key = pp.label_key(body.label)
    if not key:
        raise HTTPException(422, "A címke nem tartalmaz betűt vagy számot.")
    donors = {d["emag_category_id"] for n in pc.internal_categories().values() for d in n["donors"]}
    if body.scope_emag_category_id not in donors:
        raise HTTPException(422, "Ismeretlen donorkategória.")
    catalog = pp.active_catalog(db)
    if body.emag_parameter_id not in {x["emag_parameter_id"] for x in
                                      catalog.parameters(body.scope_emag_category_id)}:
        raise HTTPException(422, "A paraméter nem szerepel a donorkategória paraméterei között.")
    owner = None if body.scope == "global" else tid
    alias = ParameterAlias(
        tenant_id=owner, active_key=active_key(owner, body.scope_emag_category_id, key, body.unit),
        label=body.label.strip(), label_key=key, unit=(body.unit or "").strip(),
        emag_parameter_id=body.emag_parameter_id, scope_emag_category_id=body.scope_emag_category_id,
        state="approved", version=1, reason=body.reason, created_by=who.user.id, decided_by=who.user.id,
        created_at=now(), decided_at=now())
    db.add(alias)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ehhez a címkéhez és egységhez már van jóváhagyott alias.")
    if owner is not None:
        db.add(ProductEvent(tenant_id=owner, kind="parameter_alias", actor_id=who.user.id, reason=body.reason,
                            after={"action": "approve", **alias_dto(alias)}))
    audit(db, who, "parameters.alias_approve", str(alias.id), owner, after=alias_dto(alias))
    db.commit()
    return alias_dto(alias)


@router.delete("/parameter-aliases/{id}")
def revoke_alias(id: int, expected_version: int = Query(ge=1), who=Depends(require("products.read")),
                 db: Session = Depends(database)):
    tid = tenant(who)
    alias = db.get(ParameterAlias, id)
    if alias is None or (alias.tenant_id is not None and alias.tenant_id != tid):
        raise HTTPException(404, "Az alias nem található.")
    require_alias_permission(who, "global" if alias.tenant_id is None else "tenant")
    if alias.version != expected_version or alias.state != "approved":
        raise HTTPException(409, "Az aliast időközben módosították. Töltsd be újra.")
    before = alias_dto(alias)
    alias.state, alias.version, alias.active_key = "revoked", alias.version + 1, None
    alias.decided_by, alias.decided_at = who.user.id, now()
    if alias.tenant_id is not None:
        db.add(ProductEvent(tenant_id=alias.tenant_id, kind="parameter_alias", actor_id=who.user.id,
                            before=before, after={"action": "revoke", **alias_dto(alias)}))
    audit(db, who, "parameters.alias_revoke", str(alias.id), alias.tenant_id, before=before,
          after=alias_dto(alias))
    db.commit()
    return alias_dto(alias)


# --- runs ---------------------------------------------------------------------


class RunScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_category_id: int | None = Field(default=None, ge=1)
    navigation_node_id: str | None = Field(default=None, max_length=160)
    supplier_id: int | None = Field(default=None, ge=1)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview", "apply"]
    scope: RunScope = Field(default_factory=RunScope)
    start_after_product_id: int = Field(default=0, ge=0)


@router.post("/parameter-runs")
def create_run(body: RunInput, who=Depends(require("products.parameters")), db: Session = Depends(database)):
    tid = tenant(who)
    scope = body.scope.model_dump()
    if scope["source_category_id"]:
        source = db.get(ProductSourceCategory, scope["source_category_id"])
        if source is None or source.tenant_id != tid:
            raise HTTPException(404, "A saját kategória nem található.")
    if scope["supplier_id"]:
        supplier = db.get(Supplier, scope["supplier_id"])
        if supplier is None or supplier.tenant_id != tid:
            raise HTTPException(404, "A beszállító nem található.")
    if scope["navigation_node_id"] and pc.internal_category(scope["navigation_node_id"]) is None:
        raise HTTPException(422, "Ismeretlen vagy nem besorolható belső kategória.")
    pp.active_catalog(db)  # 503 before queueing work that cannot produce slots
    job = product_jobs.create_parameter_job(db, tid, body.mode, scope, body.start_after_product_id)
    audit(db, who, "products.parameter_run", str(job.id), tid, mode=body.mode, scope=scope,
          start_after_product_id=body.start_after_product_id)
    db.commit()
    result = {"job": product_jobs.parameter_job_dto(job)}
    try:
        product_jobs.enqueue_parameters(job.id)
    except Exception:  # broker down: the job stays pending and resumable
        result["enqueue_failed"] = True
    return result
