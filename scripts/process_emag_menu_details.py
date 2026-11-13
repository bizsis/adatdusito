"""Validate detailed DOM evidence against the single shared navigation offline."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.menu_details_import import process_details_archive

parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
parser.add_argument("--navigation", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error("Output already exists; refusing to overwrite")
result = process_details_archive(
    args.archive, json.loads(args.navigation.read_text(encoding="utf-8"))
)
args.output.write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result["details_verification"], ensure_ascii=False, indent=2))
