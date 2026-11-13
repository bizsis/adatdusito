"""Read-only eMAG browsing using the schema supplied by the operator.

FKs use internal IDs; category.parent_id contains an external eMAG category ID.
This metadata is deliberately separate from application migration metadata.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    or_,
    select,
)
from app.db import reference_database
from app.security import require

metadata = MetaData()
categories = Table(
    "emag_categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("emag_category_id", Integer),
    Column("name", String(255)),
    Column("parent_id", Integer),
    Column("is_allowed", Boolean),
    Column("is_ean_mandatory", Boolean),
    Column("is_warranty_mandatory", Boolean),
)
parameters = Table(
    "emag_category_parameters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("category_id", Integer),
    Column("emag_parameter_id", Integer),
    Column("name", String(255)),
    Column("type_id", Integer),
    Column("display_order", Integer),
    Column("is_mandatory", Boolean),
    Column("is_filter", Boolean),
    Column("allow_new_value", Boolean),
)
values = Table(
    "emag_parameter_values",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("parameter_id", Integer),
    Column("value_text", Text),
    Column("value_order", Integer),
)
router = APIRouter(
    prefix="/api/v1/reference",
    tags=["eMAG referencia"],
    dependencies=[Depends(require("reference.read"))],
)


def missing(detail):
    raise HTTPException(404, detail)


def category_select():
    parent = categories.alias("parent")
    return (
        select(
            *[c for c in categories.c if c.name != "parent_id"],
            categories.c.parent_id.label("parent_emag_id"),
            parent.c.id.label("parent_id"),
            parent.c.name.label("parent_name"),
        )
        .select_from(
            categories.outerjoin(
                parent,
                (parent.c.emag_category_id == categories.c.parent_id)
                & (parent.c.is_allowed == 1),
            )
        )
        .where(categories.c.is_allowed == 1)
    )


def category_json(row):
    item = dict(row)
    item["missing_parent"] = (
        item["parent_emag_id"] not in (None, 0) and item["parent_id"] is None
    )
    return item


def paginated(conn, stmt, offset, limit):
    total = conn.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    return {
        "items": [
            dict(row)
            for row in conn.execute(stmt.offset(offset).limit(limit)).mappings()
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/categories")
def list_categories(
    q: str = Query("", max_length=120),
    parent_id: int | None = Query(None, gt=0),
    roots: bool = True,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
):
    with reference_database() as conn:
        stmt = category_select()
        if parent_id is not None:
            parent_external = conn.scalar(
                select(categories.c.emag_category_id).where(
                    categories.c.id == parent_id, categories.c.is_allowed == 1
                )
            )
            if parent_external is None:
                missing("A szülőkategória nem található.")
            stmt = stmt.where(categories.c.parent_id == parent_external)
        elif not q and roots:
            stmt = stmt.where(
                or_(
                    categories.c.parent_id.is_(None),
                    categories.c.parent_id == 0,
                    stmt.selected_columns.parent_id.is_(None),
                )
            )
        if q:
            condition = categories.c.name.contains(q, autoescape=True)
            if q.isdecimal() and len(q) < 11:
                condition = or_(condition, categories.c.emag_category_id == int(q))
            stmt = stmt.where(condition)
        result = paginated(
            conn, stmt.order_by(categories.c.name, categories.c.id), offset, limit
        )
        result["items"] = [category_json(row) for row in result["items"]]
        return result


@router.get("/categories/{category_id}")
def category(category_id: int):
    with reference_database() as conn:
        row = (
            conn.execute(category_select().where(categories.c.id == category_id))
            .mappings()
            .first()
        )
        if not row:
            missing("A kategória nem található.")
        item = category_json(row)
        # Resolve ancestry by external IDs, detect cycles and missing parents.
        ancestors, seen = [], {category_id}
        parent_external = item["parent_emag_id"]
        hierarchy_error = None
        for _ in range(50):
            if parent_external in (None, 0):
                break
            parent = (
                conn.execute(
                    select(
                        categories.c.id,
                        categories.c.emag_category_id,
                        categories.c.name,
                        categories.c.parent_id,
                    ).where(
                        categories.c.emag_category_id == parent_external,
                        categories.c.is_allowed == 1,
                    )
                )
                .mappings()
                .first()
            )
            if not parent:
                hierarchy_error = "missing_parent"
                break
            if parent["id"] in seen:
                hierarchy_error = "cycle"
                break
            seen.add(parent["id"])
            ancestors.append(dict(parent))
            parent_external = parent["parent_id"]
        else:
            hierarchy_error = "depth_limit"
        item.update(
            ancestors=list(reversed(ancestors)), hierarchy_error=hierarchy_error
        )
        return item


@router.get("/parameters")
def list_parameters(
    category_id: int | None = Query(None, gt=0),
    q: str = Query("", max_length=120),
    mandatory: bool | None = None,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(25, ge=1, le=100),
):
    with reference_database() as conn:
        stmt = (
            select(
                parameters,
                categories.c.name.label("category_name"),
                categories.c.emag_category_id,
            )
            .join(categories, parameters.c.category_id == categories.c.id)
            .where(categories.c.is_allowed == 1)
        )
        if category_id is not None:
            if not conn.scalar(
                select(categories.c.id).where(
                    categories.c.id == category_id, categories.c.is_allowed == 1
                )
            ):
                missing("A kategória nem található.")
            stmt = stmt.where(parameters.c.category_id == category_id)
        if q:
            condition = parameters.c.name.contains(q, autoescape=True)
            if q.isdecimal() and len(q) < 11:
                condition = or_(condition, parameters.c.emag_parameter_id == int(q))
            stmt = stmt.where(condition)
        if mandatory is not None:
            stmt = stmt.where(parameters.c.is_mandatory == mandatory)
        return paginated(
            conn,
            stmt.order_by(parameters.c.display_order, parameters.c.id),
            offset,
            limit,
        )


@router.get("/parameters/{parameter_id}/values")
def parameter_values(
    parameter_id: int,
    q: str = Query("", max_length=120),
    after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    with reference_database() as conn:
        parameter = (
            conn.execute(
                select(parameters)
                .join(categories, parameters.c.category_id == categories.c.id)
                .where(parameters.c.id == parameter_id, categories.c.is_allowed == 1)
            )
            .mappings()
            .first()
        )
        if not parameter:
            missing("A paraméter nem található.")
        stmt = select(values).where(
            values.c.parameter_id == parameter_id, values.c.id > after
        )
        if q:
            stmt = stmt.where(values.c.value_text.contains(q, autoescape=True))
        rows = list(
            conn.execute(stmt.order_by(values.c.id).limit(limit + 1)).mappings()
        )
        has_more = len(rows) > limit
        items = [dict(row) for row in rows[:limit]]
        return {
            "parameter": dict(parameter),
            "items": items,
            "has_more": has_more,
            "next_cursor": items[-1]["id"] if has_more else None,
            "limit": limit,
        }
