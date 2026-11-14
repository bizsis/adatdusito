"""Tenant-scoped supplier imports and central export definition administration."""

import csv
import io
import json
import re
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from app.security import identity, database, require, audit
from app.import_models import (
    Supplier,
    ImportProfile,
    ImportRun,
    ImportChunk,
    ImportRow,
    SupplierProduct,
    StoreEngine,
    StoreProfile,
    ImportChange,
)
from app.import_parser import FIELDS, FINANCIAL, analyze
from app.import_engine import enqueue, limit
from app.models import now

router = APIRouter(prefix="/api/v1/imports", tags=["Beszállítói import"])


def tenant(who):
    if who.session.tenant_id is None:
        raise HTTPException(409, "Válassz ügyfél-munkaterületet.")
    return who.session.tenant_id


def get_run(db, who, id):
    r = db.get(ImportRun, id)
    if not r or r.tenant_id != tenant(who):
        raise HTTPException(404, "Az import nem található.")
    return r


def row_envelope(run, row):
    from app.import_parser import normalize

    fields = {
        field: normalize(field, row.raw[int(i)])[0]
        for i, field in run.config.get("mapping", {}).items()
        if int(i) < len(row.raw)
    }
    for field in ("currency", "price_type", "tax_basis"):
        if not fields.get(field) and run.config.get(field):
            fields[field] = run.config[field]
    mapped = {int(i) for i in run.config.get("mapping", {})}
    headers = run.analysis.get("headers", [])
    return {
        **row.normalized,
        "fields": fields,
        "unmapped_attributes": [
            {"column": i, "header": headers[i] if i < len(headers) else None, "raw": v}
            for i, v in enumerate(row.raw)
            if i not in mapped and v
        ],
    }


def public(run):
    return {
        k: getattr(run, k)
        for k in (
            "id",
            "supplier_id",
            "filename",
            "state",
            "profile_id",
            "config",
            "analysis",
            "cursor",
            "counters",
            "error",
            "created_at",
            "updated_at",
        )
    }


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/fields")
def fields(who=Depends(require("imports.read"))):
    return [{"key": k, "label": v[0]} for k, v in FIELDS.items()]


@router.get("/suppliers")
def suppliers(who=Depends(require("imports.read")), db: Session = Depends(database)):
    return [
        {"id": s.id, "name": s.name}
        for s in db.scalars(select(Supplier).where(Supplier.tenant_id == tenant(who)))
    ]


@router.post("/suppliers")
def supplier(
    body: Named, who=Depends(require("imports.manage")), db: Session = Depends(database)
):
    s = Supplier(tenant_id=tenant(who), name=body.name)
    db.add(s)
    db.flush()
    audit(db, who, "import.supplier", s.id, tenant_id=s.tenant_id)
    db.commit()
    return {"id": s.id, "name": s.name}


@router.get("/profiles")
def profiles(
    supplier_id: int,
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    return [
        {
            "id": p.id,
            "name": p.name,
            "version": p.version,
            "config": p.config,
            "approved_by": p.approved_by,
            "last_successful_processing": db.scalar(
                select(func.max(ImportRun.updated_at)).where(
                    ImportRun.profile_id == p.id,
                    ImportRun.tenant_id == tenant(who),
                    ImportRun.state == "completed",
                )
            ),
        }
        for p in db.scalars(
            select(ImportProfile)
            .where(
                ImportProfile.tenant_id == tenant(who),
                ImportProfile.supplier_id == supplier_id,
            )
            .order_by(ImportProfile.id.desc())
        )
    ]


@router.get("/runs")
def runs(
    offset: int = Query(0, ge=0),
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    return [
        public(r)
        for r in db.scalars(
            select(ImportRun)
            .where(ImportRun.tenant_id == tenant(who))
            .order_by(ImportRun.id.desc())
            .offset(offset)
            .limit(25)
        )
    ]


@router.post("/runs")
async def upload(
    supplier_id: int = Form(...),
    settings: str = Form("{}"),
    file: UploadFile = File(...),
    who=Depends(require("imports.manage")),
    db: Session = Depends(database),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.tenant_id != tenant(who):
        raise HTTPException(404, "Beszállító nem található.")
    filename = (file.filename or "").replace("\\", "/").split("/")[-1][:255]
    if not filename.lower().endswith((".csv", ".xlsx")):
        raise HTTPException(422, "CSV vagy XLSX szükséges.")
    try:
        config = json.loads(settings)
    except ValueError:
        raise HTTPException(422, "Hibás beállítások.")
    if not isinstance(config, dict) or set(config) - {
        "sheet",
        "header_line",
        "encoding",
        "delimiter",
    }:
        raise HTTPException(422, "Hibás fájlbeállítások.")
    run = ImportRun(
        tenant_id=s.tenant_id,
        supplier_id=s.id,
        filename=filename,
        config=config,
        state="uploaded",
    )
    db.add(run)
    db.flush()
    size = 0
    ordinal = 0
    try:
        while data := await file.read(60000):
            size += len(data)
            if size > limit("IMPORT_MAX_BYTES", 50_000_000):
                raise HTTPException(413, "Túl nagy fájl.")
            db.add(ImportChunk(run_id=run.id, ordinal=ordinal, data=data))
            ordinal += 1
            if ordinal % 16 == 0:
                db.flush()
        if size == 0:
            raise HTTPException(422, "Üres fájl.")
        audit(db, who, "import.upload", run.id, tenant_id=s.tenant_id, size=size)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        await file.close()
    try:
        enqueue(run.id)
    except Exception:
        run.error = "A feladatütemező nem elérhető; az Elemzés újraindítása gombbal folytatható."
        db.commit()
    return public(run)


@router.get("/runs/{id}")
def detail(
    id: int, who=Depends(require("imports.read")), db: Session = Depends(database)
):
    return public(get_run(db, who, id))


@router.get("/runs/{id}/rows")
def preview(
    id: int,
    offset: int = Query(0, ge=0),
    limit_: int = Query(25, ge=1, le=100, alias="limit"),
    errors: bool = False,
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    run = get_run(db, who, id)
    stmt = select(ImportRow).where(ImportRow.run_id == id)
    if errors:
        stmt = stmt.where(ImportRow.state.in_(["error", "conflict"]))
    return {
        "items": [
            {
                "line": r.line,
                "raw": r.raw,
                "normalized": row_envelope(run, r),
                "issues": r.issues,
                "state": r.state,
                "product_id": r.product_id,
            }
            for r in db.scalars(
                stmt.order_by(ImportRow.line).offset(offset).limit(limit_)
            )
        ],
        "offset": offset,
        "total": db.scalar(select(func.count()).select_from(stmt.subquery())),
        "schema_version": "1.0",
        "tenant_id": run.tenant_id,
        "supplier_id": run.supplier_id,
        "run_id": run.id,
    }


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    mapping: dict[str, str]
    identity_field: str | None = None
    feed_type: str = "partial"
    financial_approved: bool = False
    automatic: bool = False
    price_type: str | None = None
    tax_basis: str | None = None
    currency: str | None = None


@router.post("/runs/{id}/approve")
def approve(
    id: int,
    body: Approval,
    who=Depends(require("imports.manage")),
    db: Session = Depends(database),
):
    run = get_run(db, who, id)
    if run.state != "awaiting_approval":
        raise HTTPException(409, "Az import nem vár jóváhagyásra.")
    if body.feed_type not in ("full", "partial", "price", "stock", "technical"):
        raise HTTPException(422, "Hibás feedtípus.")
    headers = run.analysis["headers"]
    mapping = body.mapping
    if not mapping or any(
        not i.isdecimal() or int(i) >= len(headers) or v not in FIELDS
        for i, v in mapping.items()
    ):
        raise HTTPException(422, "Hibás oszlopmegfeleltetés.")
    if len(set(mapping.values())) != len(mapping):
        raise HTTPException(422, "Egy belső mezőhöz csak egy oszlop rendelhető.")
    if body.identity_field and body.identity_field not in mapping.values():
        raise HTTPException(422, "A kulcsmező nincs megfeleltetve.")
    if not any(
        v in ("name", "supplier_id", "sku", "mpn", "gtin", "model")
        for v in mapping.values()
    ):
        raise HTTPException(422, "Név vagy azonosító szükséges.")
    if (
        any(v in FINANCIAL for v in mapping.values())
        or body.currency
        or body.price_type
        or body.tax_basis
    ) and not body.financial_approved:
        raise HTTPException(
            422, "A pénzügyi megfeleltetés kifejezett jóváhagyást igényel."
        )
    previous = (
        db.scalar(
            select(func.max(ImportProfile.version)).where(
                ImportProfile.tenant_id == run.tenant_id,
                ImportProfile.supplier_id == run.supplier_id,
                ImportProfile.name == body.name,
            )
        )
        or 0
    )
    config = {
        **run.config,
        **body.model_dump(exclude={"name", "financial_approved"}),
        "analysis": run.analysis,
        "financial_approved": body.financial_approved,
        "identity_namespace": "supplier",
        "approved_columns": [
            {
                "column": int(i),
                "header": headers[int(i)],
                "field": v,
                "approved_by": who.user.id,
                "method": "user_approved",
                "confidence": next(
                    (
                        c["confidence"]
                        for c in run.analysis["columns"]
                        if c["index"] == int(i)
                    ),
                    0,
                ),
            }
            for i, v in mapping.items()
        ],
    }
    p = ImportProfile(
        tenant_id=run.tenant_id,
        supplier_id=run.supplier_id,
        name=body.name,
        version=previous + 1,
        config=config,
        approved_by=who.user.id,
    )
    db.add(p)
    db.flush()
    run.profile_id = p.id
    run.config = config
    run.approved_by = who.user.id
    run.state = "processing"
    run.error = None
    audit(db, who, "import.approve", run.id, tenant_id=run.tenant_id, profile=p.id)
    db.commit()
    enqueue(run.id)
    return public(run)


@router.post("/runs/{id}/actions/{action}")
def action(
    id: int,
    action: str,
    who=Depends(require("imports.manage")),
    db: Session = Depends(database),
):
    run = get_run(db, who, id)
    run = db.scalar(select(ImportRun).where(ImportRun.id == id).with_for_update())
    if action == "pause" and run.state == "processing":
        run.state = "paused"
    elif action == "cancel" and run.state not in ("completed", "partial"):
        run.state = "cancelled"
    elif action in ("resume", "analyze") and run.state in (
        "paused",
        "failed",
        "uploaded",
        "processing",
    ):
        if run.lease_until and run.lease_until > now():
            raise HTTPException(
                409,
                "A feladat még fut; várj a munkafolyamatra vagy a zárolás lejártára.",
            )
        run.state = "processing" if run.approved_by else "uploaded"
        run.error = None
    elif action == "retry-errors" and run.state in ("partial", "completed"):
        db.execute(
            delete(ImportRow).where(
                ImportRow.run_id == id, ImportRow.state.in_(["error", "conflict"])
            )
        )
        run.cursor = 0
        run.state = "processing"
        run.counters = {
            k: v for k, v in run.counters.items() if k not in ("error", "conflict")
        }
    else:
        raise HTTPException(409, "Ebben az állapotban nem végezhető el.")
    run.lease_until = None
    run.task_token = None
    audit(db, who, "import." + action, id, tenant_id=run.tenant_id)
    db.commit()
    if run.state in ("uploaded", "processing"):
        enqueue(id)
    return public(run)


@router.get("/runs/{id}/errors.csv")
def error_export(
    id: int, who=Depends(require("imports.read")), db: Session = Depends(database)
):
    get_run(db, who, id)

    def generate():
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Sor", "Állapot", "Hibák"])
        yield "\ufeff" + out.getvalue()
        for r in db.scalars(
            select(ImportRow)
            .where(ImportRow.run_id == id, ImportRow.state.in_(["error", "conflict"]))
            .order_by(ImportRow.line)
            .execution_options(yield_per=100)
        ):
            out.seek(0)
            out.truncate()
            writer.writerow([r.line, r.state, "; ".join(r.issues)])
            yield out.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="import-errors.csv"'},
    )


@router.get("/runs/{id}/file")
def source_file(
    id: int, who=Depends(require("imports.read")), db: Session = Depends(database)
):
    get_run(db, who, id)
    if (
        db.scalar(select(ImportChunk.run_id).where(ImportChunk.run_id == id).limit(1))
        is None
    ):
        raise HTTPException(404, "A forrásfájl megőrzési ideje lejárt.")

    def chunks():
        for c in db.scalars(
            select(ImportChunk)
            .where(ImportChunk.run_id == id)
            .order_by(ImportChunk.ordinal)
            .execution_options(yield_per=16)
        ):
            yield c.data

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="source-file"'},
    )


@router.get("/products")
def products(
    supplier_id: int,
    offset: int = Query(0, ge=0),
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    return [
        {"id": p.id, "fields": p.data, "run_id": p.last_run_id, "line": p.last_line}
        for p in db.scalars(
            select(SupplierProduct)
            .where(
                SupplierProduct.tenant_id == tenant(who),
                SupplierProduct.supplier_id == supplier_id,
            )
            .order_by(SupplierProduct.id)
            .offset(offset)
            .limit(25)
        )
    ]


class EngineInput(Named):
    fields: list[dict] = Field(max_length=512)


def validate_fields(fields):
    seen = set()
    for f in fields:
        if set(f) - {
            "key",
            "label",
            "type",
            "required",
            "default",
            "allowed",
            "validation",
            "internal_field",
        }:
            raise HTTPException(422, "Ismeretlen meződefiníció.")
        key = f.get("key", "")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", key)
            or key in seen
        ):
            raise HTTPException(422, "Hibás vagy ismételt mezőazonosító.")
        seen.add(key)
        if not isinstance(f.get("label"), str) or not 1 <= len(f["label"]) <= 255:
            raise HTTPException(422, "Hibás megjelenítési név.")
        if not isinstance(f.get("allowed", []), list) or any(
            not isinstance(v, str) for v in f.get("allowed", [])
        ):
            raise HTTPException(422, "Hibás értéklista.")
        default = f.get("default")
        if (
            default not in (None, "")
            and f.get("allowed")
            and default not in f["allowed"]
        ):
            raise HTTPException(422, "Az alapérték nincs a megengedett listában.")
        if f.get("internal_field") and f["internal_field"] not in FIELDS:
            raise HTTPException(422, "Ismeretlen belső mező.")
        if f.get("type") not in ("text", "number", "date", "boolean"):
            raise HTTPException(422, "Hibás adattípus.")
        if not isinstance(f.get("required", False), bool):
            raise HTTPException(422, "Hibás kötelezőség.")
        if f.get("validation") not in (None, "", "url", "email", "gtin", "nonnegative"):
            raise HTTPException(422, "Ismeretlen validáció.")
    return fields


@router.get("/engines")
def engines(who=Depends(identity), db: Session = Depends(database)):
    return [
        {"key": e.key, "name": e.name, "version": e.version, "fields": e.fields}
        for e in db.scalars(select(StoreEngine))
    ]


@router.put("/engines/{key}")
def save_engine(
    key: str,
    body: EngineInput,
    who=Depends(require("exports.manage")),
    db: Session = Depends(database),
):
    if not re.fullmatch(r"[a-z0-9_-]{1,48}", key):
        raise HTTPException(422, "Hibás motorazonosító.")
    e = db.get(StoreEngine, key)
    before = {"name": e.name, "fields": e.fields, "version": e.version} if e else None
    if not e:
        e = StoreEngine(key=key, name=body.name, fields=[], version=0)
        db.add(e)
    e.name = body.name
    e.fields = validate_fields(body.fields)
    e.version += 1
    audit(
        db,
        who,
        "export.engine_version",
        key,
        before=before,
        after=body.model_dump(),
        version=e.version,
    )
    db.commit()
    return {"key": e.key, "version": e.version}


@router.delete("/engines/{key}/fields/{field_key}")
def delete_field(
    key: str,
    field_key: str,
    who=Depends(require("exports.manage")),
    db: Session = Depends(database),
):
    e = db.get(StoreEngine, key)
    if not e:
        raise HTTPException(404, "Ismeretlen motor.")
    return save_engine(
        key,
        EngineInput(name=e.name, fields=[f for f in e.fields if f["key"] != field_key]),
        who,
        db,
    )


@router.post("/engines/{key}/reference")
async def engine_reference(
    key: str,
    file: UploadFile = File(...),
    who=Depends(require("exports.manage")),
    db: Session = Depends(database),
):
    import tempfile

    size = 0
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as f:
        while data := await file.read(60000):
            size += len(data)
            if size > limit("IMPORT_MAX_BYTES", 50_000_000):
                raise HTTPException(413, "Túl nagy fájl.")
            f.write(data)
        f.flush()
        try:
            _, a = analyze(f.name, file.filename or "", {})
        except Exception as exc:
            raise HTTPException(422, str(exc))
    await file.close()
    # Reference columns are proposals only, never centrally required by inference.
    return {
        "fields": [
            {"key": f"field_{i}", "label": h, "type": "text", "required": False}
            for i, h in enumerate(a["headers"])
        ]
    }


@router.get("/export-profiles")
def export_profiles(
    who=Depends(require("imports.read")), db: Session = Depends(database)
):
    return [
        {
            "id": p.id,
            "engine_key": p.engine_key,
            "name": p.name,
            "version": p.version,
            "fields": p.fields,
            "rules": p.rules,
        }
        for p in db.scalars(
            select(StoreProfile).where(StoreProfile.tenant_id == tenant(who))
        )
    ]


class ExportProfileInput(EngineInput):
    engine_key: str
    negative_stock_policy: str = "zero"


@router.post("/export-profiles")
def save_export_profile(
    body: ExportProfileInput,
    who=Depends(require("exports.profile")),
    db: Session = Depends(database),
):
    if body.negative_stock_policy not in ("zero", "preserve"):
        raise HTTPException(422, "Ismeretlen készletszabály.")
    e = db.get(StoreEngine, body.engine_key)
    if not e:
        raise HTTPException(404, "Ismeretlen motor.")
    supplied = validate_fields(body.fields)
    bykey = {f["key"]: f for f in supplied}
    for required in e.fields:
        if required.get("required") and (
            required["key"] not in bykey or not bykey[required["key"]].get("required")
        ):
            raise HTTPException(422, "Központi kötelező mező nem kapcsolható ki.")
    for required in e.fields:
        if required.get("required"):
            chosen = bykey[required["key"]]
            if any(
                chosen.get(k) != required.get(k)
                for k in ("type", "validation", "allowed")
            ):
                raise HTTPException(
                    422, "Központi kötelező mező validációja nem írható felül."
                )
    p = StoreProfile(
        tenant_id=tenant(who),
        engine_key=e.key,
        name=body.name,
        version=e.version,
        fields=supplied,
        rules={"negative_stock": body.negative_stock_policy},
    )
    db.add(p)
    audit(db, who, "export.profile", body.name, tenant_id=p.tenant_id)
    db.commit()
    return {"id": p.id}


class ParserSettings(BaseModel):
    sheet: str | None = None
    header_line: int = Field(default=1, ge=1, le=20)
    encoding: str | None = None
    delimiter: str | None = None


@router.put("/runs/{id}/settings")
def parser_settings(
    id: int,
    body: ParserSettings,
    who=Depends(require("imports.manage")),
    db: Session = Depends(database),
):
    run = get_run(db, who, id)
    if run.state not in ("awaiting_approval", "failed") or run.approved_by:
        raise HTTPException(409, "Már jóváhagyott import nem elemezhető újra.")
    run.config = body.model_dump(exclude_none=True)
    run.state = "uploaded"
    run.error = None
    db.commit()
    enqueue(id)
    return public(run)


@router.get("/runs/{id}/join-suggestions")
def join_suggestions(
    id: int, who=Depends(require("imports.read")), db: Session = Depends(database)
):
    run = get_run(db, who, id)
    products = list(
        db.scalars(
            select(SupplierProduct)
            .where(
                SupplierProduct.tenant_id == run.tenant_id,
                SupplierProduct.supplier_id == run.supplier_id,
            )
            .limit(100)
        )
    )
    result = []
    for c in run.analysis.get("columns", []):
        vals = set(c["samples"])
        for field in ("sku", "supplier_id", "mpn", "gtin"):
            matches = vals & {p.data.get(field) for p in products}
            if matches:
                result.append(
                    {
                        "column": c["index"],
                        "field": field,
                        "exact_sample_matches": len(matches),
                        "requires_approval": True,
                    }
                )
    return result


@router.delete("/runs/{id}/source")
def expire_source(
    id: int, who=Depends(require("imports.manage")), db: Session = Depends(database)
):
    from datetime import timedelta

    run = get_run(db, who, id)
    days = max(1, limit("IMPORT_SOURCE_RETENTION_DAYS", 90))
    if run.state not in (
        "completed",
        "partial",
        "cancelled",
    ) or run.created_at > now() - timedelta(days=days):
        raise HTTPException(
            409, "A megőrzési idő még nem járt le vagy az import nem lezárt."
        )
    db.execute(delete(ImportChunk).where(ImportChunk.run_id == id))
    audit(db, who, "import.expire_source", id, tenant_id=run.tenant_id)
    db.commit()
    return {"expired": True}


@router.get("/products/{id}/changes")
def changes(
    id: int,
    offset: int = Query(0, ge=0),
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    product = db.get(SupplierProduct, id)
    if not product or product.tenant_id != tenant(who):
        raise HTTPException(404, "A tétel nem található.")
    return [
        {"run_id": c.run_id, "line": c.line, "delta": c.delta}
        for c in db.scalars(
            select(ImportChange)
            .where(ImportChange.product_id == id)
            .order_by(ImportChange.id.desc())
            .offset(offset)
            .limit(25)
        )
    ]


@router.get("/runs/{id}/source-preview")
def source_preview(
    id: int,
    offset: int = Query(0, ge=0, le=250000),
    limit_: int = Query(25, ge=1, le=100, alias="limit"),
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    from app.import_engine import materialize
    from app.import_parser import rows

    run = get_run(db, who, id)
    if not run.analysis.get("headers"):
        raise HTTPException(409, "Az elemzés még nem készült el.")
    result = []
    with materialize(db, run) as path:
        for line, raw in rows(path, run.config):
            if line <= run.config["header_line"] + offset:
                continue
            result.append({"line": line, "raw": raw})
            if len(result) > limit_:
                break
    return {
        "items": result[:limit_],
        "has_more": len(result) > limit_,
        "offset": offset,
        "headers": run.analysis["headers"],
    }


class PreviewMapping(BaseModel):
    mapping: dict[str, str]
    offset: int = Field(default=0, ge=0, le=250000)


@router.post("/runs/{id}/preview")
def interpreted_preview(
    id: int,
    body: PreviewMapping,
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    from app.import_parser import normalize

    run = get_run(db, who, id)
    headers = run.analysis.get("headers", [])
    if any(
        not k.isdecimal() or int(k) >= len(headers) or v not in FIELDS
        for k, v in body.mapping.items()
        if v
    ):
        raise HTTPException(422, "Hibás megfeleltetés.")
    page = source_preview(id, body.offset, 25, who, db)
    for r in page["items"]:
        r["interpreted"] = {
            field: {
                "value": normalize(field, r["raw"][int(i)])[0],
                "issues": normalize(field, r["raw"][int(i)])[1],
            }
            for i, field in body.mapping.items()
            if field and int(i) < len(r["raw"])
        }
    return page
