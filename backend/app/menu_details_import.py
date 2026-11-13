"""Corroborate the shared navigation using bounded, offline DOM evidence.

Observed webshop IDs and category-page identifiers never establish a canonical
Marketplace binding. Conflicting observations require review, not silent edits.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
import zipfile


def process_details_archive(path, navigation):
    if path.stat().st_size > 5_000_000:
        raise ValueError("Archive size limit")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if (
            len(names) != len(set(names))
            or set(names) != {"menu-details.json", "SHA256.txt"}
            or any(
                PurePosixPath(n).is_absolute()
                or ".." in PurePosixPath(n).parts
                or "\\" in n
                for n in names
            )
            or sum(i.file_size for i in infos) > 5_000_000
        ):
            raise ValueError("Unsafe or oversized details archive")
        raw = archive.read("menu-details.json")
        digest = hashlib.sha256(raw).hexdigest()
        manifest = archive.read("SHA256.txt").decode().split()
        if manifest != [digest, "menu-details.json"]:
            raise ValueError("Details checksum mismatch")
        evidence = json.loads(raw)
    if (
        evidence.get("format") != "adatdusito.menu-details.v2"
        or evidence.get("errors")
        or evidence.get("database_writes") is not False
        or evidence.get("automatic_marketplace_mapping") is not False
    ):
        raise ValueError("Expected complete, read-only v2 evidence")
    result = deepcopy(navigation)
    nodes = {n["id"]: n for n in result["nodes"]}
    roots = [n for n in result["nodes"] if n["parent_id"] is None]
    panels = evidence["menu_panels"]
    if len(panels) != 13 or len(roots) != 13:
        raise ValueError("Expected 13 departments")
    seen = set()
    counts = Counter()
    per_root = []
    for root, capture in zip(roots, panels):
        if root["name"] != capture["name"] or len(capture["dom"]) != 1:
            raise ValueError("Department name/order mismatch")
        panel = capture["dom"][0]
        depid = panel["department_id"]
        if depid != root["source_department_id"]:
            raise ValueError("Department identity mismatch")
        items = panel["items"]
        headings = {
            i["source_menu_item_id"]
            for i in items
            if "megamenu-item-heading" in i["classes"].split()
        }
        local = Counter()
        for order, item in enumerate(items):
            sid = item["source_menu_item_id"]
            key = f"web-item-{depid}-{sid}"
            if key in seen or key not in nodes:
                raise ValueError("Duplicate or unknown menu identity")
            seen.add(key)
            node = nodes[key]
            if (
                item["identifier_namespace"] != "webshop_menu_not_marketplace"
                or item["source_attributes"].get("data-id") != sid
                or node["name"] != item["name"]
                or node["order"] != order
                or item["dom_order"] != order
            ):
                raise ValueError("Menu identity/name/order mismatch")
            group = next(
                (
                    a
                    for a in item["ancestors"]
                    if "megamenu-group" in a["classes"].split()
                ),
                None,
            )
            groups = (
                []
                if group is None
                else [
                    c.removeprefix("megamenu-group-")
                    for c in group["classes"].split()
                    if c.startswith("megamenu-group-")
                ]
            )
            parent = groups[0] if len(groups) == 1 and groups[0] in headings else None
            status = "verified_dom" if group is None or parent else "needs_review"
            proof = (
                "explicit_group_class_to_heading_data_id"
                if parent
                else "department_containment"
                if group is None
                else "unresolved_group"
            )
            parent_key = f"web-item-{depid}-{parent}" if parent else root["id"]
            if (
                item["parent_menu_item_id"] != parent
                or item["hierarchy_status"] != status
                or item["parent_evidence"] != proof
            ):
                raise ValueError("Claim not supported by DOM ancestry")
            if node["parent_id"] != parent_key or node["hierarchy_status"] != status:
                raise ValueError("Conflicting hierarchy requires explicit review")
            if parent == sid:
                raise ValueError("Cyclic evidence")
            node["details_evidence"] = {
                "content_sha256": digest,
                "hierarchy_status": status,
                "parent_evidence": proof,
            }
            counts[proof] += 1
            local[status] += 1
        per_root.append(
            {"id": root["id"], "name": root["name"], "items": len(items), **dict(local)}
        )
    if seen != {n["id"] for n in result["nodes"] if n["kind"] != "department"}:
        raise ValueError("Incomplete menu coverage")
    # No page identifier can establish its namespace, even if its number matches
    # an existing Marketplace ID. Preserve it as an explicitly unverified record.
    pages = evidence.get("category_pages", [])
    for page in pages:
        if (
            page.get("status") != 200
            or page.get("automatic_marketplace_mapping") is not False
        ):
            raise ValueError("Unsuccessful category-page evidence")
        if any(i.get("namespace") != "unverified" for i in page.get("identifiers", [])):
            raise ValueError("Unproven identifier namespace")
    result["details_verification"] = {
        "source_key": "emag_webshop",
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content_sha256": digest,
        "observed_at": evidence["observed_at"],
        "source_url": evidence["requested_homepage"],
        "department_count": len(roots),
        "menu_item_count": len(seen),
        "verified_parent_connections": counts["explicit_group_class_to_heading_data_id"]
        + counts["department_containment"],
        "explicit_section_connections": counts[
            "explicit_group_class_to_heading_data_id"
        ],
        "direct_department_connections": counts["department_containment"],
        "needs_review": counts["unresolved_group"],
        "changed_parent_connections": 0,
        "new_marketplace_bindings": 0,
        "collection_errors": 0,
        "departments": per_root,
        "category_pages": pages,
        "network_menu_evidence_count": len(evidence.get("network_menu_evidence", [])),
    }
    return result
