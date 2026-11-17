"""KNOWLEDGE-UI-01 system administration. Reuses the reference_products importer."""

import hashlib
from pathlib import Path
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, or_, case
from sqlalchemy.orm import Session

from app.security import require, database, audit
from app.access_control import is_system
from app.models import Audit, Tenant, now
from app.import_models import SupplierProduct, ImportRun
from app.product_models import ProductParameterValue
from app.unas_models import (
    ReferenceProductSource,
    ReferenceProduct,
    ReferenceProductAttribute,
    ReferenceProductIdentifier,
    ReferenceImportRun,
    ReferenceImportChunk,
)
from app import knowledge_uploads as jobs
from app import knowledge_bridge
from app.reference_products import DEFAULT_USAGE_BASIS

router = APIRouter(prefix="/api/v1/knowledge-admin", tags=["Referencia-adatbázisok"])
ACTIVE = ("queued", "analyzing", "queued_import", "converting", "running")


def administrator(
    who=Depends(require("reference.manage")), db: Session = Depends(database)
):
    if not is_system(db, who.user):
        raise HTTPException(403, "Rendszerszintű referenciajogosultság szükséges.")
    if who.session.tenant_id is not None:
        raise HTTPException(409, "Válts Rendszerszint munkaterületre.")
    return who


def get_source(db, id):
    source = db.get(ReferenceProductSource, id)
    if not source:
        raise HTTPException(404, "A referenciaforrás nem található.")
    return source


def get_run(db, id):
    item = db.get(ReferenceImportRun, id)
    if not item:
        raise HTTPException(404, "A referenciaimport nem található.")
    return item


def run_dto(run):
    conf = run.ui_config or {}
    analysis = conf.get("analysis", {})
    mapping = conf.get("mapping", {})
    return {
        "engine": "reference",
        "id": run.id,
        "source_id": run.source_id,
        "file_name": run.file_name,
        "state": run.state,
        "counters": run.counters,
        "errors": run.errors,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "cursor": run.ui_cursor,
        "uploaded": conf.get("web_upload", False),
        "retryable": run.state in ("failed", "cancelled")
        or (
            run.state in ACTIVE
            and (run.ui_lease_until or run.started_at) < now() - timedelta(minutes=15)
        ),
        "headers": analysis.get("headers", []),
        "mapping": mapping,
        "preview": [
            {
                "line": entry["line"],
                "values": [
                    v if mapping.get(str(n)) not in (None, "exclude") else "[Kizárva]"
                    for n, v in enumerate(entry["values"])
                ],
            }
            for entry in conf.get("preview_entries", [])
        ],
        "parser": conf.get("parser", {}),
    }


def supplier_run_dto(run, source_id):
    # These IDs belong to supplier imports, not reference_import_runs. Only safe
    # metadata is returned; no raw rows, private settings or exception bodies.
    return {
        "engine": "supplier",
        "id": run.id,
        "source_id": source_id,
        "file_name": run.filename,
        "state": run.state,
        "counters": {**run.counters, "errors": run.counters.get("error", 0)},
        "errors": [],
        "started_at": run.created_at,
        "finished_at": (
            run.updated_at
            if run.state in ("completed", "partial", "failed", "cancelled")
            else None
        ),
        "cursor": run.cursor,
        "uploaded": False,
        "retryable": False,
        "headers": [],
        "mapping": {},
        "preview": [],
        "parser": {},
    }


def supplier_statistics(db, tenant_id):
    name = SupplierProduct.data["name"].as_string()
    gtin = SupplierProduct.data["gtin"].as_string()
    # The supplier importer stores only validated GTINs in its normalized data.
    total, names, valid = db.execute(
        select(
            func.count(),
            func.sum(case((name.is_not(None) & (name != ""), 1), else_=0)),
            func.sum(case((gtin.is_not(None) & (gtin != ""), 1), else_=0)),
        ).where(SupplierProduct.tenant_id == tenant_id)
    ).one()
    params, attrs = db.execute(
        select(
            func.count(func.distinct(ProductParameterValue.emag_parameter_id)),
            func.count(),
        )
        .join(SupplierProduct, SupplierProduct.id == ProductParameterValue.product_id)
        .where(
            SupplierProduct.tenant_id == tenant_id,
            ProductParameterValue.state == "present",
            ProductParameterValue.slot_key.like("emag:%"),
        )
    ).one()
    updated = db.scalar(
        select(func.max(ImportRun.updated_at))
        .join(SupplierProduct, SupplierProduct.last_run_id == ImportRun.id)
        .where(SupplierProduct.tenant_id == tenant_id)
    )
    last = db.scalar(
        select(ImportRun)
        .where(ImportRun.tenant_id == tenant_id)
        .order_by(ImportRun.id.desc())
        .limit(1)
    )
    return total, updated, 0, names or 0, valid or 0, params, attrs, last


def source_dto(db, source):
    total, last_update, verified, names = db.execute(
        select(
            func.count(),
            func.max(ReferenceProduct.updated_at),
            func.sum(
                case(
                    (ReferenceProduct.verification.in_(("verified", "approved")), 1),
                    else_=0,
                )
            ),
            func.sum(case((ReferenceProduct.name.is_not(None), 1), else_=0)),
        ).where(ReferenceProduct.source_id == source.id)
    ).one()
    valid = (
        db.scalar(
            select(func.count(func.distinct(ReferenceProductIdentifier.product_id)))
            .join(
                ReferenceProduct,
                ReferenceProduct.id == ReferenceProductIdentifier.product_id,
            )
            .where(
                ReferenceProduct.source_id == source.id,
                ReferenceProductIdentifier.kind == "gtin",
                ReferenceProductIdentifier.valid.is_(True),
            )
        )
        or 0
    )
    params, attrs = db.execute(
        select(
            func.count(func.distinct(ReferenceProductAttribute.parameter_id)),
            func.count(),
        )
        .join(
            ReferenceProduct,
            ReferenceProduct.id == ReferenceProductAttribute.product_id,
        )
        .where(ReferenceProduct.source_id == source.id)
    ).one()
    last = db.scalar(
        select(ReferenceImportRun)
        .where(ReferenceImportRun.source_id == source.id)
        .order_by(ReferenceImportRun.id.desc())
        .limit(1)
    )
    last_dto = run_dto(last) if last else None
    if source.kind == "tenant_import" and source.tenant_id is not None:
        total, last_update, verified, names, valid, params, attrs, supplier_last = (
            supplier_statistics(db, source.tenant_id)
        )
        last_dto = supplier_run_dto(supplier_last, source.id) if supplier_last else None
    return {
        "id": source.id,
        "key": source.key,
        "name": source.name,
        "kind": source.kind,
        "tenant_id": source.tenant_id,
        "products": total,
        "parameters": params,
        "attribute_values": attrs,
        "imported_at": source.created_at,
        "updated_at": last_update,
        "state": last_dto["state"] if last_dto else "empty",
        "last_import": last_dto,
        "usage_status": source.usage_status,
        "enrichment_enabled": source.enrichment_enabled,
        "usage_basis": source.usage_basis,
        "usage_note": source.usage_note,
        "trust_level": (
            str(source.trust_level) if source.trust_level is not None else None
        ),
        "contribution": (
            "pending"
            if source.contribution == "pending"
            else (
                "automatic"
                if source.enrichment_enabled
                and source.usage_status == "approved_enrichment"
                and source.contribution == "automatic"
                else "excluded"
            )
        ),
        "quality": {
            "valid_gtin_products": valid,
            "without_valid_gtin": total - valid,
            "with_name": names or 0,
            "verified_products": verified or 0,
        },
        "excluded_columns": source.excluded_columns,
    }


@router.get("/options")
def options(who=Depends(administrator), db: Session = Depends(database)):
    return {
        "knowledge_engine_available": knowledge_bridge.available(),
        "fields": [{"key": key, "label": label} for key, label in jobs.LABELS.items()],
        "tenants": [
            {"id": t.id, "name": t.name}
            for t in db.scalars(
                select(Tenant).where(Tenant.active.is_(True)).order_by(Tenant.name)
            )
        ],
    }


@router.get("/sources")
def sources(
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    who=Depends(administrator),
    db: Session = Depends(database),
):
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    where = ReferenceProductSource.name.contains(escaped, escape="\\") if q else True
    rows = db.scalars(
        select(ReferenceProductSource)
        .where(where)
        .order_by(ReferenceProductSource.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [source_dto(db, row) for row in rows],
        "total": db.scalar(
            select(func.count()).select_from(ReferenceProductSource).where(where)
        ),
        "offset": offset,
        "limit": limit,
    }


@router.get("/sources/{id}")
def detail(id: int, who=Depends(administrator), db: Session = Depends(database)):
    return source_dto(db, get_source(db, id))


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    usage_status: str
    usage_note: str = Field(min_length=3, max_length=1000)
    enrichment_enabled: bool = False


@router.put("/sources/{id}")
def update(
    id: int, body: Usage, who=Depends(administrator), db: Session = Depends(database)
):
    source = get_source(db, id)
    if body.usage_status not in (
        "restricted",
        "internal_only",
        "approved_enrichment",
        "revoked",
    ):
        raise HTTPException(422, "Ismeretlen felhasználási állapot.")
    if body.enrichment_enabled and (
        body.usage_status != "approved_enrichment"
        or (
            source.tenant_id is not None
            and not (
                source.kind == "tenant_import" and source.contribution == "automatic"
            )
        )
    ):
        raise HTTPException(
            422,
            "Csak engedélyezett referencia- vagy KNOWLEDGE-01-ügyfélforrás használható.",
        )
    before = {
        "name": source.name,
        "usage_status": source.usage_status,
        "enrichment_enabled": source.enrichment_enabled,
    }
    source.name, source.usage_status, source.usage_note = (
        body.name.strip(),
        body.usage_status,
        body.usage_note,
    )
    source.enrichment_enabled = body.enrichment_enabled
    source.usage_basis = "administrator_decision"
    source.usage_decided_by, source.usage_decided_at = who.user.id, now()
    audit(
        db,
        who,
        "knowledge.source.update",
        source.id,
        before=before,
        after={
            "name": source.name,
            "usage_status": source.usage_status,
            "enrichment_enabled": source.enrichment_enabled,
        },
    )
    db.commit()
    knowledge_bridge.schedule_source(source.id)
    return source_dto(db, source)


@router.get("/sources/{id}/imports")
def history(
    id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    who=Depends(administrator),
    db: Session = Depends(database),
):
    source = get_source(db, id)
    if source.kind == "tenant_import" and source.tenant_id is not None:
        where = ImportRun.tenant_id == source.tenant_id
        return {
            "items": [
                supplier_run_dto(r, id)
                for r in db.scalars(
                    select(ImportRun)
                    .where(where)
                    .order_by(ImportRun.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ],
            "total": db.scalar(
                select(func.count()).select_from(ImportRun).where(where)
            ),
            "offset": offset,
            "limit": limit,
        }
    return {
        "items": [
            run_dto(r)
            for r in db.scalars(
                select(ReferenceImportRun)
                .where(ReferenceImportRun.source_id == id)
                .order_by(ReferenceImportRun.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
        "total": db.scalar(
            select(func.count())
            .select_from(ReferenceImportRun)
            .where(ReferenceImportRun.source_id == id)
        ),
        "offset": offset,
        "limit": limit,
    }


@router.get("/sources/{id}/audit")
def events(
    id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    who=Depends(administrator),
    db: Session = Depends(database),
):
    get_source(db, id)
    where = (
        Audit.target == str(id),
        or_(Audit.action.like("knowledge.%"), Audit.action == "unas.reference_usage"),
    )
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "actor_id": r.actor_id,
                "created_at": r.created_at,
                "details": r.details,
            }
            for r in db.scalars(
                select(Audit)
                .where(*where)
                .order_by(Audit.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
        "total": db.scalar(select(func.count()).select_from(Audit).where(*where)),
        "offset": offset,
        "limit": limit,
    }


def schedule(db, run):
    try:
        jobs.enqueue(run.id)
    except Exception:
        run.state, run.finished_at = "failed", now()
        run.errors = [{"line": None, "code": "queue_unavailable"}]
        db.commit()
    db.refresh(run)
    return run_dto(run)


@router.post("/uploads")
async def upload(
    file: UploadFile = File(...),
    source_name: str = Form(..., min_length=1, max_length=255),
    scope: str = Form("system"),
    source_id: int | None = Form(None),
    tenant_id: int | None = Form(None),
    reuse_authorized: bool = Form(False),
    who=Depends(administrator),
    db: Session = Depends(database),
):
    if not source_name.strip():
        raise HTTPException(422, "A forrás neve nem lehet üres.")
    filename = Path((file.filename or "").replace("\\", "/")).name
    if len(filename) > 255:
        raise HTTPException(422, "A fájlnév legfeljebb 255 karakter lehet.")
    if Path(filename).suffix.lower() not in (".csv", ".xlsx"):
        raise HTTPException(422, "CSV vagy XLSX fájl tölthető fel.")
    if scope not in ("system", "tenant") or (
        scope == "system" and not reuse_authorized
    ):
        raise HTTPException(
            422,
            "Válassz importhatókört és igazold a rendszerszintű újrahasznosítás jogát.",
        )
    if scope == "tenant" and (
        not tenant_id
        or not db.get(Tenant, tenant_id)
        or not db.get(Tenant, tenant_id).active
    ):
        raise HTTPException(422, "Válassz aktív ügyfelet.")
    source = get_source(db, source_id) if source_id else None
    if source is not None and source.kind == "tenant_import":
        raise HTTPException(
            422,
            "Ezt az ügyfélforrást a beszállítói importmotor frissíti. Új referenciafájlhoz válassz külön forrást.",
        )
    if source and source.tenant_id != (tenant_id if scope == "tenant" else None):
        raise HTTPException(
            422, "A forrás hatóköre nem változtatható meg feltöltéssel."
        )
    try:
        if source is None:
            import secrets

            source = ReferenceProductSource(
                key="admin:" + secrets.token_hex(16),
                name=source_name.strip(),
                kind=Path(filename).suffix.lower()[1:],
                tenant_id=tenant_id if scope == "tenant" else None,
                usage_status=(
                    "approved_enrichment" if scope == "system" else "internal_only"
                ),
                usage_basis=(
                    DEFAULT_USAGE_BASIS
                    if scope == "system"
                    else "tenant_upload_pending_review"
                ),
                enrichment_enabled=scope == "system",
                contribution="automatic" if scope == "system" else "pending",
                excluded_columns=[],
            )
            db.add(source)
            db.flush()
        run = ReferenceImportRun(
            source_id=source.id,
            file_name=filename,
            file_sha256="",
            state="queued",
            counters={},
            errors=[],
            ui_config={
                "web_upload": True,
                "scope": scope,
                "reuse_authorized": reuse_authorized,
            },
            ui_cursor=0,
        )
        db.add(run)
        db.flush()
        digest = hashlib.sha256()
        total = 0
        ordinal = 0
        while data := await file.read(60000):
            total += len(data)
            if total > 50_000_000:
                raise HTTPException(413, "Legfeljebb 50 MB tölthető fel.")
            digest.update(data)
            db.add(ReferenceImportChunk(run_id=run.id, ordinal=ordinal, data=data))
            ordinal += 1
            if ordinal % 16 == 0:
                db.flush()
        if not total:
            raise HTTPException(422, "A fájl üres.")
        run.file_sha256 = digest.hexdigest()
        audit(
            db,
            who,
            "knowledge.upload",
            source.id,
            run_id=run.id,
            bytes=total,
            scope=scope,
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        await file.close()
    return schedule(db, run)


@router.get("/imports/{id}")
def import_status(id: int, who=Depends(administrator), db: Session = Depends(database)):
    return run_dto(get_run(db, id))


class Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, str] = Field(max_length=512)


@router.post("/imports/{id}/preview")
def preview(
    id: int, body: Approve, who=Depends(administrator), db: Session = Depends(database)
):
    run = get_run(db, id)
    if run.state != "preview":
        raise HTTPException(409, "Csak ellenőrzésre váró import nézhető elő.")
    try:
        jobs.canonical_headers(run.ui_config["analysis"]["headers"], body.mapping)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    original = run.ui_config
    run.ui_config = {**original, "mapping": body.mapping}
    result = run_dto(run)
    # Preview is non-mutating; no commit or import state transition.
    db.rollback()
    return result


@router.post("/imports/{id}/start")
def start(
    id: int, body: Approve, who=Depends(administrator), db: Session = Depends(database)
):
    run = get_run(db, id)
    source = db.scalar(
        select(ReferenceProductSource)
        .where(ReferenceProductSource.id == run.source_id)
        .with_for_update()
    )
    db.refresh(run)
    if run.state != "preview":
        raise HTTPException(409, "Csak előnézetből indítható import.")
    if db.scalar(
        select(ReferenceImportRun.id)
        .where(
            ReferenceImportRun.source_id == source.id,
            ReferenceImportRun.id != id,
            ReferenceImportRun.state.in_(("queued_import", "converting", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "Ehhez a forráshoz már tartozik futó import; várd meg a végét."
        )
    try:
        jobs.canonical_headers(run.ui_config["analysis"]["headers"], body.mapping)
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            422, str(exc) if isinstance(exc, ValueError) else "Hiányzik az elemzés."
        ) from exc
    run.ui_config = {
        **run.ui_config,
        "mapping": body.mapping,
        "approved": True,
        "excluded_headers": [
            h
            for n, h in enumerate(run.ui_config["analysis"]["headers"])
            if body.mapping.get(str(n)) in (None, "exclude")
        ],
    }
    run.state, run.finished_at = "queued_import", None
    audit(db, who, "knowledge.import.start", source.id, run_id=id)
    db.commit()
    return schedule(db, run)


@router.post("/imports/{id}/cancel")
def cancel(id: int, who=Depends(administrator), db: Session = Depends(database)):
    run = get_run(db, id)
    if run.state not in ACTIVE + ("preview",):
        raise HTTPException(409, "Ez a feladat már befejeződött.")
    run.state, run.finished_at = "cancelled", now()
    run.ui_task_token = run.ui_lease_until = None
    audit(db, who, "knowledge.import.cancel", run.source_id, run_id=id)
    db.commit()
    return run_dto(run)


@router.post("/imports/{id}/retry")
def retry(id: int, who=Depends(administrator), db: Session = Depends(database)):
    run = get_run(db, id)
    if not run.ui_config.get("web_upload") or not run_dto(run)["retryable"]:
        raise HTTPException(409, "Ez az import most nem folytatható.")
    db.scalar(
        select(ReferenceProductSource)
        .where(ReferenceProductSource.id == run.source_id)
        .with_for_update()
    )
    if db.scalar(
        select(ReferenceImportRun.id)
        .where(
            ReferenceImportRun.source_id == run.source_id,
            ReferenceImportRun.id != id,
            ReferenceImportRun.state.in_(("queued_import", "converting", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(409, "A forrásnak másik aktív importja van.")
    run.errors = [e for e in (run.errors or []) if e.get("line") is not None]
    run.state = "queued_import" if run.ui_config.get("approved") else "queued"
    run.ui_task_token = run.ui_lease_until = None
    run.finished_at = None
    audit(db, who, "knowledge.import.retry", run.source_id, run_id=id)
    db.commit()
    return schedule(db, run)


@router.post("/imports/{id}/repeat")
def repeat(id: int, who=Depends(administrator), db: Session = Depends(database)):
    original = get_run(db, id)
    if not original.ui_config.get("web_upload") or original.state not in (
        "completed",
        "partial",
    ):
        raise HTTPException(
            409,
            "Csak befejezett webes import ismételhető meg. CLI-importhoz tölts fel új fájlt.",
        )
    db.scalar(
        select(ReferenceProductSource)
        .where(ReferenceProductSource.id == original.source_id)
        .with_for_update()
    )
    if db.scalar(
        select(ReferenceImportRun.id)
        .where(
            ReferenceImportRun.source_id == original.source_id,
            ReferenceImportRun.state.in_(("queued_import", "converting", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(409, "A forrásnak másik aktív importja van.")
    run = ReferenceImportRun(
        source_id=original.source_id,
        file_name=original.file_name,
        file_sha256=original.file_sha256,
        state="queued_import",
        counters={},
        errors=[],
        ui_config=dict(original.ui_config),
        ui_cursor=0,
    )
    db.add(run)
    db.flush()
    for chunk in db.scalars(
        select(ReferenceImportChunk)
        .where(ReferenceImportChunk.run_id == id)
        .order_by(ReferenceImportChunk.ordinal)
        .execution_options(yield_per=16)
    ):
        db.add(
            ReferenceImportChunk(run_id=run.id, ordinal=chunk.ordinal, data=chunk.data)
        )
        if chunk.ordinal % 16 == 0:
            db.flush()
    audit(
        db,
        who,
        "knowledge.import.repeat",
        original.source_id,
        run_id=run.id,
        previous_run_id=id,
    )
    db.commit()
    return schedule(db, run)
