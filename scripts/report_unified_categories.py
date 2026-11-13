"""Measure existing categories offline, without websites, credentials or DB writes."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.category_export import load_category_export
from app.unified_categories import build_unified
from app.web_navigation import navigation

parser = argparse.ArgumentParser()
parser.add_argument("--export", dest="source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error("Output already exists")
tree = load_category_export(args.source)
nav = build_unified(navigation(), tree)
placed = {v for k, v in nav.bindings.items() if nav.placement[k] == "verified_tree"}
report = {
    "input_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
    "rules_version": nav.reference_coverage["matching_rules_version"],
    "scope": "Offline supplied export, without existing operator overrides",
    "coverage": nav.reference_coverage,
    "televisions": {
        "reference_key": "emag_marketplace:79",
        "internal_id": nav.bindings.get("web-item-43-3730"),
        "parameter_count": tree.counts.get(
            nav.bindings.get("web-item-43-3730"), {}
        ).get("total"),
    },
    "ambiguous_menu_entries": [
        {
            "id": k,
            "name": nav.nodes[k]["name"],
            "candidates": [tree.light(c) for c in options],
        }
        for k, options in nav.candidates.items()
        if len(options) > 1 and k not in nav.bindings
    ],
    "unlocated_reference_categories": [
        tree.light(k)
        | {
            "original_parent_emag_id": tree.rows[k]["parent_id"],
            "parameter_count": tree.counts[k]["total"],
        }
        for k in tree.rows
        if k not in placed
    ],
    "automatic_matches": [
        {
            "node_id": k,
            "name": nav.nodes[k]["name"],
            "canonical_emag_id": tree.rows[v]["emag_category_id"],
            "method": nav.methods[k],
            "placement_status": nav.placement[k],
        }
        for k, v in nav.bindings.items()
        if nav.methods[k].startswith("automatic_")
    ],
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(report["coverage"], ensure_ascii=False, indent=2))
print("Televisions:", report["televisions"])
