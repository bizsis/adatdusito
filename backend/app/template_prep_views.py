"""TEMPLATE-PREP-01 endpoints under /api/v1/imports; contract:
docs/design/TEMPLATE-PREP-01-API.md. Existing import endpoints are unchanged."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import template_prep as tp
from app.import_api import get_run, tenant
from app.import_models import Supplier
from app.security import audit, database, require

router = APIRouter(prefix="/api/v1/imports", tags=["Beszállítói import – sablonkészítés"])


def failure(exc):
    return JSONResponse({"error": {"code": str(exc.status), "message": exc.message,
                                   **exc.extra}},
                        status_code=exc.status, headers={"Cache-Control": "no-store"})


class ParameterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    param_type: Literal["text", "num", "enum", "enummore", "link_text"] = "text"
    group_name: str = Field("", max_length=120)
    unit: str | None = Field(None, max_length=32)


class NewParameter(ParameterSpec):
    approved: bool = False


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=40)
    instance: int | None = Field(None, ge=0, le=99)
    order: int | None = Field(None, ge=1, le=99)
    header: str | None = Field(None, max_length=500)
    parameter: ParameterSpec | None = None


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, lt=512)
    state: Literal["mapped", "unused"] | None = None
    target: Target | None = None


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statusz: str = "1"
    afa: str = "27"


class PreparationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str = Field("unas", max_length=48)
    currency: str = Field("HUF", max_length=3)
    columns: list[Column] = Field(max_length=512)
    new_parameters: list[NewParameter] = Field(default_factory=list, max_length=200)
    defaults: Defaults = Field(default_factory=Defaults)


class SaveInput(PreparationInput):
    run_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    template_id: int | None = Field(None, gt=0)


def plain(body):
    data = body.model_dump()
    for c in data["columns"]:
        if c["state"] == "mapped" and c["target"] is None:
            c["state"] = None  # "mapped" without a target is undecided, never dropped
        if c["target"]:
            c["target"] = {k: v for k, v in c["target"].items() if v is not None}
    return data


@router.get("/template-targets")
def targets(engine: str = Query("unas", max_length=48), who=Depends(require("imports.read"))):
    if engine not in tp.ENGINES:
        raise HTTPException(422, "Nem támogatott webshopmotor.")
    return tp.targets_payload()


@router.get("/runs/{id}/template-preparation")
def preparation(id: int, engine: str = Query("unas", max_length=48),
                currency: str = Query("HUF", max_length=3),
                template_id: int | None = Query(None, ge=0),
                who=Depends(require("imports.read")), db: Session = Depends(database)):
    try:
        return tp.preparation(db, get_run(db, who, id), engine, currency, template_id)
    except tp.TemplateError as exc:
        return failure(exc)


@router.post("/runs/{id}/template-preparation/validate")
def validate(id: int, body: PreparationInput, who=Depends(require("imports.read")),
             db: Session = Depends(database)):
    try:
        return tp.public_report(tp.validate(db, get_run(db, who, id), plain(body)))
    except tp.TemplateError as exc:
        return failure(exc)


@router.post("/import-templates")
def save(body: SaveInput, who=Depends(require("imports.approve")),
         db: Session = Depends(database)):
    run = get_run(db, who, body.run_id)
    try:
        profile, report, created = tp.save(db, run, plain(body), who.user.id)
        db.flush()
    except tp.TemplateError as exc:
        db.rollback()
        return failure(exc)
    except IntegrityError:
        db.rollback()
        return failure(tp.TemplateError(409, "A sablon verziója közben megváltozott; "
                                             "próbáld újra.", reason="version_conflict"))
    audit(db, who, "import.template_saved", profile.id, tenant_id=run.tenant_id,
          supplier=run.supplier_id, name=profile.name, version=profile.version,
          template_key=profile.config["template"]["template_key"], run=run.id)
    for p in created:
        audit(db, who, "import.parameter_approved", profile.id, tenant_id=run.tenant_id,
              header=p["header"])
    db.commit()
    return {"id": profile.id, "template_key": profile.config["template"]["template_key"],
            "name": profile.name, "version": profile.version,
            "price_missing": report["price_missing"], "validation": report}


@router.get("/suppliers/{id}/import-templates")
def supplier_templates(id: int, who=Depends(require("imports.read")),
                       db: Session = Depends(database)):
    supplier = db.get(Supplier, id)
    if supplier is None or supplier.tenant_id != tenant(who):
        raise HTTPException(404, "Beszállító nem található.")
    return tp.supplier_templates(db, supplier.tenant_id, supplier.id)


@router.get("/import-templates/{id}")
def template(id: int, who=Depends(require("imports.read")), db: Session = Depends(database)):
    return tp.template_dto(tp.get_template(db, tenant(who), id))


@router.get("/import-templates/{id}/versions")
def template_versions(id: int, who=Depends(require("imports.read")),
                      db: Session = Depends(database)):
    t = tp.get_template(db, tenant(who), id)
    return tp.versions(db, t.tenant_id, t)

