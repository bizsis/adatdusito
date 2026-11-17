"""UNAS-REF-01 API: schema registry, eMAG-UNAS parameter mappings, reference-source usage
permission and the column plan for the (separately developed) template generator.

Reading needs reference.read; every decision (mapping approval, usage permission) needs the
system-level reference.manage and is audited. CSRF/Origin/no-store apply as for every route.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.import_parser import FIELDS
from app.import_parser import norm as header_norm
from app.models import now
from app.reference_products import USAGE_STATUSES, fold
from app.security import audit, database, require
from app.unas_models import (
    ParameterMapping,
    ReferenceImportRun,
    ReferenceProduct,
    ReferenceProductSource,
    UnasFieldDefinition,
    UnasParameterDefinition,
)

router = APIRouter(prefix="/api/v1/unas", tags=["UNAS sématár és referencia"])

# Unit conversion factors to the target unit (value_target = value_source * factor).
UNIT_FACTORS = {
    ("mm", "cm"): Decimal("0.1"), ("cm", "mm"): Decimal("10"), ("m", "cm"): Decimal("100"),
    ("cm", "m"): Decimal("0.01"), ("mm", "m"): Decimal("0.001"), ("m", "mm"): Decimal("1000"),
    ("g", "kg"): Decimal("0.001"), ("kg", "g"): Decimal("1000"),
    ("ml", "l"): Decimal("0.001"), ("l", "ml"): Decimal("1000"),
}
# Seed vocabulary for automatic *proposals* (folded eMAG name -> folded UNAS parameter name).
# Proposals are never active; an administrator approves or rejects each one.
SYNONYMS = {
    "brand": "marka", "marca": "marka", "marka": "marka",
    "width": "szelesseg", "latime": "szelesseg", "szelesseg": "szelesseg",
    "height": "magassag", "inaltime": "magassag", "magassag": "magassag",
    "length": "hosszusag", "lungime": "hosszusag", "hosszusag": "hosszusag",
    "material": "anyag", "anyag": "anyag",
    "size": "meret", "marime": "meret", "meret": "meret",
}
# Internal import fields (app.import_parser.FIELDS) that already cover a standard UNAS column.
INTERNAL_TO_UNAS = {
    "sku": "Cikkszám", "name": "Termék Név", "category": "Kategória",
    "description": "Tulajdonságok", "images": "Kép link", "stock": "Raktárkészlet",
    "unit": "Egység", "weight": "Tömeg",
}


def unit_factor(unit_from, unit_to):
    if not unit_from or not unit_to or unit_from == unit_to:
        return Decimal("1") if unit_from == unit_to else None
    factor = UNIT_FACTORS.get((unit_from.casefold(), unit_to.casefold()))
    if factor is None:
        raise HTTPException(422, "Nem támogatott mértékegység-átváltás.")
    return factor


def convert(value, mapping):
    """Apply an approved mapping's unit conversion to a numeric text value."""
    if mapping.unit_factor is None:
        return value
    return format((Decimal(str(value).replace(",", ".")) * mapping.unit_factor).normalize(), "f")


def mapping_key(emag_category_id, emag_parameter_id, unas_parameter_id, unas_field_id):
    return ":".join(str(x if x is not None else "*") for x in (
        emag_category_id, emag_parameter_id,
        f"p{unas_parameter_id}" if unas_parameter_id else "-",
        f"f{unas_field_id}" if unas_field_id else "-"))


def mapping_dto(m):
    return {k: getattr(m, k) for k in (
        "id", "emag_category_id", "emag_parameter_id", "emag_parameter_name",
        "unas_parameter_id", "unas_field_id", "unit_from", "unit_to", "status", "origin",
        "reason", "decided_by", "decided_at", "created_at")} | {
        "unit_factor": str(m.unit_factor) if m.unit_factor is not None else None,
        "confidence": str(m.confidence) if m.confidence is not None else None,
    }


# --- schema registry ------------------------------------------------------------------------


@router.get("/schemas")
def schemas(who=Depends(require("reference.read")), db: Session = Depends(database)):
    rows = db.execute(select(UnasFieldDefinition.schema_source,
                             UnasFieldDefinition.store_key,
                             UnasFieldDefinition.source_version, func.count())
                      .group_by(UnasFieldDefinition.schema_source, UnasFieldDefinition.store_key,
                                UnasFieldDefinition.source_version)
                      .order_by(UnasFieldDefinition.schema_source))
    return [{"schema_source": s, "store_key": k, "source_version": v, "fields": n}
            for s, k, v, n in rows]


@router.get("/fields")
def fields(
    schema_source: str = Query(..., max_length=160),
    scope: str | None = Query(None, pattern="^(standard|store_specific|unknown)$"),
    requirement: str | None = Query(None, pattern="^(required|recommended|optional)$"),
    who=Depends(require("reference.read")),
    db: Session = Depends(database),
):
    stmt = select(UnasFieldDefinition).where(UnasFieldDefinition.schema_source == schema_source)
    if scope:
        stmt = stmt.where(UnasFieldDefinition.scope == scope)
    if requirement:
        stmt = stmt.where(UnasFieldDefinition.requirement == requirement)
    return [{k: getattr(f, k) for k in (
        "id", "position", "header", "field_key", "scope", "field_group", "data_type",
        "requirement", "requirement_source", "importable", "default_value", "validation",
        "note", "profile", "source_version", "store_key")}
        for f in db.scalars(stmt.order_by(UnasFieldDefinition.position))]


@router.get("/parameters")
def parameters(
    schema_source: str = Query(..., max_length=160),
    who=Depends(require("reference.read")),
    db: Session = Depends(database),
):
    return [{k: getattr(p, k) for k in (
        "id", "field_id", "name", "group_name", "param_type", "unit", "unit_source",
        "settings", "header")}
        for p in db.scalars(select(UnasParameterDefinition)
                            .where(UnasParameterDefinition.schema_source == schema_source)
                            .order_by(UnasParameterDefinition.id))]


# --- eMAG-UNAS parameter mappings -------------------------------------------------------------


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emag_category_id: int | None = Field(None, gt=0)
    emag_parameter_id: int = Field(gt=0)
    emag_parameter_name: str = Field(min_length=1, max_length=255)
    unas_parameter_id: int | None = Field(None, gt=0)
    unas_field_id: int | None = Field(None, gt=0)
    unit_from: str | None = Field(None, max_length=32)
    unit_to: str | None = Field(None, max_length=32)
    reason: str | None = Field(None, max_length=500)


def create_mapping(db, body, origin, actor_id=None, confidence=None):
    if (body.unas_parameter_id is None) == (body.unas_field_id is None):
        raise HTTPException(422, "Pontosan egy UNAS-paraméter vagy -mező adható meg.")
    if body.unas_parameter_id and not db.get(UnasParameterDefinition, body.unas_parameter_id):
        raise HTTPException(404, "Az UNAS-paraméter nem található.")
    if body.unas_field_id and not db.get(UnasFieldDefinition, body.unas_field_id):
        raise HTTPException(404, "Az UNAS-mező nem található.")
    key = mapping_key(body.emag_category_id, body.emag_parameter_id, body.unas_parameter_id,
                      body.unas_field_id)
    existing = db.scalar(select(ParameterMapping).where(ParameterMapping.mapping_key == key))
    if existing:
        return existing, False
    mapping = ParameterMapping(
        mapping_key=key, emag_category_id=body.emag_category_id,
        emag_parameter_id=body.emag_parameter_id, emag_parameter_name=body.emag_parameter_name,
        unas_parameter_id=body.unas_parameter_id, unas_field_id=body.unas_field_id,
        unit_from=body.unit_from, unit_to=body.unit_to,
        unit_factor=unit_factor(body.unit_from, body.unit_to), status="proposed",
        origin=origin, confidence=confidence, reason=body.reason, created_by=actor_id,
    )
    db.add(mapping)
    db.flush()
    return mapping, True


def propose(db, schema_source, emag_parameters):
    """Automatic proposals by exact folded name or the seed synonym vocabulary.

    emag_parameters: iterable of {category_id, parameter_id, name, unit?}. Two UNAS
    parameters with the same name in different groups are never merged: such a name gets no
    automatic proposal.
    """
    by_name = {}
    for p in db.scalars(select(UnasParameterDefinition)
                        .where(UnasParameterDefinition.schema_source == schema_source)):
        by_name.setdefault(fold(p.name), []).append(p)
    created = []
    for e in emag_parameters:
        name = fold(e["name"])
        target = by_name.get(SYNONYMS.get(name, name), [])
        if len(target) != 1:
            continue  # unknown or ambiguous (same name in several groups)
        unas = target[0]
        unit_from = e.get("unit")
        body = MappingInput(emag_category_id=e.get("category_id"),
                            emag_parameter_id=e["parameter_id"], emag_parameter_name=e["name"],
                            unas_parameter_id=unas.id,
                            unit_from=unit_from if unas.unit and unit_from else None,
                            unit_to=unas.unit if unas.unit and unit_from else None,
                            reason="Automatikus javaslat név/szinonima alapján.")
        try:
            mapping, new = create_mapping(db, body, "automatic", None, Decimal("0.6"))
        except HTTPException:
            continue  # e.g. unsupported unit pair: left for a manual decision
        if new:
            created.append(mapping)
    return created


def active_emag_parameters(db):
    """eMAG parameters of the active owned catalog version (never pinfo_db writes)."""
    from app import catalog_store
    from app.models import CatalogLinkEntry

    version = catalog_store.active_version(db)
    if not version:
        raise HTTPException(409, "Nincs aktív közös katalógusverzió.")
    data_version = catalog_store.data_version_id(db, version)
    return [{"category_id": e.category_id, "parameter_id": e.emag_parameter_id, "name": e.name}
            for e in db.scalars(select(CatalogLinkEntry)
                                .where(CatalogLinkEntry.version_id == data_version))]


@router.get("/parameter-mappings")
def list_mappings(
    status: str | None = Query(None, pattern="^(proposed|approved|rejected)$"),
    emag_parameter_id: int | None = Query(None, gt=0),
    offset: int = Query(0, ge=0),
    who=Depends(require("reference.read")),
    db: Session = Depends(database),
):
    stmt = select(ParameterMapping)
    if status:
        stmt = stmt.where(ParameterMapping.status == status)
    if emag_parameter_id:
        stmt = stmt.where(ParameterMapping.emag_parameter_id == emag_parameter_id)
    return [mapping_dto(m) for m in
            db.scalars(stmt.order_by(ParameterMapping.id).offset(offset).limit(100))]


@router.post("/parameter-mappings")
def add_mapping(body: MappingInput, who=Depends(require("reference.manage")),
                db: Session = Depends(database)):
    mapping, new = create_mapping(db, body, "manual", who.user.id)
    if not new:
        raise HTTPException(409, "Ez a megfeleltetés már létezik.")
    audit(db, who, "unas.mapping_create", mapping.id, key=mapping.mapping_key)
    db.commit()
    return mapping_dto(mapping)


class ProposeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_source: str = Field(min_length=1, max_length=160)


@router.post("/parameter-mappings/propose")
def propose_mappings(body: ProposeInput, who=Depends(require("reference.manage")),
                     db: Session = Depends(database)):
    created = propose(db, body.schema_source, active_emag_parameters(db))
    audit(db, who, "unas.mapping_propose", body.schema_source, created=len(created))
    db.commit()
    return {"created": len(created), "items": [mapping_dto(m) for m in created]}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, max_length=500)


@router.post("/parameter-mappings/{id}/{decision}")
def decide_mapping(id: int, decision: str, body: Decision,
                   who=Depends(require("reference.manage")), db: Session = Depends(database)):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Ismeretlen művelet.")
    mapping = db.scalar(select(ParameterMapping).where(ParameterMapping.id == id)
                        .with_for_update())
    if not mapping:
        raise HTTPException(404, "A megfeleltetés nem található.")
    if mapping.status != "proposed":
        raise HTTPException(409, "Csak javasolt megfeleltetésről lehet dönteni.")
    mapping.status = "approved" if decision == "approve" else "rejected"
    mapping.decided_by, mapping.decided_at = who.user.id, now()
    if body.reason:
        mapping.reason = body.reason
    audit(db, who, "unas.mapping_" + decision, mapping.id, key=mapping.mapping_key)
    db.commit()
    return mapping_dto(mapping)


# --- reference sources --------------------------------------------------------------------


def source_dto(db, s):
    last = db.scalar(select(ReferenceImportRun).where(ReferenceImportRun.source_id == s.id)
                     .order_by(ReferenceImportRun.id.desc()).limit(1))
    return {
        **{k: getattr(s, k) for k in (
            "id", "key", "name", "kind", "store_key", "schema_source", "usage_status",
            "enrichment_enabled", "usage_note", "usage_decided_by", "usage_decided_at",
            "excluded_columns", "created_at")},
        "products": db.scalar(select(func.count()).select_from(ReferenceProduct)
                              .where(ReferenceProduct.source_id == s.id)),
        "last_import": None if not last else {
            "id": last.id, "state": last.state, "counters": last.counters,
            "file_name": last.file_name, "finished_at": last.finished_at},
    }


@router.get("/reference-sources")
def sources(who=Depends(require("reference.manage")), db: Session = Depends(database)):
    return [source_dto(db, s) for s in
            db.scalars(select(ReferenceProductSource).order_by(ReferenceProductSource.id))]


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usage_status: str
    enrichment_enabled: bool = False
    usage_note: str = Field(min_length=3, max_length=1000)


@router.put("/reference-sources/{id}/usage")
def set_usage(id: int, body: Usage, who=Depends(require("reference.manage")),
              db: Session = Depends(database)):
    if body.usage_status not in USAGE_STATUSES:
        raise HTTPException(422, "Ismeretlen felhasználási állapot.")
    if body.enrichment_enabled and body.usage_status != "approved_enrichment":
        raise HTTPException(422, "Dúsításhoz jóváhagyott felhasználási jog szükséges.")
    source = db.scalar(select(ReferenceProductSource).where(ReferenceProductSource.id == id)
                       .with_for_update())
    if not source:
        raise HTTPException(404, "A forrás nem található.")
    before = {"usage_status": source.usage_status, "enrichment": source.enrichment_enabled}
    source.usage_status = body.usage_status
    source.enrichment_enabled = body.enrichment_enabled
    source.usage_note = body.usage_note
    source.usage_decided_by, source.usage_decided_at = who.user.id, now()
    audit(db, who, "unas.reference_usage", source.id, before=before,
          after={"usage_status": body.usage_status, "enrichment": body.enrichment_enabled})
    db.commit()
    return source_dto(db, source)


# --- template generator interface -----------------------------------------------------------


class EmagParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_id: int | None = None
    parameter_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)


class TemplatePlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_source: str = Field(min_length=1, max_length=160)
    supplier_headers: list[str] = Field(max_length=512)
    emag_parameters: list[EmagParameter] = Field(default_factory=list, max_length=2000)


def template_plan(db, schema_source, supplier_headers, emag_parameters):
    """Column order for the template generator: (1) supplier columns unchanged, (2) missing
    standard UNAS required/recommended columns, (3) eMAG parameters of the category, mapped
    to the UNAS parameter header only through an approved mapping. No column twice."""
    fields_ = list(db.scalars(select(UnasFieldDefinition)
                              .where(UnasFieldDefinition.schema_source == schema_source)
                              .order_by(UnasFieldDefinition.position)))
    if not fields_:
        raise HTTPException(404, "Ismeretlen UNAS-sémaforrás.")
    columns = [{"source": "supplier", "header": h, "covers": None} for h in supplier_headers]
    taken = {header_norm(h) for h in supplier_headers}
    covered = set()
    for h in supplier_headers:
        internal = [k for k, (_, aliases) in FIELDS.items()
                    if header_norm(h) in [header_norm(a) for a in aliases.split()]]
        for k in internal:
            if k in INTERNAL_TO_UNAS:
                covered.add(INTERNAL_TO_UNAS[k])
    for col in columns:
        internal = [k for k, (_, aliases) in FIELDS.items()
                    if header_norm(col["header"]) in [header_norm(a) for a in aliases.split()]]
        col["covers"] = next((INTERNAL_TO_UNAS[k] for k in internal if k in INTERNAL_TO_UNAS),
                             None)
    for f in fields_:
        if (f.scope == "standard" and f.requirement in ("required", "recommended")
                and f.header not in covered and header_norm(f.header) not in taken):
            columns.append({"source": "unas", "header": f.header, "requirement": f.requirement,
                            "field_id": f.id})
            taken.add(header_norm(f.header))
    approved = {}
    for m in db.scalars(select(ParameterMapping).where(ParameterMapping.status == "approved",
                                                       ParameterMapping.unas_parameter_id
                                                       .is_not(None))):
        approved.setdefault(m.emag_parameter_id, []).append(m)
    for e in emag_parameters:
        candidates = [m for m in approved.get(e.parameter_id, [])
                      if m.emag_category_id in (None, e.category_id)]
        candidates.sort(key=lambda m: m.emag_category_id is None)  # category-specific first
        unas = db.get(UnasParameterDefinition, candidates[0].unas_parameter_id) \
            if candidates else None
        header = unas.header if unas and unas.schema_source == schema_source else None
        name = header or f"eMAG: {e.name}"
        if header_norm(name) in taken:
            continue
        columns.append({"source": "emag", "header": name, "emag_parameter_id": e.parameter_id,
                        "mapping_id": candidates[0].id if header else None})
        taken.add(header_norm(name))
    return columns


@router.post("/template-plan")
def plan(body: TemplatePlanInput, who=Depends(require("reference.read")),
         db: Session = Depends(database)):
    return {"schema_source": body.schema_source,
            "columns": template_plan(db, body.schema_source, body.supplier_headers,
                                     body.emag_parameters)}
