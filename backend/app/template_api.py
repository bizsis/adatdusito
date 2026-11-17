"""Tenant-scoped generation, preview and immutable worktable downloads."""

import logging
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.security import require, database, audit
from app.access_control import need
from app.import_api import get_run
from app.template_models import ImportTemplate, TemplateChunk
from app import template_engine as te
from app.product_catalog import internal_categories

router = APIRouter(prefix="/api/v1/imports", tags=["Adatdúsítási munkasablon"])
log = logging.getLogger(__name__)


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=160)
    donor: int | None = None


class Generate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    rows: dict[int, Category] = Field(default_factory=dict, max_length=50000)
    mapping: dict[str, int] = Field(default_factory=dict, max_length=25)


def public(item):
    from app.models import now
    from datetime import timedelta

    retry_allowed = item.state in ("queued", "building") and (
        item.completed_at or item.created_at
    ) < now() - timedelta(minutes=30)
    return {
        "id": item.id,
        "run_id": item.run_id,
        "state": item.state,
        "error": item.error,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
        "options": item.options,
        "manifest": item.manifest,
        "retry_allowed": retry_allowed,
    }


@router.get("/template-categories")
def categories(who=Depends(require("imports.read"))):
    return [
        {"id": n["id"], "path": " / ".join(n["path"]), "donors": n["donors"]}
        for n in internal_categories().values()
    ]


@router.get("/runs/{run_id}/template")
def status(
    run_id: int, who=Depends(require("imports.read")), db: Session = Depends(database)
):
    run = get_run(db, who, run_id)
    item = te.latest(db, run.id)
    return public(item) if item else None


@router.post("/runs/{run_id}/templates")
def generate(
    run_id: int,
    body: Generate,
    who=Depends(require("imports.create")),
    db: Session = Depends(database),
):
    run = get_run(db, who, run_id)
    if body.category or body.rows:
        need(who, "products.classify")
    if run.state in ("uploaded", "processing"):
        raise HTTPException(409, "Várd meg a futó importlépés végét.")
    current = te.latest(db, run.id)
    if current and current.state in ("queued", "building"):
        from app.models import now
        from datetime import timedelta

        stamp = current.completed_at or current.created_at
        if stamp > now() - timedelta(minutes=30):
            raise HTTPException(409, "A sablonkészítés már folyamatban van.")
    try:
        item = te.create_snapshot(db, run, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, who, "import.template.generate", item.id, tenant_id=run.tenant_id)
    db.commit()
    try:
        te.enqueue(item.id)
    except Exception:
        log.exception("Could not enqueue template_id=%s", item.id)
        item.state, item.error = (
            "failed",
            "A sablonfeladat nem indítható. Próbáld újra később.",
        )
        db.commit()
    db.refresh(item)
    return public(item)


@router.get("/runs/{run_id}/templates/{template_id}/{format}")
def download(
    run_id: int,
    template_id: int,
    format: Literal["csv", "xlsx"],
    who=Depends(require("imports.read")),
    db: Session = Depends(database),
):
    get_run(db, who, run_id)
    item = db.get(ImportTemplate, template_id)
    if not item or item.run_id != run_id:
        raise HTTPException(404, "A sablon nem található.")
    if item.state != "ready_for_enrichment":
        raise HTTPException(409, "A sablon még nem tölthető le.")
    # Copy bounded chunks into a spooled file before the request DB closes.
    # Slow downloads hold neither a database transaction nor all bytes in RAM.
    import tempfile

    file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    try:
        for chunk in db.scalars(
            select(TemplateChunk)
            .where(
                TemplateChunk.template_id == template_id, TemplateChunk.format == format
            )
            .order_by(TemplateChunk.ordinal)
            .execution_options(yield_per=16)
        ):
            file.write(chunk.data)
        file.seek(0)
        db.rollback()  # End the read transaction before streaming to a slow client.
    except BaseException:
        file.close()
        raise

    def stream():
        try:
            yield from iter(lambda: file.read(60000), b"")
        finally:
            file.close()

    content_type = (
        "text/csv; charset=utf-8"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return StreamingResponse(
        stream(),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="sablon-{run_id}-{template_id}.{format}"',
            "Cache-Control": "no-store",
        },
    )
