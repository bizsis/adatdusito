"""Offline CODEX 05 binding report: approved taxonomy, never source-derived nodes."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.category_export import load_category_export
from app.fixed_navigation import resolve_fixed, binding_status
from app.web_navigation import navigation
from app.parameter_profiles import profile_info, reviewed_bindings

parser = argparse.ArgumentParser()
parser.add_argument("--export", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error("Output already exists")
tree = load_category_export(args.export)
nav = resolve_fixed(navigation(), tree)
entries = []
review_notes = {r["node_id"]: r for r in reviewed_bindings()["rules"]}
for key, node in nav.nodes.items():
    internal = nav.bindings.get(key)
    profiles = profile_info(nav, key)
    entries.append(
        dict(
            id=key,
            name=node["name"],
            parent_id=node["parent_id"],
            path=[nav.nodes[p]["name"] for p in nav.path(key)],
            status=binding_status(nav, key),
            source_emag_id=tree.rows[internal]["emag_category_id"]
            if internal is not None and len(profiles) == 1
            else None,
            parameter_profiles=profiles,
            reviewed_rationale=review_notes.get(key, {}).get("rationale"),
            parameter_count=sum(p["parameter_count"] for p in profiles),
            candidates=[
                dict(
                    emag_category_id=tree.rows[c]["emag_category_id"],
                    name=tree.rows[c]["name"],
                    parameter_count=tree.counts[c]["total"],
                )
                for c in nav.candidates.get(key, [])
                if internal is None
            ],
        )
    )
report = dict(
    scope="Approved fixed taxonomy; offline parameter bindings without operator overrides",
    input_sha256=hashlib.sha256(args.export.read_bytes()).hexdigest(),
    approved_nodes=len(nav.nodes),
    approved_edges=len(nav.nodes) - len(nav.roots),
    roots=nav.roots,
    maximum_depth=max(len(nav.path(k)) for k in nav.nodes),
    structural_nodes=nav.reference_coverage["structural_node_count"],
    bound_nodes=len(nav.bindings),
    unique_parameter_donors=len(
        {v for donors in nav.parameter_donors.values() for v in donors}
    ),
    parameter_profile_associations=sum(len(v) for v in nav.parameter_donors.values()),
    multi_profile_categories=sum(len(v) > 1 for v in nav.parameter_donors.values()),
    retired_nodes=nav.data.get("retired_nodes", []),
    reviewed_rule_count=len(review_notes),
    source_profile_warnings=nav.profile_warnings,
    nodes_with_parameters=nav.reference_coverage["categories_with_parameter_set"],
    ambiguous_bindings=nav.reference_coverage["ambiguous_parameter_binding_count"],
    unavailable_bindings=nav.reference_coverage["unavailable_parameter_binding_count"],
    source_category_records=len(tree.rows),
    source_parameter_links=sum(c["total"] for c in tree.counts.values()),
    allowed_values_not_in_export=True,
    source_activity_used_for_visibility=False,
    source_nodes_added_to_tree=0,
    entries=entries,
)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {k: v for k, v in report.items() if k != "entries"},
        ensure_ascii=False,
        indent=2,
    )
)
