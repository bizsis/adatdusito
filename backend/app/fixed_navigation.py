"""CODEX 05: the approved menu is the taxonomy; source rows are parameter donors."""

from types import SimpleNamespace
from app.curated_taxonomy import apply_taxonomy
from app.unified_categories import build_unified


def resolve_fixed(base, tree, latest=None, overrides=()):
    from app.web_navigation import Navigation

    base = apply_taxonomy(base)
    fixed = {k: n for k, n in base.nodes.items() if n.get("taxonomy_version")}
    # Preserve parameter decisions, never apply an old placement override to the
    # approved taxonomy. No persistent source/category record is changed here.
    binding_choices = [
        SimpleNamespace(
            **{
                "node_id": r.node_id,
                "source_key": r.source_key,
                "source_category_id": r.source_category_id,
                "source_snapshot": r.source_snapshot,
                "disable_automatic": r.disable_automatic,
                "override_parent": False,
                "parent_id": None,
            }
        )
        for r in overrides
        if r.node_id in fixed
    ]
    matched = build_unified(base, tree, latest, binding_choices)
    nav = Navigation(
        {
            **base.data,
            "nodes": list(fixed.values()),
            "retired_nodes": base.curated_spec.get("retired_nodes", []),
        }
    )
    leaves = {
        k
        for k, n in fixed.items()
        if n["kind"] == "category" and not n.get("structural_only")
    }
    nav.bindings = {k: v for k, v in matched.bindings.items() if k in leaves}
    nav.methods = {k: v for k, v in matched.methods.items() if k in leaves}
    nav.candidates = {k: v for k, v in matched.candidates.items() if k in leaves}
    nav.blocked, nav.reference = matched.blocked, tree
    retired = {n["id"] for n in base.curated_spec.get("retired_nodes", [])}
    nav.related = lambda key: [
        n for n in base.related(key) if n["id"] not in fixed and n["id"] not in retired
    ]
    from app.parameter_profiles import resolve_profiles

    resolve_profiles(nav, tree, matched)
    nav.reference_coverage = {
        **matched.reference_coverage,
        "fixed_category_count": len(fixed),
        "structural_node_count": len(fixed) - len(leaves),
        "parameter_linked_category_count": len(nav.bindings),
        "categories_with_parameter_set": sum(
            any(tree.counts.get(v, {}).get("total", 0) > 0 for v in donors)
            for donors in nav.parameter_donors.values()
        ),
        "parameter_profile_count": sum(len(v) for v in nav.parameter_donors.values()),
        "multi_profile_category_count": sum(
            len(v) > 1 for v in nav.parameter_donors.values()
        ),
        "ambiguous_parameter_binding_count": sum(
            k not in nav.bindings and len(nav.candidates.get(k, [])) > 1 for k in leaves
        ),
        "unavailable_parameter_binding_count": sum(
            k not in nav.bindings and len(nav.candidates.get(k, [])) <= 1
            for k in leaves
        ),
    }
    return nav


def binding_status(nav, key):
    node = nav.nodes[key]
    if node["kind"] != "category" or node.get("structural_only"):
        return "navigation"
    if key in nav.bindings:
        return "confirmed"
    if key in nav.blocked:
        return "rejected"
    return "pending" if len(nav.candidates.get(key, [])) > 1 else "unavailable"


def binding_scope_keys(nav, scope):
    """Use the same product-only partition as the live dashboard counters."""
    if scope not in {"unavailable", "unclassified"}:
        return list(nav.nodes)
    return [
        key
        for key, node in nav.nodes.items()
        if node["kind"] == "category"
        and not node.get("structural_only")
        and key not in nav.bindings
        and ((len(nav.candidates.get(key, [])) > 1) == (scope == "unclassified"))
    ]
