"""CATEGORY-02C: reproducible 457-category status and discrepancy report.

Compares the historical CODEX 05 report (docs/reports/reviewed-parameter-profiles.json,
412 confirmed / 171 navigation) with the current backend list of bindable
categories (backend/reference_data/reviewed_parameter_bindings.json via
app.product_catalog.internal_categories, 457). Offline only: reads versioned
files of this repository, never a database (pinfo_db is not touched).

    PYTHONPATH=backend python scripts/report_category_457.py          # write
    PYTHONPATH=backend python scripts/report_category_457.py --check  # CI: verify

Output: docs/reports/category-457-status.json (the markdown summary in
docs/category-457-status.md is written by hand from this file).
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "docs/reports/reviewed-parameter-profiles.json"
BINDINGS = ROOT / "backend/reference_data/reviewed_parameter_bindings.json"
REVIEW = ROOT / "backend/reference_data/donor_review.json"
EXPORT = ROOT / "backend/tests/fixtures/emag_categories_export.tsv"
OUT = ROOT / "docs/reports/category-457-status.json"

# Pure documentation of how each newly bindable node relates to its donor. The
# classification is mechanical: a pending_review entry in donor_review.json wins,
# several donors mean "explicit profile choice", otherwise the node equals or is a
# narrower menu cut (type, build, platform, season) of the donor's product scope.
RISK_LABELS = {
    "pending_review": "Donor ellenőrzésre vár; automatikus donor és paraméterdúsítás tiltott.",
    "multi_profile": "Több külön profil; dúsítás csak kifejezett profilválasztás után.",
    "narrower_scope": "A menüpont termékköre azonos a donoréval vagy annak szűkítése (típus, kivitel, platform, évszak).",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    from app import product_catalog as pc
    from app.curated_taxonomy import apply_taxonomy
    from app.web_navigation import navigation

    old = json.loads(OLD.read_text(encoding="utf-8"))
    rules = {r["node_id"]: r for r in json.loads(BINDINGS.read_text(encoding="utf-8"))["rules"]}
    review = {(e["node_id"], e["emag_category_id"]): e
              for e in json.loads(REVIEW.read_text(encoding="utf-8"))["entries"]}
    export = {int(r["emag_category_id"]): r for r in
              csv.DictReader(EXPORT.open(encoding="utf-8-sig"), delimiter="\t")}

    base = apply_taxonomy(navigation())
    fixed = [n for n in base.nodes.values() if n.get("taxonomy_version")]
    current = {n["id"]: (n["name"], n["parent_id"]) for n in fixed}
    historical = {e["id"]: (e["name"], e["parent_id"]) for e in old["entries"]}
    roots = [n["id"] for n in fixed if n["parent_id"] is None]
    cats = pc.internal_categories()
    old_status = {e["id"]: e["status"] for e in old["entries"]}
    retired = [r["id"] for r in old["retired_nodes"]]

    def donor(node_id, d):
        row = export.get(d["emag_category_id"])
        entry = review.get((node_id, d["emag_category_id"]))
        return {
            "emag_category_id": d["emag_category_id"],
            "name": d["name"],
            "review_state": d["review_state"],
            "parameter_count": int(row["parameter_count"]) if row else None,
            "is_allowed": row["is_allowed"] == "1" if row else None,
            **({"review_reason": entry["reason_code"]} if entry else {}),
        }

    def risk(node_id, node):
        if any(d["review_state"] == "pending_review" for d in node["donors"]):
            return "pending_review"
        return "multi_profile" if len(node["donors"]) > 1 else "narrower_scope"

    added = []
    for key in sorted(set(cats) - {k for k, s in old_status.items() if s == "confirmed"},
                      key=lambda k: [e["id"] for e in old["entries"]].index(k)):
        node, rule = cats[key], rules[key]
        r = risk(key, node)
        added.append({
            "id": key,
            "path": node["path"],
            "donors": [donor(key, d) for d in node["donors"]],
            "old_status": old_status[key],
            "new_status": "bindable",
            "reviewed_input_state": rule["reviewed_input_state"],
            "rationale": rule["rationale"],
            "risk": r,
            "risk_note": RISK_LABELS[r],
            "has_children": any(p == key for _, p in current.values()),
        })
    removed = sorted(k for k, s in old_status.items() if s == "confirmed" and k not in cats)
    not_allowed = [
        {"node_id": k, "path": n["path"], "emag_category_id": d["emag_category_id"], "name": d["name"]}
        for k, n in cats.items() for d in n["donors"]
        if export.get(d["emag_category_id"], {}).get("is_allowed") == "0"
    ]
    return {
        "format": "adatdusito.category-457-status.v1",
        "issue": "CATEGORY-02C (#20)",
        "inputs_sha256": {
            "reviewed_parameter_profiles_json": sha256(OLD),
            "reviewed_parameter_bindings_json": sha256(BINDINGS),
            "donor_review_json": sha256(REVIEW),
            "emag_categories_export_tsv": sha256(EXPORT),
        },
        "tree": {
            "roots": len(roots),
            "root_ids": roots,
            "approved_nodes": len(current),
            "roots_unchanged": roots == old["roots"],
            "nodes_unchanged": current == historical,
            "retired_nodes": retired,
            "retired_classifiable": sorted(set(retired) & set(cats)),
        },
        "classification": {
            "historical_confirmed": old["bound_nodes"],
            "historical_navigation": old["structural_nodes"],
            "bindable_now": len(cats),
            "structural_now": len(current) - len(cats),
            "added": len(added),
            "removed": removed,
            "multi_profile_categories": sum(len(n["donors"]) > 1 for n in cats.values()),
            "parameter_profile_associations": sum(len(n["donors"]) for n in cats.values()),
            "pending_review_donors": sum(d["review_state"] == "pending_review"
                                         for n in cats.values() for d in n["donors"]),
            "bindable_with_children": sorted(k for k in cats if any(p == k for _, p in current.values())),
            "calibrated_methods": sorted(pc.CALIBRATED_PRECISION),
            "auto_threshold_default": pc.DEFAULT_AUTO_THRESHOLD,
            "auto_threshold_is_measured": bool(pc.CALIBRATED_PRECISION),
        },
        "added": added,
        "donors_not_allowed_in_export": not_allowed,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the committed report is stale")
    args = parser.parse_args(argv)
    text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("docs/reports/category-457-status.json is stale; regenerate it.", file=sys.stderr)
            return 1
        print("category-457-status.json is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
