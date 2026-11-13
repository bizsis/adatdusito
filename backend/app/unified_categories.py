"""One common tree with source references, deterministic matching and no DB writes.

Only labels/category metadata and aggregated parameter counts are materialized.
Source IDs retain their namespaces; parameters/values always use original FKs.
"""

from collections import defaultdict
from copy import deepcopy
import unicodedata
import json
from pathlib import Path
from functools import lru_cache


def normalized(name):
    name = unicodedata.normalize("NFKC", name).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in name).split())


@lru_cache(maxsize=1)
def matching_rules():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "reference_data/category_matching_rules.json"
        ).read_text(encoding="utf-8")
    )


def reference_node_id(external_id):
    return f"ref-emag-{external_id}"


def build_unified(base, tree, latest=None, overrides=()):
    # Import at invocation to avoid a module cycle with the API/index class.
    from app.web_navigation import Navigation, BINDABLE_KINDS

    latest = latest or {}
    choices = {
        r.node_id: r
        for r in overrides
        if not r.source_snapshot or r.source_snapshot == base.data["archive_sha256"]
    }
    data = {**base.data, "nodes": deepcopy(base.data["nodes"])}
    byid = {n["id"]: n for n in data["nodes"]}
    bindings, methods, candidates = {}, {}, {}
    names = defaultdict(list)
    for key in sorted(tree.visible_all):
        names[normalized(tree.rows[key]["name"])].append(key)

    @lru_cache(maxsize=None)
    def ancestors(key):
        result, seen = [], set()
        key = tree.parents[key]
        while key is not None and key not in seen:
            seen.add(key)
            result.append(key)
            key = tree.parents[key]
        return result

    # External category ancestry is resolved by CategoryTree via emag_category_id.
    eligible = [n for n in data["nodes"] if n["kind"] in BINDABLE_KINDS]
    rules = matching_rules()
    aliases = {
        (r["root_id"], normalized(r["menu_name"])): normalized(r["reference_name"])
        for r in rules["label_aliases"]
    }
    alias_nodes = set()
    blocked = set()
    for node in eligible:
        key = node["id"]
        override = choices.get(key)
        record = latest.get(key)
        if override and (override.source_category_id or override.disable_automatic):
            if override.source_category_id:
                internal = (
                    tree.external.get(int(override.source_category_id))
                    if override.source_key == "emag_marketplace"
                    else None
                )
                if internal is not None:
                    bindings[key], methods[key] = internal, "administrator"
                else:
                    blocked.add(key)
            elif override.disable_automatic:
                blocked.add(key)
        elif record:
            if record.mapping_status == "confirmed":
                internal = tree.external.get(record.canonical_emag_id)
                if internal is not None:
                    bindings[key], methods[key] = internal, "administrator_legacy"
                else:
                    blocked.add(key)
            else:
                blocked.add(key)  # Preserve a prior explicit revocation/rejection.
        label = normalized(node["name"])
        candidates[key] = names.get(label, [])
        root = base.path(key)[0]
        alias = aliases.get((root, label))
        if not candidates[key] and alias:
            candidates[key] = names.get(alias, [])
            alias_nodes.add(key)

    # Resolve ancestors first; an exact unique name needs no operator approval.
    ordered = sorted(eligible, key=lambda n: len(base.path(n["id"])))
    for node in ordered:
        key = node["id"]
        if key in bindings or key in blocked:
            continue
        options = list(candidates[key])
        anchors = [bindings[k] for k in base.path(key)[:-1] if k in bindings]
        if len(options) > 1 and anchors:
            anchor = anchors[-1]
            options = [c for c in options if c == anchor or anchor in ancestors(c)]
        if len(options) > 1:
            context = {normalized(base.nodes[k]["name"]) for k in base.path(key)[:-1]}
            contextual = [
                c
                for c in options
                if any(
                    normalized(tree.rows[p]["name"]) in context for p in ancestors(c)
                )
            ]
            if contextual:
                options = contextual
        candidates[key] = options
        if len(options) == 1:
            bindings[key] = options[0]
            methods[key] = (
                "automatic_alias"
                if key in alias_nodes
                else "automatic_context"
                if len(names[normalized(node["name"])]) > 1
                else "automatic_exact"
            )

    # Preserve the existing webshop structure and apply only explicit app choices.
    for key, choice in choices.items():
        if key in byid and choice.override_parent:
            byid[key]["original_parent_id"] = byid[key]["parent_id"]
            byid[key]["parent_id"] = choice.parent_id
            byid[key]["hierarchy_status"] = "verified_assignment"
    interim = Navigation(data)
    anchors = defaultdict(list)
    for key, internal in bindings.items():
        if interim.placement[key] == "verified_tree":
            anchors[internal].append(key)
    represented = set(bindings.values())
    native = {
        internal: reference_node_id(row["emag_category_id"])
        for internal, row in tree.rows.items()
        if internal not in represented
    }
    scope_rules = {
        normalized(r["reference_name"]): r["parent_id"]
        for r in rules["source_scope_placements"]
    }
    root_names = defaultdict(list)
    for internal, row in tree.rows.items():
        if row["parent_id"] in (None, 0) and internal not in tree.deleted:
            root_names[normalized(row["name"])].append(internal)
    semantic_placements = set()
    for internal, key in native.items():
        row = tree.rows[internal]
        parent = tree.parents[internal]
        anchor_options = anchors.get(parent, [])
        parent_key = (
            anchor_options[0] if len(anchor_options) == 1 else native.get(parent)
        )
        choice = choices.get(key)
        status = "verified_reference"
        scope_parent = scope_rules.get(normalized(row["name"]))
        if (
            row["parent_id"] in (None, 0)
            and len(root_names[normalized(row["name"])]) == 1
            and scope_parent in base.roots
        ):
            parent_key = scope_parent
            semantic_placements.add(key)
        if internal in tree.deleted or internal in tree.cycle_nodes:
            status = "needs_review"
        if choice and choice.override_parent:
            parent_key, status = choice.parent_id, "verified_assignment"
        if internal not in tree.navigation:
            # Keep inactive source-only leaves out of normal navigation. Their
            # parameters remain available in the same browser's separate list.
            status = "needs_review"
        data["nodes"].append(
            {
                "id": key,
                "parent_id": parent_key,
                "root_id": None,
                "name": row["name"],
                "kind": "category",
                "url": None,
                "order": len(data["nodes"]),
                "hierarchy_status": status,
                "parent_evidence": "administrator"
                if choice and choice.override_parent
                else "semantic_source_scope"
                if key in semantic_placements
                else "existing_reference_parent",
                "source_department_id": "",
                "source_item_id": None,
                "canonical_emag_id": row["emag_category_id"],
                "source_key": "emag_marketplace",
                "original_parent_emag_id": row["parent_id"],
            }
        )
        bindings[key], methods[key] = internal, "source_reference"
    nav = Navigation(data)
    nav.bindings, nav.methods, nav.candidates, nav.reference = (
        bindings,
        methods,
        candidates,
        tree,
    )
    nav.blocked = blocked
    # Exact aliases use a single source category and parameter set, not a copy.
    placed = {
        internal
        for key, internal in bindings.items()
        if nav.placement[key] == "verified_tree"
    }
    ambiguous = {
        c
        for key, options in candidates.items()
        if key not in bindings and len(options) > 1
        for c in options
    }
    uncertain = {
        internal
        for key, internal in bindings.items()
        if nav.placement[key] != "verified_tree"
    }
    review = (ambiguous | uncertain) - placed
    # Native unlocated entries with no matching/structural issue are simply unplaced.
    review = {
        key
        for key in review
        if key in ambiguous or key in represented or key in tree.cycle_nodes
    }
    nav.reference_coverage = {
        "reference_total": len(tree.rows),
        "represented_reference_count": len(set(bindings.values())),
        "semantic_scope_rule_match_count": len(semantic_placements),
        "semantic_scope_placement_count": sum(
            nav.placement[key] == "verified_tree" for key in semantic_placements
        ),
        "selectable_reference_count": len(tree.selectable),
        "placed_selectable_reference_count": len(placed & tree.selectable),
        "matching_rules_version": rules["version"],
        "auto_mapped_reference_count": len(
            {
                bindings[k]
                for k, method in methods.items()
                if method.startswith("automatic_")
            }
        ),
        "automatically_arranged_reference_count": len(
            {
                internal
                for key, internal in bindings.items()
                if nav.placement[key] == "verified_tree"
                and methods[key] != "administrator"
                and key not in choices
                and methods[key] != "administrator_legacy"
            }
        ),
        "placed_reference_count": len(placed),
        "review_reference_count": len(review),
        "unplaced_reference_count": len(tree.rows) - len(placed) - len(review),
        "unlocated_reference_count": len(tree.rows) - len(placed),
        "ambiguous_menu_count": sum(
            len(v) > 1 and k not in bindings for k, v in candidates.items()
        ),
        "unmatched_menu_count": sum(
            not v and k not in bindings for k, v in candidates.items()
        ),
        "deleted_reference_count": len(tree.deleted),
        "inactive_source_only_entries": sum(
            internal not in tree.navigation and internal not in tree.deleted
            for internal in native
        ),
        "inactive_reference_count": sum(
            row["is_allowed"] != 1 for row in tree.rows.values()
        ),
        "categories_with_parameters": sum(
            bool(v["total"]) for v in tree.counts.values()
        ),
        "parameter_definition_total": sum(v["total"] for v in tree.counts.values()),
        "counts_are_runtime_observations": True,
        "parameter_values_copied": False,
    }
    return nav
