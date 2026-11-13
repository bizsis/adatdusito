"""Validate and recover menu hierarchy offline; no network or database writes."""

import argparse
import json
from pathlib import Path
import sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.menu_import import process_archive

parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
result = process_archive(args.archive)
if args.output.exists():
    raise SystemExit("Output already exists; refusing to overwrite")
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            "roots": sum(n["kind"] == "department" for n in result["nodes"]),
            "manifest_links": result["manifest_link_count"],
            "kinds": dict(Counter(n["kind"] for n in result["nodes"])),
            "hierarchy_needs_review": len(result["issues"]),
            "html_url_disagreements": result["html_url_disagreements"],
            "marketplace_mappings": 0,
        },
        ensure_ascii=False,
    )
)
