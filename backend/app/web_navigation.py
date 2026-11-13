"""One shared shopper-facing navigation, with explicit Marketplace bindings only.

The observed navigation contains no duplicate Marketplace catalog. Bindings are
immutable/audited reference_observations in the existing application database.
"""

from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ReferenceObservation
from app.security import database, require
from app.db import reference_database
from app.reference import load_tree, list_parameters

TREE_KINDS = {"department", "section", "category"}
BINDABLE_KINDS = {"section", "category"}


class Navigation:
    def __init__(self, data):
        self.data = data
        self.nodes = {n["id"]: n for n in data["nodes"]}
        if len(self.nodes) != len(data["nodes"]):
            raise ValueError("Duplicate navigation identity")
        self.children = {}
        for n in data["nodes"]:
            self.children.setdefault(n["parent_id"], []).append(n["id"])
        self.visible = {n["id"] for n in data["nodes"] if n["kind"] in TREE_KINDS}

    def proof_key(self, id):
        return id + "@" + self.data["archive_sha256"]

    def path(self, id):
        result = []
        seen = set()
        while id:
            if id in seen or id not in self.nodes:
                raise ValueError("Invalid navigation path")
            seen.add(id)
            result.append(id)
            id = self.nodes[id]["parent_id"]
        return list(reversed(result))

    def summary(self, id):
        n = self.nodes[id]
        return {k: n[k] for k in ["id", "name", "kind", "hierarchy_status"]}

    def related(self, id):
        result = []
        pending = list(self.children.get(id, []))
        for key in pending:
            node = self.nodes[key]
            if key not in self.visible:
                result.append(node)
                pending.extend(self.children.get(key, []))
        return result


@lru_cache
def navigation():
    return Navigation(
        json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "reference_data/web_navigation.json"
            ).read_text(encoding="utf-8")
        )
    )


def observations(db, nav):
    rows = db.scalars(
        select(ReferenceObservation)
        .where(
            ReferenceObservation.source_key == "emag_webshop",
            ReferenceObservation.source_category_id.in_(
                [nav.proof_key(id) for id in nav.nodes]
            ),
        )
        .order_by(ReferenceObservation.id.desc())
    )
    latest = {}
    reverse = {nav.proof_key(id): id for id in nav.nodes}
    for row in rows:
        latest.setdefault(reverse[row.source_category_id], row)
    return latest


def mapping_tree(latest):
    if not any(r.mapping_status == "confirmed" for r in latest.values()):
        return None
    with reference_database() as conn:
        return load_tree(conn)


def dto(nav, id, latest, tree):
    node = nav.nodes[id]
    record = latest.get(id)
    mapped = None
    if (
        node["kind"] in BINDABLE_KINDS
        and record
        and record.mapping_status == "confirmed"
        and tree
    ):
        internal = tree.external.get(record.canonical_emag_id)
        if internal in tree.visible_all:
            mapped = tree.item(internal, "all")
    status = (
        ("confirmed" if mapped else "unavailable")
        if record and record.mapping_status == "confirmed"
        else record.mapping_status
        if record
        else "pending"
        if node["kind"] in BINDABLE_KINDS
        else "not_applicable"
    )
    return {
        **node,
        "children_count": sum(k in nav.visible for k in nav.children.get(id, [])),
        "path": [nav.summary(k) for k in nav.path(id)],
        "ancestors": [nav.summary(k) for k in nav.path(id)[:-1]],
        "related_links": nav.related(id),
        "mapping_status": status,
        "mapping_evidence_id": record.id if record else None,
        "canonical_emag_id": mapped["emag_category_id"] if mapped else None,
        "marketplace_category_id": mapped["id"] if mapped else None,
        "selectable": bool(
            mapped and mapped["selectable"] and node["kind"] == "category"
        ),
        "parameter_count": mapped["parameter_count"] if mapped else None,
        "mandatory_parameter_count": mapped["mandatory_parameter_count"]
        if mapped
        else None,
        "optional_parameter_count": mapped["optional_parameter_count"]
        if mapped
        else None,
        "snapshot_sha256": nav.data["archive_sha256"],
    }


def require_node(nav, id):
    if id not in nav.visible:
        raise HTTPException(404, "A navigációs kategória nem található.")


router = APIRouter(
    prefix="/api/v1/reference/navigation",
    tags=["Egységes webshop-navigáció"],
    dependencies=[Depends(require("reference.read"))],
)


@router.get("")
def nodes(
    parent_id: str | None = Query(None, max_length=160),
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    nav = navigation()
    if parent_id:
        require_node(nav, parent_id)
    ids = nav.children.get(parent_id, []) if not q else list(nav.nodes)
    ids = [
        id
        for id in ids
        if id in nav.visible
        and (not q or q.casefold() in nav.nodes[id]["name"].casefold())
    ]
    # Source order is retained, including across search results and pages.
    latest = observations(db, nav)
    tree = mapping_tree(latest)
    return {
        "items": [dto(nav, id, latest, tree) for id in ids[offset : offset + limit]],
        "total": len(ids),
        "offset": offset,
        "limit": limit,
        "snapshot_sha256": nav.data["archive_sha256"],
    }


@router.get("/coverage")
def coverage(db: Session = Depends(database)):
    nav = navigation()
    latest = observations(db, nav)
    tree = mapping_tree(latest)
    return {
        "root_count": len(nav.children.get(None, [])),
        "manifest_link_count": nav.data["manifest_link_count"],
        "kind_counts": dict(Counter(n["kind"] for n in nav.nodes.values())),
        "hierarchy_needs_review": len(nav.data["issues"]),
        "details_verification": nav.data.get("details_verification"),
        "confirmed_bindings": sum(
            dto(nav, id, latest, tree)["mapping_status"] == "confirmed"
            for id in nav.visible
        ),
        "full_category_tree_verified": False,
        "archive_sha256": nav.data["archive_sha256"],
        "observed_at": nav.data["observed_at"],
        "html_url_disagreements": nav.data["html_url_disagreements"],
    }


@router.get("/{node_id}")
def detail(node_id: str, db: Session = Depends(database)):
    nav = navigation()
    require_node(nav, node_id)
    latest = observations(db, nav)
    return dto(nav, node_id, latest, mapping_tree(latest))


def confirmed(node_id, db, selection=False):
    nav = navigation()
    require_node(nav, node_id)
    latest = observations(db, nav)
    node = dto(nav, node_id, latest, mapping_tree(latest))
    if node["mapping_status"] != "confirmed" or node["kind"] not in BINDABLE_KINDS:
        raise HTTPException(
            409,
            "Nincs igazolt Marketplace-megfeleltetés; paramétert névegyezésből nem töltünk be.",
        )
    if selection and not node["selectable"]:
        raise HTTPException(
            409, "Ez a navigációs elem nem használható termékbesorolásra."
        )
    return node


@router.get("/{node_id}/parameters")
def parameters(
    node_id: str,
    q: str = Query("", max_length=120),
    mandatory: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(database),
):
    node = confirmed(node_id, db)
    return list_parameters(
        category_id=node["marketplace_category_id"],
        q=q,
        mandatory=mandatory,
        view="all",
        offset=offset,
        limit=limit,
    )


@router.get("/{node_id}/selection")
def selection(node_id: str, db: Session = Depends(database)):
    node = confirmed(node_id, db, selection=True)
    return {
        "navigation_id": node_id,
        "snapshot_sha256": node["snapshot_sha256"],
        "mapping_evidence_id": node["mapping_evidence_id"],
        "canonical_reference_key": f"emag_marketplace:{node['canonical_emag_id']}",
        "category_id": node["marketplace_category_id"],
        "emag_category_id": node["canonical_emag_id"],
        "parameter_inheritance": False,
        "reference_writes_allowed": False,
        "new_value_policy": "proposal_requires_approval",
    }
