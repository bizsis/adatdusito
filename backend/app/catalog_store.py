"""Owned catalog reads. An active catalog never falls back to the source DB."""

from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select, func, or_, case
from app.models import (
    Setting,
    CatalogVersion,
    CatalogNode,
    CatalogCategory,
    CatalogLinkEntry,
    CatalogParameter,
    CatalogValue,
    CatalogSourceMapping,
)
from app.catalog_constants import ACTIVE_KEY, COMMON_ID_START, SOURCE


def active_version(db):
    setting = db.get(Setting, ACTIVE_KEY)
    if not setting or setting.value == "legacy":
        return None
    try:
        version = db.get(CatalogVersion, int(setting.value))
    except ValueError:
        version = None
    if (
        not version
        or version.status != "ready"
        or not version.verification
        or not version.verification.get("complete")
    ):
        raise HTTPException(503, "Az aktív közös referenciaadat-verzió nem elérhető.")
    data_version_id(db, version)
    return version


def data_version_id(db, version):
    seen = set()
    current = version
    while current.counters.get("data_version_id") is not None:
        if current.id in seen:
            raise HTTPException(503, "Ciklikus katalógus-adatverzió.")
        seen.add(current.id)
        current = db.get(CatalogVersion, int(current.counters["data_version_id"]))
        if (
            not current
            or current.status != "ready"
            or not current.verification
            or not current.verification.get("complete")
        ):
            raise HTTPException(503, "Hiányzó közös katalógus-adatverzió.")
    return current.id


def source_category_id(db, version, category_id):
    if category_id >= COMMON_ID_START:
        if db.scalar(
            select(CatalogNode.key)
            .where(
                CatalogNode.version_id == version.id,
                CatalogNode.category_id == category_id,
            )
            .limit(1)
        ):
            return category_id
        for row in db.scalars(
            select(CatalogNode).where(CatalogNode.version_id == version.id)
        ):
            if category_id in row.data.get("category_alias_ids", []):
                return row.category_id
        return category_id
    mapping = db.get(
        CatalogSourceMapping,
        (data_version_id(db, version), "category", SOURCE, category_id),
    )
    if not mapping:
        raise HTTPException(404, "A kategória nem található.")
    return mapping.target_id


def index(db, version):
    from app.web_navigation import Navigation

    rows = list(
        db.scalars(select(CatalogNode).where(CatalogNode.version_id == version.id))
    )
    rows.sort(key=lambda r: (r.data["order"], r.key))
    nav = Navigation(
        {
            "nodes": [r.data for r in rows],
            "verified_root_ids": version.counters["root_ids"],
            "archive_sha256": version.counters["navigation_snapshot"],
        }
    )
    nav.owned_nodes = {r.key: r for r in rows}
    nav.owned_categories = {
        r.target_id: r
        for r in db.scalars(
            select(CatalogSourceMapping).where(
                CatalogSourceMapping.version_id == data_version_id(db, version),
                CatalogSourceMapping.kind == "category",
                CatalogSourceMapping.source_key == SOURCE,
            )
        )
    }
    nav.owned_counts = {
        r.category_id: {
            "total": r.total,
            "mandatory": int(r.mandatory or 0),
            "optional": int(r.optional or 0),
        }
        for r in db.execute(
            select(
                CatalogLinkEntry.category_id,
                func.count().label("total"),
                func.sum(
                    case((CatalogLinkEntry.is_mandatory.is_(True), 1), else_=0)
                ).label("mandatory"),
                func.sum(
                    case((CatalogLinkEntry.is_mandatory.is_(False), 1), else_=0)
                ).label("optional"),
            )
            .where(CatalogLinkEntry.version_id == data_version_id(db, version))
            .group_by(CatalogLinkEntry.category_id)
        )
    }
    return nav


def dto(db, version, nav, key):
    if key not in nav.visible:
        raise HTTPException(404, "A kategória nem található.")
    row, node = nav.owned_nodes[key], nav.nodes[key]
    source = nav.owned_categories.get(row.category_id)
    counts = nav.owned_counts.get(
        row.category_id, {"total": 0, "mandatory": 0, "optional": 0}
    )
    return {
        **node,
        "unified_category_id": row.category_id,
        "selectable": bool(
            node.get("selectable")
            and node["kind"] == "category"
            and not node.get("structural_only")
        ),
        "catalog_version_id": version.id,
        "children_count": len(nav.tree_children(key)),
        "parent_category_id": nav.owned_nodes[node["parent_id"]].category_id
        if node["parent_id"] in nav.owned_nodes
        else None,
        "placement_status": nav.placement[key],
        "path": [nav.summary(k) for k in nav.path(key)],
        "ancestors": [nav.summary(k) for k in nav.path(key)[:-1]],
        "related_links": nav.related(key),
        "mapping_status": "confirmed"
        if source
        else "pending"
        if node["kind"] in {"category", "section"}
        else "not_applicable",
        "canonical_emag_id": int(source.external_id) if source else None,
        "marketplace_category_id": source.source_id if source else None,
        "mapping_candidates": [],
        "mapping_evidence_id": None,
        "parameter_count": counts["total"],
        "mandatory_parameter_count": counts["mandatory"],
        "optional_parameter_count": counts["optional"],
        "unknown_parameter_count": counts["total"]
        - counts["mandatory"]
        - counts["optional"],
        "snapshot_sha256": nav.data["archive_sha256"],
        "parameter_source": "owned_catalog",
    }


def nodes(db, version, parent_id=None, q="", scope="tree", offset=0, limit=50):
    nav = index(db, version)
    if parent_id and parent_id not in nav.visible:
        raise HTTPException(404, "A szülőkategória nem található.")
    keys = (
        list(nav.nodes)
        if q
        else [k for k in nav.nodes if nav.placement[k] != "verified_tree"]
        if scope == "unclassified"
        else nav.tree_children(parent_id)
        if parent_id
        else nav.roots
    )
    term = q.casefold()
    keys = [
        k
        for k in keys
        if k in nav.visible
        and (
            not q
            or term in nav.nodes[k]["name"].casefold()
            or (
                nav.owned_nodes[k].category_id in nav.owned_categories
                and (
                    term
                    in nav.owned_categories[nav.owned_nodes[k].category_id]
                    .data["name"]
                    .casefold()
                    or q
                    == nav.owned_categories[nav.owned_nodes[k].category_id].external_id
                )
            )
            or q == str(nav.owned_nodes[k].category_id)
        )
    ]
    return {
        "items": [dto(db, version, nav, k) for k in keys[offset : offset + limit]],
        "total": len(keys),
        "offset": offset,
        "limit": limit,
        "snapshot_sha256": nav.data["archive_sha256"],
        "catalog_version_id": version.id,
    }


def detail(db, version, key):
    nav = index(db, version)
    return dto(db, version, nav, key)


def category_detail(db, version, category_id):
    category_id = source_category_id(db, version, category_id)
    nav = index(db, version)
    keys = [k for k in nav.visible if nav.owned_nodes[k].category_id == category_id]
    if not keys:
        raise HTTPException(404, "A kategória nem található.")
    key = next((k for k in keys if nav.placement[k] == "verified_tree"), keys[0])
    return {**dto(db, version, nav, key), "id": category_id}


def coverage(db, version):
    nav = index(db, version)
    source_ids = set(nav.owned_categories)
    placed = {
        nav.owned_nodes[k].category_id
        for k in nav.visible
        if nav.placement[k] == "verified_tree"
    } & source_ids
    represented_web = {
        nav.owned_nodes[k].category_id for k in nav.visible if not k.startswith("ref-")
    } & source_ids
    ambiguous = {
        c
        for k in nav.visible
        if nav.owned_nodes[k].category_id not in source_ids
        for c in nav.nodes[k].get("mapping_candidate_ids", [])
    }
    cyclic = {
        nav.owned_nodes[k].category_id
        for k in nav.visible
        if nav.placement[k] == "cycle"
    } & source_ids
    review = (represented_web | ambiguous | cyclic) - placed
    original = version.counters["coverage"]
    runtime = {
        **original,
        "placed_reference_count": len(placed),
        "review_reference_count": len(review),
        "unplaced_reference_count": len(source_ids - placed - review),
        "unlocated_reference_count": len(source_ids - placed),
        "reference_total": len(source_ids),
    }
    from app.category_tree import CategoryTree

    source_rows = [r.data for r in nav.owned_categories.values()]
    source_counts = {
        r.source_id: {
            **nav.owned_counts.get(
                r.target_id, {"total": 0, "mandatory": 0, "optional": 0}
            ),
            "unknown": 0,
        }
        for r in nav.owned_categories.values()
    }
    original_source = CategoryTree(source_rows, source_counts).coverage()
    return {
        **original_source,
        "source": "owned_catalog",
        "unified_parameter_count": version.verification.get("unified_parameter_count"),
        "unified_value_count": version.verification.get("unified_value_count"),
        "root_count": len(nav.roots),
        "reference_coverage": runtime,
        "catalog_version_id": version.id,
        "parameter_source": "owned_catalog",
        "source_record_counts": version.verification["processed"],
        "confirmed_bindings": len(source_ids),
        "hierarchy_needs_review": sum(
            not n["id"].startswith("ref-") and n["hierarchy_status"] == "needs_review"
            for n in nav.nodes.values()
        ),
        "manifest_link_count": 609,
        "full_category_tree_verified": False,
        "kind_counts": dict(Counter(n["kind"] for n in nav.nodes.values())),
        "archive_sha256": nav.data["archive_sha256"],
    }


def visible_categories(db, version, view):
    from app.category_tree import CategoryTree

    records = list(
        db.scalars(
            select(CatalogSourceMapping).where(
                CatalogSourceMapping.version_id == data_version_id(db, version),
                CatalogSourceMapping.kind == "category",
            )
        )
    )
    if view == "archive":
        return {r.target_id for r in records}
    tree = CategoryTree([r.data for r in records])
    visible = tree.navigation if view == "navigation" else tree.visible_all
    return {r.target_id for r in records if r.source_id in visible}


def parameters(
    db, version, category_id=None, q="", mandatory=None, view="all", offset=0, limit=25
):
    category_id = (
        source_category_id(db, version, category_id)
        if category_id is not None
        else None
    )
    stmt = (
        select(
            CatalogLinkEntry.link_id.label("id"),
            CatalogLinkEntry.link_id.label("category_parameter_id"),
            CatalogLinkEntry.parameter_id,
            CatalogLinkEntry.category_id,
            CatalogLinkEntry.name,
            CatalogParameter.type_id,
            CatalogLinkEntry.emag_parameter_id,
            CatalogLinkEntry.display_order,
            CatalogLinkEntry.is_mandatory,
            CatalogLinkEntry.is_filter,
            CatalogLinkEntry.allow_new_value,
            CatalogCategory.name.label("category_name"),
        )
        .join(CatalogParameter, CatalogParameter.id == CatalogLinkEntry.parameter_id)
        .join(CatalogCategory, CatalogCategory.id == CatalogLinkEntry.category_id)
        .where(CatalogLinkEntry.version_id == data_version_id(db, version))
    )
    if category_id is not None:
        stmt = stmt.where(CatalogLinkEntry.category_id == category_id)
    stmt = stmt.where(
        CatalogLinkEntry.category_id.in_(visible_categories(db, version, view))
    )
    if q:
        condition = CatalogLinkEntry.name.contains(q, autoescape=True)
        if q.isdecimal() and len(q) < 17:
            condition = or_(
                condition,
                CatalogParameter.id == int(q),
                CatalogLinkEntry.emag_parameter_id == int(q),
            )
        stmt = stmt.where(condition)
    if mandatory is not None:
        stmt = stmt.where(CatalogLinkEntry.is_mandatory == mandatory)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {
        "items": [
            dict(r)
            for r in db.execute(
                stmt.order_by(CatalogLinkEntry.display_order, CatalogLinkEntry.link_id)
                .offset(offset)
                .limit(limit)
            ).mappings()
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "catalog_version_id": version.id,
    }


def values(db, version, link_id, q="", after=0, view="all", limit=50):
    legacy_id = link_id < COMMON_ID_START
    if legacy_id:
        mapping = db.get(
            CatalogSourceMapping,
            (data_version_id(db, version), "parameter", SOURCE, link_id),
        )
        if not mapping:
            raise HTTPException(404, "A paraméter nem található.")
        link_id = mapping.target_id
    if legacy_id and 0 < after < COMMON_ID_START:
        cursor = db.get(
            CatalogSourceMapping, (data_version_id(db, version), "value", SOURCE, after)
        )
        if cursor and cursor.context_id == link_id:
            after = cursor.target_id
    entry = db.get(CatalogLinkEntry, (data_version_id(db, version), link_id))
    if not entry:
        raise HTTPException(404, "A paraméter nem található.")
    if entry.category_id not in visible_categories(db, version, view):
        raise HTTPException(404, "A paraméter ebben a nézetben nem található.")
    allowed = select(
        CatalogSourceMapping.target_id.label("value_id"),
        func.min(CatalogSourceMapping.ordinal).label("value_order"),
    ).where(
        CatalogSourceMapping.version_id == data_version_id(db, version),
        CatalogSourceMapping.kind == "value",
        CatalogSourceMapping.context_id == link_id,
        CatalogSourceMapping.target_id > after,
    )
    if q:
        allowed = allowed.join(
            CatalogValue, CatalogValue.id == CatalogSourceMapping.target_id
        ).where(CatalogValue.value_text.contains(q, autoescape=True))
    allowed = (
        allowed.group_by(CatalogSourceMapping.target_id)
        .order_by(CatalogSourceMapping.target_id)
        .limit(limit + 1)
        .subquery()
    )
    stmt = (
        select(CatalogValue.id, CatalogValue.value_text, allowed.c.value_order)
        .join(allowed, allowed.c.value_id == CatalogValue.id)
        .order_by(CatalogValue.id)
    )
    rows = list(db.execute(stmt).mappings())
    items = [dict(r) for r in rows[:limit]]
    definition = db.get(CatalogParameter, entry.parameter_id)
    return {
        "parameter": {
            "type_id": definition.type_id,
            "category_id": entry.category_id,
            "emag_parameter_id": entry.emag_parameter_id,
            "display_order": entry.display_order,
            "is_mandatory": entry.is_mandatory,
            "is_filter": entry.is_filter,
            "allow_new_value": entry.allow_new_value,
            "id": link_id,
            "parameter_id": entry.parameter_id,
            "name": entry.name,
        },
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": items[-1]["id"] if len(rows) > limit else None,
        "limit": limit,
        "catalog_version_id": version.id,
    }


def reference_choices(db, version, q, limit):
    nav = index(db, version)
    items = []
    first_node = {}
    for key in nav.nodes:
        if key in nav.visible:
            first_node.setdefault(nav.owned_nodes[key].category_id, key)
    for category_id, record in nav.owned_categories.items():
        data = record.data
        if "deleted" in data["name"].casefold() or (
            q
            and q.casefold() not in data["name"].casefold()
            and q not in (record.external_id, str(category_id))
        ):
            continue
        key = first_node.get(category_id)
        items.append(
            {
                "category_id": category_id,
                "emag_category_id": int(record.external_id),
                "name": data["name"],
                "path_names": [nav.nodes[k]["name"] for k in nav.path(key)]
                if key
                else [data["name"]],
            }
        )
    return {"items": items[:limit], "total": len(items)}


def parent_choices(db, version, q, limit):
    nav = index(db, version)
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


def assign(db, version, node_id, body, who):
    from app.models import CategoryOverride, now
    from app.security import audit

    setting = db.get(
        Setting,
        "reference_catalog_active",
        with_for_update=True,
        populate_existing=True,
    )
    if not setting or setting.value != str(version.id):
        raise HTTPException(
            409, "A katalógus időközben változott. Töltsd újra az oldalt."
        )
    nav = index(db, version)
    if node_id not in nav.visible or nav.nodes[node_id]["kind"] not in {
        "category",
        "section",
    }:
        raise HTTPException(409, "Csak meglévő kategória besorolása módosítható.")
    row = nav.owned_nodes[node_id]
    fields = body.model_fields_set
    if not fields or (body.reset and len(fields) != 1):
        raise HTTPException(422, "Válassz egy kategóriát vagy elhelyezést.")
    override = db.get(CategoryOverride, node_id)
    data = dict(row.data)
    if body.reset:
        row.category_id = data["_imported_category_id"]
        data["parent_id"], data["hierarchy_status"] = (
            data["_imported_parent_id"],
            data["_imported_hierarchy_status"],
        )
        if override:
            db.delete(override)
    else:
        if not override:
            override = CategoryOverride(
                node_id=node_id,
                source_key=SOURCE,
                override_parent=False,
                disable_automatic=False,
            )
            db.add(override)
        selected = body.category_id
        if body.canonical_emag_id:
            selected = next(
                (
                    k
                    for k, r in nav.owned_categories.items()
                    if r.external_id == str(body.canonical_emag_id)
                ),
                None,
            )
        if "category_id" in fields or "canonical_emag_id" in fields:
            if (
                selected not in nav.owned_categories
                or "deleted" in nav.owned_categories[selected].data["name"].casefold()
                or (node_id.startswith("ref-") and selected != row.category_id)
            ):
                raise HTTPException(
                    409, "Ismeretlen, archivált vagy nem módosítható kategória."
                )
            row.category_id = selected
            data["mapping_method"] = "administrator"
            override.source_category_id = nav.owned_categories[selected].external_id
            override.disable_automatic = False
        if "parent_id" in fields:
            if body.parent_id is not None and (
                body.parent_id not in nav.visible
                or nav.placement[body.parent_id] != "verified_tree"
                or node_id in nav.path(body.parent_id)
            ):
                raise HTTPException(409, "Érvénytelen szülő vagy ciklikus kapcsolat.")
            data["parent_id"], data["hierarchy_status"] = (
                body.parent_id,
                "verified_assignment",
            )
            override.parent_id, override.override_parent = body.parent_id, True
        if body.disable_automatic:
            raise HTTPException(422, "Az importált besorolás visszaállítását használd.")
        override.actor_id, override.updated_at = who.user.id, now()
        override.source_snapshot = (
            None
            if node_id.startswith("ref-")
            else version.counters["navigation_snapshot"]
        )
    source = nav.owned_categories.get(row.category_id)
    data.update(
        {
            "canonical_emag_id": int(source.external_id) if source else None,
            "marketplace_category_id": source.source_id if source else None,
            "selectable": bool(
                source
                and source.data["is_allowed"] == 1
                and "deleted" not in source.data["name"].casefold()
            ),
            "archived": bool(source and "deleted" in source.data["name"].casefold()),
            "inactive": bool(source and source.data["is_allowed"] != 1),
        }
    )
    row.data = data
    # A changed menu binding must never hide the previously represented category.
    remaining = {r.category_id for r in nav.owned_nodes.values()}
    for category_id, record in nav.owned_categories.items():
        if category_id in remaining:
            continue
        key = "ref-emag-" + record.external_id
        if key in nav.owned_nodes:
            continue
        meta = {
            "id": key,
            "name": record.data["name"],
            "kind": "category",
            "parent_id": None,
            "root_id": None,
            "order": len(nav.nodes),
            "hierarchy_status": "needs_review",
            "source_item_id": None,
            "source_department_id": "",
            "url": None,
            "canonical_emag_id": int(record.external_id),
            "marketplace_category_id": record.source_id,
            "selectable": record.data["is_allowed"] == 1
            and "deleted" not in record.data["name"].casefold(),
            "inactive": record.data["is_allowed"] != 1,
            "archived": "deleted" in record.data["name"].casefold(),
            "_imported_category_id": category_id,
            "_imported_parent_id": None,
            "_imported_hierarchy_status": "needs_review",
        }
        db.add(
            CatalogNode(
                version_id=version.id, key=key, category_id=category_id, data=meta
            )
        )
    audit(
        db,
        who,
        "category.assignment",
        node_id,
        catalog_version_id=version.id,
        **body.model_dump(),
    )
    db.commit()
    return {"saved": True, "node_id": node_id, "catalog_version_id": version.id}
