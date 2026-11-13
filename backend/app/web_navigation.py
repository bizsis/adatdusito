"""One common tree: existing source categories, automatic matches and app choices."""

from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ReferenceObservation, CategoryOverride, now
from app.security import database, require, Identity, audit
from app.db import reference_database
from app.reference import load_tree, list_parameters
from app import catalog_store
from pydantic import BaseModel, ConfigDict, Field

TREE_KINDS = {"department", "section", "category"}
BINDABLE_KINDS = {"section", "category"}


class Navigation:
    def __init__(self, data):
        self.data = data
        self.nodes = {n["id"]: n for n in data["nodes"]}
        if len(self.nodes) != len(data["nodes"]):
            raise ValueError("Duplicate navigation identity")
        # Roots are a versioned list of observed identities, never every row
        # whose parent happens to be null. Do not repair the source graph here.
        self.roots = list(data["verified_root_ids"])
        if (
            len(self.roots) != 13
            or len(set(self.roots)) != 13
            or any(
                key not in self.nodes
                or self.nodes[key]["kind"] != "department"
                or self.nodes[key]["parent_id"] is not None
                or self.nodes[key]["hierarchy_status"] != "verified_dom"
                for key in self.roots
            )
        ):
            raise ValueError("Expected 13 explicitly verified navigation roots")
        self.children = {}
        for n in data["nodes"]:
            self.children.setdefault(n["parent_id"], []).append(n["id"])
        self.visible = {n["id"] for n in data["nodes"] if n["kind"] in TREE_KINDS}

        self.placement = {key: "verified_tree" for key in self.roots}
        for key in self.nodes:
            trail = []
            current = key
            seen = set()
            while current not in self.placement:
                if current in seen:
                    status = "cycle"
                    break
                if current not in self.nodes:
                    status = "missing_parent"
                    break
                seen.add(current)
                trail.append(current)
                node = self.nodes[current]
                if node["parent_id"] is None:
                    status = "unclassified"
                    break
                current = node["parent_id"]
            else:
                status = self.placement[current]
            for ancestor in reversed(trail):
                if status == "verified_tree" and self.nodes[ancestor][
                    "hierarchy_status"
                ] not in {"verified_dom", "verified_reference", "verified_assignment"}:
                    status = "needs_review"
                self.placement[ancestor] = status

    def tree_children(self, id):
        return [
            key
            for key in self.children.get(id, [])
            if key in self.visible and self.placement[key] == "verified_tree"
        ]

    def proof_key(self, id):
        return id + "@" + self.data["archive_sha256"]

    def path(self, id):
        result = []
        seen = set()
        while id:
            if id in seen or id not in self.nodes:
                break
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
        seen = set()
        for key in pending:
            if key in seen:
                continue
            seen.add(key)
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


def resolved(db):
    base = navigation()
    latest = observations(db, base)
    with reference_database() as conn:
        tree = load_tree(conn)
    overrides = list(db.scalars(select(CategoryOverride)))
    from app.fixed_navigation import resolve_fixed

    return resolve_fixed(base, tree, latest, overrides), latest, tree


def dto(nav, id, latest, tree):
    node = nav.nodes[id]
    record = latest.get(id)
    mapped = None
    if tree and hasattr(nav, "bindings"):
        internal = nav.bindings.get(id)
        if internal is not None:
            mapped = tree.item(internal, "archive")
    from app.fixed_navigation import binding_status

    status = binding_status(nav, id)
    from app.parameter_profiles import profile_info

    profiles = profile_info(nav, id)
    return {
        **node,
        "children_count": len(nav.tree_children(id)),
        "placement_status": nav.placement[id],
        "path": [nav.summary(k) for k in nav.path(id)],
        "ancestors": [nav.summary(k) for k in nav.path(id)[:-1]],
        "related_links": nav.related(id),
        "mapping_status": status,
        "parameter_profiles": profiles,
        "parameter_profile_count": len(profiles),
        "parameter_source_category_id": profiles[0]["source_category_id"]
        if len(profiles) == 1
        else None,
        "parameter_source_category_ids": [p["source_category_id"] for p in profiles],
        "mapping_method": getattr(nav, "methods", {}).get(id),
        "reference_name": mapped["name"] if mapped else None,
        "reference_key": f"emag_marketplace:{mapped['emag_category_id']}"
        if mapped
        else None,
        "archived": bool(tree and mapped and mapped["id"] in tree.deleted),
        "inactive": False,
        "reference_hierarchy_error": mapped["hierarchy_error"] if mapped else None,
        "mapping_candidates": [
            tree.light(k)
            | {
                "path_names": [
                    tree.rows[p]["name"] for p in tree.path_ids(k, "archive")
                ]
            }
            for k in getattr(nav, "candidates", {}).get(id, [])
        ]
        if tree
        else [],
        "mapping_evidence_id": record.id if record else None,
        "canonical_emag_id": mapped["emag_category_id"]
        if mapped and len(profiles) == 1
        else None,
        "marketplace_category_id": mapped["id"] if mapped else None,
        "selectable": bool(
            node["kind"] == "category" and not node.get("structural_only")
        ),
        "parameter_count": sum(p["parameter_count"] for p in profiles)
        if profiles
        else None,
        "mandatory_parameter_count": mapped["mandatory_parameter_count"]
        if mapped and len(profiles) == 1
        else None,
        "optional_parameter_count": mapped["optional_parameter_count"]
        if mapped and len(profiles) == 1
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
    scope: Literal["tree", "unclassified", "unavailable"] = "tree",
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.nodes(db, version, parent_id, q, scope, offset, limit)
    nav, latest, tree = resolved(db)
    if parent_id:
        require_node(nav, parent_id)
    from app.fixed_navigation import binding_scope_keys

    if scope != "tree":
        ids = binding_scope_keys(nav, scope)
    elif q:
        ids = list(nav.nodes)
    elif parent_id:
        ids = nav.tree_children(parent_id)
    else:
        ids = nav.roots
    ids = [
        id
        for id in ids
        if id in nav.visible
        and (
            not q
            or q.casefold() in nav.nodes[id]["name"].casefold()
            or (
                id in nav.bindings
                and q.casefold() in tree.rows[nav.bindings[id]]["name"].casefold()
            )
            or (
                q.isdecimal()
                and id in nav.bindings
                and str(tree.rows[nav.bindings[id]]["emag_category_id"]) == q
            )
        )
    ]
    # Source order is retained, including across search results and pages.
    return {
        "items": [dto(nav, id, latest, tree) for id in ids[offset : offset + limit]],
        "total": len(ids),
        "offset": offset,
        "limit": limit,
        "snapshot_sha256": nav.data["archive_sha256"],
    }


@router.get("/coverage")
def coverage(db: Session = Depends(database)):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.coverage(db, version)
    nav, latest, tree = resolved(db)
    return {
        "reference_coverage": nav.reference_coverage,
        "root_count": len(nav.roots),
        "unclassified_count": sum(
            key in nav.visible and status != "verified_tree"
            for key, status in nav.placement.items()
        ),
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
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.detail(db, version, node_id)
    nav, latest, tree = resolved(db)
    require_node(nav, node_id)
    return dto(nav, node_id, latest, tree)


def confirmed(node_id, db, selection=False):
    nav, latest, tree = resolved(db)
    require_node(nav, node_id)
    node = dto(nav, node_id, latest, tree)
    if node["mapping_status"] != "confirmed" or node["kind"] not in BINDABLE_KINDS:
        raise HTTPException(
            409,
            "A kategória többértelmű vagy még nincs összekapcsolva; adminisztrátori választás szükséges.",
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
    profile_emag_id: int | None = Query(None, gt=0),
    db: Session = Depends(database),
):
    from app.parameter_profiles import choose_profile

    version = catalog_store.active_version(db)
    if version:
        nav = catalog_store.index(db, version)
        if node_id not in nav.visible:
            raise HTTPException(404, "A kategória nem található.")
        internal = choose_profile(nav, node_id, profile_emag_id)
        if internal is None:
            return {"items": [], "total": 0, "offset": offset, "limit": limit}
        category_id = next(
            r.target_id
            for r in nav.owned_categories.values()
            if r.source_id == internal
        )
        return catalog_store.parameters(
            db, version, category_id, q, mandatory, "all", offset, limit
        )
    nav, _, tree = resolved(db)
    require_node(nav, node_id)
    internal = choose_profile(nav, node_id, profile_emag_id)
    if internal is None:
        return {"items": [], "total": 0, "offset": offset, "limit": limit}
    return list_parameters(
        category_id=internal,
        q=q,
        mandatory=mandatory,
        view="all",
        offset=offset,
        limit=limit,
        db=db,
    )


@router.get("/{node_id}/selection")
def selection(node_id: str, db: Session = Depends(database)):
    version = catalog_store.active_version(db)
    if version:
        node = catalog_store.detail(db, version, node_id)
        if not node["selectable"]:
            raise HTTPException(
                409, "Strukturális vagy archivált kategória nem választható."
            )
        return {
            "navigation_id": node_id,
            "category_id": node["unified_category_id"],
            "catalog_version_id": version.id,
            "canonical_reference_key": f"fixed_category:{node_id}",
            "parameter_source_category_id": node["parameter_source_category_id"],
            "parameter_source_category_ids": node["parameter_source_category_ids"],
            "parameter_profile_required": node["parameter_profile_count"] > 1,
            "parameter_inheritance": False,
            "reference_writes_allowed": False,
            "new_value_policy": "proposal_requires_approval",
        }
    node = confirmed(node_id, db, selection=True)
    return {
        "navigation_id": node_id,
        "snapshot_sha256": node["snapshot_sha256"],
        "mapping_evidence_id": node["mapping_evidence_id"],
        "canonical_reference_key": f"fixed_category:{node_id}",
        "parameter_source_category_id": node["parameter_source_category_id"],
        "parameter_source_category_ids": node["parameter_source_category_ids"],
        "parameter_profile_required": node["parameter_profile_count"] > 1,
        "category_id": node["marketplace_category_id"],
        "emag_category_id": node["canonical_emag_id"],
        "parameter_inheritance": False,
        "reference_writes_allowed": False,
        "new_value_policy": "proposal_requires_approval",
    }


@router.get("/choices/reference")
def reference_choices(
    q: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.reference_choices(db, version, q, limit)
    nav, _, tree = resolved(db)
    term = q.casefold()
    keys = [
        k
        for k, row in tree.rows.items()
        if k not in tree.deleted
        and (term in row["name"].casefold() or str(row["emag_category_id"]) == q)
    ]
    return {
        "items": [
            tree.light(k)
            | {
                "path_names": [
                    tree.rows[p]["name"] for p in tree.path_ids(k, "archive")
                ]
            }
            for k in keys[:limit]
        ],
        "total": len(keys),
    }


@router.get("/choices/parents")
def parent_choices(
    q: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.parent_choices(db, version, q, limit)
    nav, _, _ = resolved(db)
    keys = [
        k
        for k in nav.nodes
        if k in nav.visible
        and nav.placement[k] == "verified_tree"
        and (not q or q.casefold() in nav.nodes[k]["name"].casefold())
    ]
    return {
        "items": [
            nav.summary(k) | {"path_names": [nav.nodes[p]["name"] for p in nav.path(k)]}
            for k in keys[:limit]
        ],
        "total": len(keys),
    }


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_emag_id: int | None = Field(None, gt=0)
    category_id: int | None = Field(None, ge=1_000_000_000, lt=2**53)
    parent_id: str | None = Field(None, max_length=160)
    disable_automatic: bool = False
    reset: bool = False


@router.post("/{node_id}/assignment")
def assign_category(
    node_id: str,
    body: AssignmentInput,
    who: Identity = Depends(require("system.manage")),
    db: Session = Depends(database),
):
    version = catalog_store.active_version(db)
    if version:
        return catalog_store.assign(db, version, node_id, body, who)
    if body.category_id is not None:
        raise HTTPException(
            409, "Közös adatbázis-azonosítóhoz előbb aktiváld az importált katalógust."
        )
    nav, _, tree = resolved(db)
    require_node(nav, node_id)
    node = nav.nodes[node_id]
    if node["kind"] not in BINDABLE_KINDS:
        raise HTTPException(409, "Főcsoporthoz nem rendelhető termékkategória.")
    if body.reset and len(body.model_fields_set) > 1:
        raise HTTPException(422, "A visszaállítás nem kombinálható más módosítással.")
    if body.disable_automatic and body.canonical_emag_id is not None:
        raise HTTPException(
            422, "Az automatikus összerendelés tiltása mellett ne adj meg kategóriát."
        )
    if "parent_id" in body.model_fields_set:
        raise HTTPException(409, "A rögzített kategóriahierarchia nem módosítható.")
    if node["kind"] != "category" or node.get("structural_only"):
        raise HTTPException(
            409, "Navigációs gyűjtőponthoz nem szükséges paraméter-hozzárendelés."
        )
    if body.reset:
        row = db.get(CategoryOverride, node_id)
        if row:
            db.delete(row)
    else:
        if not body.model_fields_set:
            raise HTTPException(422, "Válassz kategóriát vagy elhelyezést.")
        if body.canonical_emag_id is not None:
            if (
                body.canonical_emag_id not in tree.external
                or tree.external[body.canonical_emag_id] in tree.deleted
            ):
                raise HTTPException(409, "Ismeretlen vagy törölt kategória.")
            if (
                node_id.startswith("ref-")
                and body.canonical_emag_id != node["canonical_emag_id"]
            ):
                raise HTTPException(409, "A forráskategória azonosítója nem írható át.")
        if "parent_id" in body.model_fields_set and body.parent_id is not None:
            if (
                body.parent_id not in nav.visible
                or nav.placement[body.parent_id] != "verified_tree"
                or node_id in nav.path(body.parent_id)
            ):
                raise HTTPException(
                    409, "A szülő nem elhelyezett kategória, vagy ciklust okozna."
                )
        row = db.get(CategoryOverride, node_id)
        if row is None:
            row = CategoryOverride(
                node_id=node_id,
                source_key="emag_marketplace",
                override_parent=False,
                disable_automatic=False,
            )
            db.add(row)
        if "canonical_emag_id" in body.model_fields_set:
            if body.canonical_emag_id:
                row.disable_automatic = False
            row.source_category_id = (
                str(body.canonical_emag_id) if body.canonical_emag_id else None
            )
        if "parent_id" in body.model_fields_set:
            row.parent_id, row.override_parent = body.parent_id, True
        if "disable_automatic" in body.model_fields_set:
            row.disable_automatic = body.disable_automatic
            if body.disable_automatic:
                row.source_category_id = None
        row.actor_id, row.updated_at = who.user.id, now()
        row.source_snapshot = (
            navigation().data["archive_sha256"]
            if not node_id.startswith("ref-")
            else None
        )
    audit(db, who, "category.assignment", node_id, **body.model_dump())
    db.commit()
    updated, latest, tree = resolved(db)
    # A newly matched native category is represented by its existing webshop node.
    return {
        "saved": True,
        "node_id": node_id,
        "reference_coverage": updated.reference_coverage,
    }
