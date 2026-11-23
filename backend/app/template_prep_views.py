"""TEMPLATE-PREP-01 endpoints under /api/v1/imports; contract:
docs/design/TEMPLATE-PREP-01-API.md. Existing import endpoints are unchanged."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import template_prep as tp
from app.import_api import get_run, tenant
from app.import_models import ImportProfile, ImportRun, Supplier
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



# --- IMPORT-DELETE-01: saved template and template version deletion -------------

TEMPLATE_REFUSALS = {
    "active_version": "Az aktív (legújabb) sablonverzió nem törölhető, mert ezt használja a "
                      "sablon. Ments új verziót, vagy töröld a teljes sablont.",
    "only_version": "A sablon egyetlen verziója nem törölhető külön; töröld a teljes sablont.",
    "referenced": "A sablont (vagy ezt a verzióját) jóváhagyott vagy feldolgozott import "
                  "hivatkozza, ezért nem törölhető.",
}


def family(db, template, lock=False):
    """All versions of one saved template (same template_key), newest first."""
    query = select(ImportProfile).where(ImportProfile.tenant_id == template.tenant_id,
                                        ImportProfile.supplier_id == template.supplier_id)
    if lock:
        query = query.with_for_update()
    key = template.config["template"]["template_key"]
    return [p for p in db.scalars(query.order_by(ImportProfile.id.desc()))
            if (p.config.get("template") or {}).get("template_key") == key]


def run_references(db, profiles, lock=False):
    """Imports pointing at these versions: (hard references, soft upload matches).

    Hard: an approved/processed import used the version (profile_id) or a settings
    link (engine_mapping_profile_id) -> deletion is refused. Soft: an unapproved
    upload whose analysis merely matched the version's header structure -> the
    link is detached (profile_id cleared) so the foreign key stays valid.
    """
    ids = {p.id for p in profiles}
    if not ids:
        return [], []
    template = profiles[0]
    query = select(ImportRun).where(ImportRun.tenant_id == template.tenant_id,
                                    ImportRun.supplier_id == template.supplier_id)
    hard, soft = [], []
    for r in db.scalars(query.with_for_update() if lock else query):
        if (r.config or {}).get("engine_mapping_profile_id") in ids:
            hard.append(r)
        elif r.profile_id in ids:
            (soft if r.approved_by is None else hard).append(r)
    return hard, soft


def detach(soft):
    for r in soft:
        r.profile_id = None
        if (r.analysis or {}).get("matched_profile_id") is not None:
            r.analysis = {**r.analysis, "matched_profile_id": None}


def template_plan(db, template, version=None, lock=False):
    versions = family(db, template, lock=lock)
    target = [version] if version is not None else versions
    hard, soft = run_references(db, target, lock=lock)
    references = {"import_runs": len(hard), "import_run_ids": [r.id for r in hard]}
    if version is not None and version.id == versions[0].id:
        reason = "only_version" if len(versions) == 1 else "active_version"
    elif references["import_runs"]:
        reason = "referenced"
    else:
        reason = None
    return {
        "template_id": versions[0].id,
        "template_key": template.config["template"]["template_key"],
        "name": versions[0].name,
        "active_version_id": versions[0].id,
        "active_version": versions[0].version,
        "version_id": version.id if version is not None else None,
        "deletable": reason is None,
        "reason": reason,
        "deletes": {"template_versions": len(target),
                    "version_ids": [p.id for p in target],
                    "approved_parameters_in_deleted_versions": sum(
                        len(p.config["template"].get("parameters", [])) for p in target)},
        "detaches": {"matched_uploads": len(soft), "run_ids": [r.id for r in soft]},
        "_soft": soft,
        "references": references,
        "keeps": ["import_runs", "source_files", "supplier_products", "import_suppliers",
                  "other_templates", "audit_log"],
    }


def version_of(db, who, id, version_id):
    template = tp.get_template(db, tenant(who), id)
    version = tp.get_template(db, tenant(who), version_id)
    if version.supplier_id != template.supplier_id or \
            version.config["template"]["template_key"] != template.config["template"]["template_key"]:
        raise HTTPException(404, "A sablonverzió nem található.")
    return template, version


@router.get("/import-templates/{id}/deletion")
def template_deletion_preview(id: int, who=Depends(require("imports.approve")),
                              db: Session = Depends(database)):
    """Dry run for the confirmation dialog: nothing is changed."""
    return public_plan(template_plan(db, tp.get_template(db, tenant(who), id)))


def public_plan(plan):
    return {k: v for k, v in plan.items() if not k.startswith("_")}


@router.delete("/import-templates/{id}")
def delete_template(id: int, who=Depends(require("imports.approve")),
                    db: Session = Depends(database)):
    """Delete one saved template with all of its versions (and nothing else)."""
    template = tp.get_template(db, tenant(who), id)
    plan = template_plan(db, template, lock=True)
    if not plan["deletable"]:
        raise HTTPException(409, TEMPLATE_REFUSALS[plan["reason"]])
    detach(plan["_soft"])
    db.flush()
    for p in family(db, template):
        db.delete(p)
    audit(db, who, "import.template_delete", plan["template_id"], tenant_id=template.tenant_id,
          supplier=template.supplier_id, name=plan["name"], template_key=plan["template_key"],
          versions=plan["deletes"]["version_ids"], detached_runs=plan["detaches"]["run_ids"])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, TEMPLATE_REFUSALS["referenced"])
    return {"deleted": True, "template_key": plan["template_key"],
            "version_ids": plan["deletes"]["version_ids"]}


@router.get("/import-templates/{id}/versions/{version_id}/deletion")
def version_deletion_preview(id: int, version_id: int, who=Depends(require("imports.approve")),
                             db: Session = Depends(database)):
    template, version = version_of(db, who, id, version_id)
    return public_plan(template_plan(db, template, version))


@router.delete("/import-templates/{id}/versions/{version_id}")
def delete_version(id: int, version_id: int, who=Depends(require("imports.approve")),
                   db: Session = Depends(database)):
    """Delete one older version; the active (newest) version is never touched."""
    template, version = version_of(db, who, id, version_id)
    plan = template_plan(db, template, version, lock=True)
    if not plan["deletable"]:
        raise HTTPException(409, TEMPLATE_REFUSALS[plan["reason"]])
    detach(plan["_soft"])
    db.flush()
    db.delete(version)
    audit(db, who, "import.template_version_delete", version.id, tenant_id=version.tenant_id,
          supplier=version.supplier_id, name=version.name, version=version.version,
          template_key=plan["template_key"], active_version_id=plan["active_version_id"],
          detached_runs=plan["detaches"]["run_ids"])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, TEMPLATE_REFUSALS["referenced"])
    return {"deleted": True, "version_id": version_id, "active_version_id": plan["active_version_id"]}
