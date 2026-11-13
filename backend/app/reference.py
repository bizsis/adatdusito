"""Read-only eMAG browsing using the schema supplied by the operator.

FKs use internal IDs; category.parent_id contains an external eMAG category ID.
This metadata is deliberately separate from application migration metadata.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from sqlalchemy import case
from app.category_tree import CategoryTree
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    func,
    or_,
    select,
)
from app.db import reference_database
from app.security import require, database
from sqlalchemy.orm import Session
from app import catalog_store

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
    Column("raw_json", JSON),
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
    Column("raw_json", JSON),
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


View = Literal["navigation", "all", "archive"]


def load_tree(conn):
    rows = list(
        conn.execute(
            select(*(c for c in categories.c if c.name != "raw_json"))
        ).mappings()
    )
    groups = conn.execute(
        select(
            parameters.c.category_id,
            func.count().label("total"),
            func.sum(case((parameters.c.is_mandatory == 1, 1), else_=0)).label(
                "mandatory"
            ),
            func.sum(case((parameters.c.is_mandatory == 0, 1), else_=0)).label(
                "optional"
            ),
            func.sum(case((parameters.c.is_mandatory.is_(None), 1), else_=0)).label(
                "unknown"
            ),
        ).group_by(parameters.c.category_id)
    ).mappings()
    counts = {
        r["category_id"]: {
            k: int(r[k] or 0) for k in ["total", "mandatory", "optional", "unknown"]
        }
        for r in groups
    }
    return CategoryTree(rows, counts)


def get_category(tree, id, view):
    if id not in tree.visible(view):
        missing("A kategória nem található.")
    return tree.item(id, view, tree.children_counts(view))


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


@router.get("/coverage")
def coverage(db: Session = Depends(database)):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.coverage(db, version)
    with reference_database() as conn:
        from datetime import datetime, timezone

        return load_tree(conn).coverage() | {
            "observed_at": datetime.now(timezone.utc).isoformat()
        }


@router.get("/categories")
def list_categories(
    q: str = Query("", max_length=120),
    parent_id: int | None = Query(None, gt=0),
    roots: bool = True,
    view: View = "navigation",
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        parent = None
        if parent_id is not None:
            parent = catalog_store.category_detail(db, version, parent_id)["id"]
            nav = catalog_store.index(db, version)
            parent = next(
                (k for k in nav.visible if nav.owned_nodes[k].category_id == parent),
                None,
            )
        result = catalog_store.nodes(db, version, parent, q, "tree", offset, limit)
        result["items"] = [
            {
                **n,
                "navigation_id": n["id"],
                "id": n["unified_category_id"],
                "parent_id": n["parent_category_id"],
            }
            for n in result["items"]
        ]
        return result
    with reference_database() as conn:
        tree = load_tree(conn)
        ids = tree.visible(view)
        if parent_id is not None:
            get_category(tree, parent_id, view)
            ids = {id for id in ids if tree.parent(id, view) == parent_id}
        elif not q and roots:
            ids = {id for id in ids if tree.parent(id, view) is None}
        if q:
            term = q.casefold()
            ids = {
                id
                for id in ids
                if term in tree.rows[id]["name"].casefold()
                or str(tree.rows[id]["emag_category_id"]) == q
            }
        ordered = sorted(ids, key=lambda id: (tree.rows[id]["name"].casefold(), id))
        counts = tree.children_counts(view)
        return {
            "items": [
                tree.item(id, view, counts) for id in ordered[offset : offset + limit]
            ],
            "total": len(ordered),
            "offset": offset,
            "limit": limit,
            "view": view,
        }


@router.get("/categories/{category_id}")
def category(
    category_id: int, view: View = "navigation", db: Session = Depends(database)
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.category_detail(db, version, category_id)
    with reference_database() as conn:
        return get_category(load_tree(conn), category_id, view)


@router.get("/categories/{category_id}/selection")
def category_selection(category_id: int, db: Session = Depends(database)):
    """Stable reference contract for future imports; does not create any product."""
    version = catalog_store.active_version(db)
    if version:
        node = catalog_store.category_detail(db, version, category_id)
        if not node["selectable"]:
            raise HTTPException(409, "Strukturális kategória nem választható.")
        return {
            "category": node,
            "category_id": node["unified_category_id"],
            "parameter_inheritance": False,
            "reference_writes_allowed": False,
        }
    with reference_database() as conn:
        tree = load_tree(conn)
        item = get_category(tree, category_id, "all")
        if not item["selectable"]:
            raise HTTPException(
                409, "Strukturális kategória termékbesoroláshoz nem választható."
            )
        return {
            "category": item,
            "parameter_source_category_id": category_id,
            "parameter_inheritance": False,
            "new_value_policy": "proposal_requires_approval",
            "reference_writes_allowed": False,
        }


@router.get("/parameters")
def list_parameters(
    category_id: int | None = Query(None, gt=0),
    q: str = Query("", max_length=120),
    mandatory: bool | None = None,
    view: View = "navigation",
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.parameters(
            db, version, category_id, q, mandatory, view, offset, limit
        )
    with reference_database() as conn:
        tree = load_tree(conn)
        if category_id is not None:
            get_category(tree, category_id, view)
        visible_ids = tree.visible(view)
        stmt = (
            select(
                *(c for c in parameters.c if c.name != "raw_json"),
                categories.c.name.label("category_name"),
                categories.c.emag_category_id,
            )
            .join(categories, parameters.c.category_id == categories.c.id)
            .where(categories.c.id.in_(visible_ids))
        )
        if category_id is not None:
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
    view: View = "navigation",
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.values(db, version, parameter_id, q, after, view, limit)
    with reference_database() as conn:
        tree = load_tree(conn)
        parameter = (
            conn.execute(
                select(*(c for c in parameters.c if c.name != "raw_json"))
                .join(categories, parameters.c.category_id == categories.c.id)
                .where(
                    parameters.c.id == parameter_id,
                    categories.c.id.in_(tree.visible(view)),
                )
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
