"""IMPORT-MAP-01 (#58) endpoints under /api/v1/imports; contract:
docs/design/IMPORT-MAP-01-API.md. Existing /api/v1/imports endpoints are unchanged."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import import_mapping as im
from app.import_api import get_run, tenant
from app.import_models import Supplier
from app.security import audit, database, require

router = APIRouter(prefix="/api/v1/imports", tags=["Beszállítói import – megfeleltetés"])
ENGINE = Query("unas", pattern=r"^[a-z0-9_-]{1,48}$")


def failure(exc):
    return JSONResponse({"error": {"code": str(exc.status), "message": exc.message,
                                   **exc.extra}},
                        status_code=exc.status, headers={"Cache-Control": "no-store"})


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["field", "parameter"]
    key: str | None = Field(None, max_length=120)
    header: str | None = Field(None, max_length=500)


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, lt=512)
    target: Target | None = None


class NewParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    param_type: Literal["text", "num", "enum", "enummore", "link_text"] = "text"
    group_name: str = Field("", max_length=120)
    unit: str | None = Field(None, max_length=32)
    approved: bool = False


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine_key: str = Field("unas", pattern=r"^[a-z0-9_-]{1,48}$")
    columns: list[Column] = Field(max_length=512)
    new_parameters: list[NewParameter] = Field(default_factory=list, max_length=200)
    identity_target: str | None = Field(None, max_length=500)
    financial_approved: bool = False
    vat_rate: int | None = None


class SaveInput(MappingInput):
    name: str = Field(min_length=1, max_length=120)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emag_category_id: int = Field(gt=0)
    mode: Literal["set", "all", "none"] = "set"
    emag_parameter_ids: list[int] = Field(default_factory=list, max_length=2000)


def plain(body):
    data = body.model_dump()
    data["columns"] = [{"index": c["index"], "target": c["target"]} for c in data["columns"]]
    return data


@router.get("/engines/{key}/registry")
def registry(key: str, who=Depends(require("imports.read")), db: Session = Depends(database)):
    return im.engine_registry(db, key)


@router.get("/runs/{id}/column-mapping")
def column_mapping(id: int, engine: str = ENGINE, who=Depends(require("imports.read")),
                   db: Session = Depends(database)):
    return im.mapping_view(db, get_run(db, who, id), engine)


@router.post("/runs/{id}/column-mapping/validate")
def validate_mapping(id: int, body: MappingInput, who=Depends(require("imports.read")),
                     db: Session = Depends(database)):
    return im.public_validation(im.validate(db, get_run(db, who, id), plain(body)))


@router.post("/runs/{id}/column-mapping")
def save_mapping(id: int, body: SaveInput, who=Depends(require("imports.approve")),
                 db: Session = Depends(database)):
    run = get_run(db, who, id)
    try:
        profile, report, created = im.save_mapping(db, run, plain(body), who.user.id)
    except im.MappingError as exc:
        db.rollback()
        return failure(exc)
    audit(db, who, "import.engine_mapping", run.id, tenant_id=run.tenant_id,
          profile=profile.id, version=profile.version, engine=body.engine_key)
    for p in created:
        audit(db, who, "import.parameter_approved", profile.id, tenant_id=run.tenant_id,
              header=p["header"])
    db.commit()
    return {"profile_id": profile.id, "version": profile.version,
            "import_mapping": report["import_mapping"],
            "approval_defaults": report["approval_defaults"], "validation": report}


@router.get("/suppliers/{id}/engine-mappings")
def engine_mappings(id: int, engine: str = ENGINE, who=Depends(require("imports.read")),
                    db: Session = Depends(database)):
    supplier = db.get(Supplier, id)
    if supplier is None or supplier.tenant_id != tenant(who):
        raise HTTPException(404, "Beszállító nem található.")
    return [{"profile_id": p.id, "version": p.version, "name": p.name,
             "engine_version": p.config["engine_mapping"]["engine_version"],
             "columns": p.config["engine_mapping"]["columns"],
             "parameters": p.config["engine_mapping"]["parameters"],
             "approved_by": p.approved_by, "created_at": p.created_at}
            for p in im.engine_profiles(db, supplier.tenant_id, supplier.id, engine)]


@router.get("/runs/{id}/donor-categories")
def donor_categories(id: int, who=Depends(require("imports.read")),
                     db: Session = Depends(database)):
    return im.donor_categories(db, get_run(db, who, id))


@router.get("/runs/{id}/donor-parameters")
def donor_parameters(id: int, emag_category_id: int = Query(gt=0),
                     who=Depends(require("imports.read")), db: Session = Depends(database)):
    return im.donor_parameters(db, get_run(db, who, id), emag_category_id)


@router.put("/runs/{id}/donor-parameters/selection")
def donor_selection(id: int, body: Selection, who=Depends(require("imports.manage")),
                    db: Session = Depends(database)):
    run = get_run(db, who, id)
    try:
        chosen = im.set_selection(db, run, body.emag_category_id, body.mode,
                                  body.emag_parameter_ids, who.user.id)
    except im.MappingError as exc:
        db.rollback()
        return failure(exc)
    audit(db, who, "import.donor_selection", run.id, tenant_id=run.tenant_id,
          emag_category_id=body.emag_category_id, mode=body.mode, selected=len(chosen))
    db.commit()
    return im.donor_parameters(db, run, body.emag_category_id)


@router.get("/runs/{id}/prepared-fields")
def prepared_fields(id: int, who=Depends(require("imports.read")),
                    db: Session = Depends(database)):
    return im.prepared_fields(db, get_run(db, who, id))

