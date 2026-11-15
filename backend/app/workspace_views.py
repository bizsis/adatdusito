"""Tenant product workspace: products, own categories and internal classification.

CODEX 07 ingestion is unchanged. CATEGORY-02A adds the classification contract
(docs/design/CATEGORY-02A-API.md). Every endpoint checks the permission and the
selected tenant; the global reference assignment (/reference/navigation/...)
is never used to change a customer's product.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app.import_api import tenant
from app.import_models import Supplier, SupplierProduct
from app.import_parser import FIELDS
from app.models import now
from app.product_models import (
    CategoryMap,
    ProductClassification,
    ProductEvent,
    ProductSourceCategory,
)
from app.security import audit, database, require

router = APIRouter(prefix="/api/v1/workspace", tags=["Termékadatok"])
MAX_PAGE = 100
BATCH = 500


# --- DTOs -------------------------------------------------------------------


def category_ref(row):
    if row is None:
        return None
    return {"id": row.id, "path": row.path_text, "origin": row.origin, "supplier_id": row.supplier_id}


def classification_dto(c):
    if c is None:
        return {
            "status": pc.REVIEW,
            "status_label": pc.STATUS_LABELS[pc.REVIEW],
            "origin": "none",
            "method": None,
            "reason_codes": ["not_classified_yet"],
            "navigation_node_id": None,
            "navigation_path": None,
            "donor_emag_category_id": None,
            "donor_name": None,
            "donor_choices": [],
            "confidence": None,
            "alternatives": [],
            "locked": False,
            "rule_version": None,
            "decided_by": None,
            "decided_at": None,
        }
    node = pc.internal_category(c.navigation_node_id)
    donors = node["donors"] if node else []
    return {
        "status": c.status,
        "status_label": pc.STATUS_LABELS[c.status],
        "origin": c.origin,
        "method": c.method,
        "reason_codes": c.reason_codes or [],
        "navigation_node_id": c.navigation_node_id,
        "navigation_path": node["path"] if node else None,
        "donor_emag_category_id": c.donor_emag_category_id,
        "donor_name": next(
            (d["name"] for d in donors if d["emag_category_id"] == c.donor_emag_category_id),
            None,
        ),
        "donor_choices": donors if len(donors) > 1 else [],
        "confidence": float(c.confidence) if c.confidence is not None else None,
        "alternatives": c.alternatives or [],
        "locked": c.locked,
        "rule_version": c.rule_version,
        "decided_by": c.decided_by,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
    }


def export_category(source, c):
    """Own category first; an unambiguous internal classification is the fallback."""
    if source is not None:
        return {"kind": "own", "path": source.path_text}
    if c is not None and c.status == pc.AUTO and c.navigation_node_id:
        node = pc.internal_category(c.navigation_node_id)
        if node:
            return {"kind": "internal", "path": " > ".join(node["path"])}
    return {"kind": "none", "path": None}


def product_dto(p, supplier_name, source, c):
    return {
        "id": p.id,
        "revision": p.revision,
        "fields": p.data,
        "supplier_id": p.supplier_id,
        "supplier_name": supplier_name,
        "source_line": p.last_line,
        "source_run_id": p.last_run_id,
        "source_category": category_ref(source),
        "classification": classification_dto(c),
        "export_category": export_category(source, c),
    }


def load_product(db, who, id):
    tid = tenant(who)
    row = db.execute(
        select(SupplierProduct, Supplier.name, ProductSourceCategory, ProductClassification)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .outerjoin(ProductSourceCategory, ProductSourceCategory.id == SupplierProduct.source_category_id)
        .outerjoin(ProductClassification, ProductClassification.product_id == SupplierProduct.id)
        .where(SupplierProduct.id == id, SupplierProduct.tenant_id == tid, Supplier.tenant_id == tid)
    ).first()
    if row is None:
        raise HTTPException(404, "A termék nem található.")
    return row


def detail_dto(db, who, row):
    p, supplier_name, source, c = row
    result = product_dto(p, supplier_name, source, c)
    attributes = sorted((p.source_attributes or {}).items(), key=lambda kv: (kv[1].get("column", 0), kv[0]))
    result["source_attributes"] = [pc.expand_attribute(k, v) for k, v in attributes]
    result["events"] = [
        {
            "id": e.id,
            "kind": e.kind,
            "revision": e.revision,
            "actor_id": e.actor_id,
            "run_id": e.run_id,
            "reason": e.reason,
            "before": e.before,
            "after": e.after,
            "created_at": e.created_at.isoformat(),
        }
        for e in db.scalars(
            select(ProductEvent)
            .where(ProductEvent.tenant_id == p.tenant_id, ProductEvent.product_id == p.id)
            .order_by(ProductEvent.id.desc())
            .limit(50)
        )
    ]
    result["capabilities"] = {"classify": "products.classify" in who.permissions}
    return result


# --- products -----------------------------------------------------------------


@router.get("/products")
def products(
    cursor: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    status: Literal["auto_classified", "needs_review"] | None = None,
    origin: Literal["category_map", "manual", "suggestion", "none"] | None = None,
    locked: bool | None = None,
    supplier_id: int | None = Query(None, ge=1),
    source_category_id: int | None = Query(None, ge=1),
    without_source_category: bool = False,
    navigation_node_id: str | None = Query(None, max_length=160),
    q: str | None = Query(None, max_length=120),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    tid = tenant(who)
    conditions = [SupplierProduct.tenant_id == tid, Supplier.tenant_id == tid]
    # Server-side search: every folded term must occur in name, SKU or GTIN.
    # Wildcards are escaped (autoescape); no product is loaded for filtering.
    for term in pc.search_terms(q):
        conditions.append(SupplierProduct.search_text.contains(term, autoescape=True))
    if supplier_id is not None:
        conditions.append(SupplierProduct.supplier_id == supplier_id)
    if source_category_id is not None:
        conditions.append(SupplierProduct.source_category_id == source_category_id)
    if without_source_category:
        conditions.append(SupplierProduct.source_category_id.is_(None))
    if navigation_node_id is not None:
        conditions.append(ProductClassification.navigation_node_id == navigation_node_id)
    if origin is not None:
        conditions.append(ProductClassification.origin == origin)
    if locked is not None:
        conditions.append(ProductClassification.locked == locked)
    base = (
        select(SupplierProduct, Supplier.name, ProductSourceCategory, ProductClassification)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .outerjoin(ProductSourceCategory, ProductSourceCategory.id == SupplierProduct.source_category_id)
        .outerjoin(ProductClassification, ProductClassification.product_id == SupplierProduct.id)
        .where(*conditions)
    )
    status_column = func.coalesce(ProductClassification.status, pc.REVIEW)
    counts = dict(
        db.execute(
            select(status_column, func.count())
            .select_from(SupplierProduct)
            .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
            .outerjoin(ProductClassification, ProductClassification.product_id == SupplierProduct.id)
            .where(*conditions)
            .group_by(status_column)
        ).all()
    )
    if status is not None:
        base = base.where(status_column == status)
    rows = db.execute(
        base.where(SupplierProduct.id > cursor).order_by(SupplierProduct.id).limit(limit + 1)
    ).all()
    return {
        "items": [product_dto(*r) for r in rows[:limit]],
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
        "field_labels": {k: v[0] for k, v in FIELDS.items()},
        "status_counts": {s: counts.get(s, 0) for s in (pc.AUTO, pc.REVIEW)},
        "status_labels": pc.STATUS_LABELS,
    }


@router.get("/products/{id}")
def product(id: int, who=Depends(require("products.read")), db: Session = Depends(database)):
    return detail_dto(db, who, load_product(db, who, id))


class ClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["set", "reset"]
    navigation_node_id: str | None = Field(default=None, max_length=160)
    donor_emag_category_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)


@router.patch("/products/{id}/classification")
def set_classification(
    id: int,
    body: ClassificationInput,
    who=Depends(require("products.classify")),
    db: Session = Depends(database),
):
    p, _, source, current = load_product(db, who, id)
    before = pc.snapshot(current)
    if body.action == "set":
        if not body.navigation_node_id:
            raise HTTPException(422, "Válassz belső kategóriát.")
        donor = pc.validate_target(body.navigation_node_id, body.donor_emag_category_id)
        revision = pc.bump_revision(db, p, body.expected_revision)
        if current is None:
            current = ProductClassification(product_id=p.id, tenant_id=p.tenant_id)
            db.add(current)
        current.status = pc.AUTO
        current.origin = "manual"
        current.method = "manual"
        current.rule_version = pc.RULE_VERSION
        current.reason_codes = ["manual_decision"]
        if donor is None and len(pc.internal_category(body.navigation_node_id)["donors"]) > 1:
            current.reason_codes = ["manual_decision", "parameter_profile_choice_required"]
        current.navigation_node_id = body.navigation_node_id
        current.donor_emag_category_id = donor
        current.confidence = None
        current.alternatives = current.alternatives or []
        current.locked = True
        current.map_revision = None
        current.decided_by = who.user.id
        current.decided_at = now()
        kind = "classification_manual"
    else:
        if body.navigation_node_id or body.donor_emag_category_id:
            raise HTTPException(422, "A visszaállítás nem kombinálható kategóriaválasztással.")
        revision = pc.bump_revision(db, p, body.expected_revision)
        if current is not None:
            current.locked = False
        db.flush()
        pc.classify(
            db, p, pc.maps_for(db, p.tenant_id), pc.auto_threshold(db),
            source.path_text if source else "", record_event=False,
        )
        db.flush()
        current = db.get(ProductClassification, p.id)
        p.revision = revision  # one revision for the whole user action
        kind = "classification_reset"
    db.add(ProductEvent(tenant_id=p.tenant_id, product_id=p.id, revision=revision, kind=kind,
                        actor_id=who.user.id, reason=body.reason, before=before,
                        after=pc.snapshot(current)))
    audit(db, who, "products." + kind, str(p.id), p.tenant_id, before=before,
          after=pc.snapshot(current), reason=body.reason)
    db.commit()
    return detail_dto(db, who, load_product(db, who, id))


# --- own categories and category maps ---------------------------------------


def map_dto(m):
    if m is None:
        return None
    node = pc.internal_category(m.navigation_node_id)
    return {
        "state": m.state,
        "navigation_node_id": m.navigation_node_id,
        "navigation_path": node["path"] if node else None,
        "donor_emag_category_id": m.donor_emag_category_id,
        "revision": m.revision,
        "reason": m.reason,
        "decided_by": m.decided_by,
        "decided_at": m.decided_at.isoformat(),
    }


@router.get("/category-maps")
def category_maps(
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    state: Literal["unmapped", "approved", "rejected"] | None = None,
    supplier_id: int | None = Query(None, ge=1),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    tid = tenant(who)
    stmt = (
        select(ProductSourceCategory, CategoryMap)
        .outerjoin(CategoryMap, CategoryMap.source_category_id == ProductSourceCategory.id)
        .where(ProductSourceCategory.tenant_id == tid, ProductSourceCategory.id > cursor)
    )
    if supplier_id is not None:
        stmt = stmt.where(ProductSourceCategory.supplier_id == supplier_id)
    if state == "unmapped":
        stmt = stmt.where(CategoryMap.source_category_id.is_(None))
    elif state is not None:
        stmt = stmt.where(CategoryMap.state == state)
    rows = db.execute(stmt.order_by(ProductSourceCategory.id).limit(limit + 1)).all()
    page = rows[:limit]
    ids = [s.id for s, _ in page]
    counts = dict(
        db.execute(
            select(SupplierProduct.source_category_id, func.count())
            .where(SupplierProduct.tenant_id == tid, SupplierProduct.source_category_id.in_(ids))
            .group_by(SupplierProduct.source_category_id)
        ).all()
    ) if ids else {}
    return {
        "items": [
            {
                "source_category": category_ref(s),
                "product_count": counts.get(s.id, 0),
                "map": map_dto(m),
                "suggestions": [pc.alternative(k) for k in pc.suggestions(s.path_text)[:3]],
            }
            for s, m in page
        ],
        "next_cursor": page[-1][0].id if len(rows) > limit else None,
    }


class CategoryMapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    state: Literal["approved", "rejected"]
    navigation_node_id: str | None = Field(default=None, max_length=160)
    donor_emag_category_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)


def source_category_for(db, who, id):
    row = db.get(ProductSourceCategory, id)
    if row is None or row.tenant_id != tenant(who):
        raise HTTPException(404, "A saját kategória nem található.")
    return row


def reapply(db, who, source, before, after, reason):
    """Re-run the automatic decision for every unlocked product of one own category."""
    maps = pc.maps_for(db, source.tenant_id)
    threshold = pc.auto_threshold(db)
    changed = skipped = cursor = 0
    while True:
        batch = list(
            db.scalars(
                select(SupplierProduct)
                .where(
                    SupplierProduct.tenant_id == source.tenant_id,
                    SupplierProduct.source_category_id == source.id,
                    SupplierProduct.id > cursor,
                )
                .order_by(SupplierProduct.id)
                .limit(BATCH)
            )
        )
        if not batch:
            break
        for p in batch:
            current = db.get(ProductClassification, p.id)
            if current is not None and current.locked:
                skipped += 1
            elif pc.classify(db, p, maps, threshold, source.path_text, record_event=False):
                changed += 1
        cursor = batch[-1].id
        db.flush()
    db.add(ProductEvent(tenant_id=source.tenant_id, source_category_id=source.id, kind="category_map",
                        actor_id=who.user.id, reason=reason, before=before,
                        after={**(after or {}), "products_changed": changed, "locked_skipped": skipped}))
    return changed, skipped


@router.put("/category-maps/{source_category_id}")
def put_category_map(
    source_category_id: int,
    body: CategoryMapInput,
    who=Depends(require("products.classify")),
    db: Session = Depends(database),
):
    source = source_category_for(db, who, source_category_id)
    current = db.get(CategoryMap, source.id)
    if (current.revision if current else None) != body.expected_revision:
        raise HTTPException(409, "A kategóriatérképet időközben módosították. Töltsd be újra.")
    donor = None
    if body.state == "approved":
        if not body.navigation_node_id:
            raise HTTPException(422, "Válassz belső kategóriát.")
        donor = pc.validate_target(body.navigation_node_id, body.donor_emag_category_id)
    elif body.navigation_node_id or body.donor_emag_category_id:
        raise HTTPException(422, "Elutasított térképhez nem adható meg kategória.")
    before = map_dto(current)
    if current is None:
        current = CategoryMap(source_category_id=source.id, tenant_id=source.tenant_id, revision=0)
        db.add(current)
    current.state = body.state
    current.navigation_node_id = body.navigation_node_id if body.state == "approved" else None
    current.donor_emag_category_id = donor
    current.reason = body.reason
    current.revision += 1
    current.decided_by = who.user.id
    current.decided_at = now()
    db.flush()
    changed, skipped = reapply(db, who, source, before, map_dto(current), body.reason)
    audit(db, who, "products.category_map", str(source.id), source.tenant_id, before=before,
          after=map_dto(current), products_changed=changed, locked_skipped=skipped)
    db.commit()
    return {"source_category": category_ref(source), "map": map_dto(current),
            "products_changed": changed, "locked_skipped": skipped}


@router.delete("/category-maps/{source_category_id}")
def delete_category_map(
    source_category_id: int,
    expected_revision: int = Query(ge=1),
    who=Depends(require("products.classify")),
    db: Session = Depends(database),
):
    source = source_category_for(db, who, source_category_id)
    current = db.get(CategoryMap, source.id)
    if current is None or current.revision != expected_revision:
        raise HTTPException(409, "A kategóriatérképet időközben módosították. Töltsd be újra.")
    before = map_dto(current)
    db.delete(current)
    db.flush()
    changed, skipped = reapply(db, who, source, before, None, None)
    audit(db, who, "products.category_map_deleted", str(source.id), source.tenant_id,
          before=before, products_changed=changed, locked_skipped=skipped)
    db.commit()
    return {"source_category": category_ref(source), "map": None,
            "products_changed": changed, "locked_skipped": skipped}


@router.get("/internal-categories")
def internal_categories(
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    who=Depends(require("products.read")),
):
    needle = pc.fold(q)
    items = [
        {"navigation_node_id": n["id"], "name": n["name"], "path": n["path"], "donors": n["donors"]}
        for n in pc.internal_categories().values()
        if not needle or needle in pc.fold(" > ".join(n["path"]))
    ]
    return {"items": items[offset : offset + limit], "total": len(items), "offset": offset,
            "limit": limit, "rule_version": pc.RULE_VERSION}
