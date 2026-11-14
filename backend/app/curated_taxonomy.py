"""The operator's 13-menu transcription, applied only to a new import version."""

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from app.unified_categories import normalized

PATH = Path(__file__).resolve().parents[1] / "reference_data/curated_taxonomy.json"


def specification():
    return json.loads(PATH.read_text(encoding="utf-8"))


def apply_taxonomy(base, spec=None):
    from app.web_navigation import Navigation

    spec = deepcopy(spec or specification())
    if len(spec["roots"]) != 13 or [r["name"] for r in spec["roots"]] != [
        base.nodes[k]["name"] for k in base.roots
    ]:
        raise ValueError(
            "Curated taxonomy must preserve the 13 verified roots and order"
        )
    lookup = defaultdict(list)
    for node in base.nodes.values():
        if node["kind"] != "department":
            lookup[(node["root_id"], normalized(node["name"]))].append(node)
    nodes, used, issues = [], set(), []

    def visit(item, root_id, parent_id, path, parent_name=None):
        if parent_id is None:
            original = base.nodes[root_id]
        else:
            candidates = [
                n
                for n in lookup[(root_id, normalized(item["name"]))]
                if n["id"] not in used
            ]
            pinned = base.nodes.get(item.get("id"))
            if pinned:
                if (
                    pinned["root_id"] != root_id
                    or normalized(pinned["name"]) != normalized(item["name"])
                    or (
                        item.get("source_identity_url")
                        and item["source_identity_url"] != pinned["url"]
                    )
                ):
                    raise ValueError("Invalid previous menu identity evidence")
                candidates = [pinned]
            if len(candidates) > 1:
                contextual = [
                    n
                    for n in candidates
                    if n["parent_id"] in base.nodes
                    and normalized(base.nodes[n["parent_id"]]["name"])
                    == normalized(parent_name or "")
                ]
                if len(contextual) == 1:
                    candidates = contextual
            original = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                issues.append(
                    {
                        "path": path,
                        "reason": "ambiguous_previous_menu_identity",
                        "candidates": [n["id"] for n in candidates],
                    }
                )
        key = item.get("id") or (
            original["id"]
            if original
            else "tax-04b-" + hashlib.sha256(" / ".join(path).encode()).hexdigest()[:20]
        )
        if key in used:
            raise ValueError("Duplicate curated navigation identity")
        if original and item.get("id") and item["id"] != original["id"]:
            raise ValueError("Curated node identity conflicts with existing menu")
        used.add(key)
        item["id"] = key
        product_role = item.get("role") == "product"
        structural_only = not product_role and bool(
            item.get("structural")
            or (
                original
                and original["kind"]
                in {
                    "parameter_filter",
                    "brand",
                    "campaign",
                    "collection",
                    "product_finder",
                    "search",
                    "related_section",
                }
            )
        )
        kind = (
            "department"
            if parent_id is None
            else "category"
            if product_role
            else "section"
            if structural_only
            else original["kind"]
            if original and original["kind"] in {"category", "section"}
            else "section"
            if item["children"]
            else "category"
        )
        node = {
            **(original or {}),
            "id": key,
            "name": item["name"],
            "parent_id": parent_id,
            "root_id": root_id,
            "kind": kind,
            "order": len(nodes),
            "hierarchy_status": "verified_dom"
            if parent_id is None
            else "verified_assignment",
            "parent_evidence": "operator_menu_transcription",
            "structural_only": structural_only,
            "source_department_id": base.nodes[root_id]["source_department_id"],
            "source_item_id": original.get("source_item_id") if original else None,
            "url": original.get("url") if original else None,
            "canonical_emag_id": None,
            "taxonomy_version": spec["version"],
            "taxonomy_path": path,
        }
        if original:
            node["previous_parent_id"] = original["parent_id"]
            node["source_link_kind"] = original["kind"]
        nodes.append(node)
        for child in item["children"]:
            visit(child, root_id, key, path + [child["name"]], item["name"])

    for key, root in zip(base.roots, spec["roots"]):
        visit(root, key, None, [root["name"]])
    declared = set(used)
    # Preserve evidence/related links, never promote omitted marketing or filters.
    for original in base.nodes.values():
        if original["id"] in used:
            continue
        node = deepcopy(original)
        node["parent_id"] = (
            node["parent_id"] if node["parent_id"] in declared else node["root_id"]
        )
        node["order"] = len(nodes)
        if node["kind"] in {"category", "section"}:
            node["source_link_kind"] = node["kind"]
            node["kind"] = "unknown_link"
            node["excluded_from_taxonomy"] = True
        nodes.append(node)
    data = {
        **base.data,
        "nodes": nodes,
        "curated_taxonomy_version": spec["version"],
        "curated_taxonomy_issues": issues,
    }
    nav = Navigation(data)
    nav.curated_spec = spec
    return nav


def plan_signature(base):
    from app.unified_categories import matching_rules

    content = {
        "taxonomy": specification(),
        "rules": matching_rules(),
        "navigation": base.data["archive_sha256"],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
