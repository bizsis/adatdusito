"""TEMPLATE-RESULT-01 endpoints; contract: docs/design/TEMPLATE-RESULT-01-API.md.
Read only: nothing is imported or written except the download audit entry."""

import os
import tempfile

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import template_result as tr
from app.import_api import tenant
from app.security import audit, database, require

router = APIRouter(prefix="/api/v1/imports", tags=["Beszállítói import – UNAS-eredmény"])


@router.get("/import-templates/{id}/result")
def result(id: int, run_id: int | None = Query(None, gt=0), offset: int = Query(0, ge=0),
           limit: int = Query(50, ge=1, le=tr.MAX_LIMIT),
           who=Depends(require("imports.read")), db: Session = Depends(database)):
    template, run = tr.resolve(db, tenant(who), id, run_id)
    return tr.preview(db, template, run, offset, limit)


def headers_for(name, counters):
    return {"Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
            "X-Exported-Rows": str(counters["exported"]),
            "X-Excluded-Rows": str(counters["excluded"])}


def record(db, who, template, run, fmt, counters):
    audit(db, who, "import.template_result_download", template.id,
          tenant_id=run.tenant_id, version=template.version, run=run.id, format=fmt,
          exported=counters["exported"], excluded=counters["excluded"])
    db.commit()


@router.get("/import-templates/{id}/result.xlsx")
def result_xlsx(id: int, run_id: int | None = Query(None, gt=0),
                who=Depends(require("imports.read")), db: Session = Depends(database)):
    template, run = tr.resolve(db, tenant(who), id, run_id)
    headers, items, counters = tr.export_rows(db, template, run)
    handle, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(handle)
    try:
        tr.write_xlsx(path, headers, items)
    except Exception:
        os.unlink(path)
        raise
    record(db, who, template, run, "xlsx", counters)
    name = tr.filename(template, run, "xlsx")
    return FileResponse(
        path, filename=name, headers=headers_for(name, counters),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(os.unlink, path))


@router.get("/import-templates/{id}/result.csv")
def result_csv(id: int, run_id: int | None = Query(None, gt=0),
               who=Depends(require("imports.read")), db: Session = Depends(database)):
    template, run = tr.resolve(db, tenant(who), id, run_id)
    headers, items, counters = tr.export_rows(db, template, run)
    body = b"".join(tr.csv_chunks(headers, items))  # counters are final only afterwards
    record(db, who, template, run, "csv", counters)
    name = tr.filename(template, run, "csv")
    return StreamingResponse(iter([body]), media_type="text/csv; charset=utf-8",
                             headers=headers_for(name, counters))
