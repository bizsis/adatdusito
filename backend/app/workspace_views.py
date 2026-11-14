"""Read-only product view; CODEX 07 ingestion remains unchanged."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.security import require, database
from app.import_api import tenant
from app.import_models import SupplierProduct, Supplier
from app.import_parser import FIELDS

router = APIRouter(prefix="/api/v1/workspace", tags=["Termékadatok"])


@router.get("/products")
def products(
    cursor: int = Query(0, ge=0),
    who=Depends(require("products.read")),
    db: Session = Depends(database),
):
    tid = tenant(who)
    rows = db.execute(
        select(SupplierProduct, Supplier.name)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .where(
            SupplierProduct.tenant_id == tid,
            Supplier.tenant_id == tid,
            SupplierProduct.id > cursor,
        )
        .order_by(SupplierProduct.id)
        .limit(26)
    ).all()
    return {
        "items": [
            {
                "id": p.id,
                "fields": p.data,
                "supplier_name": name,
                "source_line": p.last_line,
            }
            for p, name in rows[:25]
        ],
        "next_cursor": rows[24][0].id if len(rows) > 25 else None,
        "field_labels": {k: v[0] for k, v in FIELDS.items()},
    }
