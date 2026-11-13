"""Read-only, credential-free runtime coverage report for the operator."""

import json
from datetime import datetime, timezone
from app.db import reference_database
from app.reference import load_tree


def main():
    with reference_database() as conn:
        tree = load_tree(conn)
        report = tree.coverage()
        report["observed_at"] = datetime.now(timezone.utc).isoformat()
        report["unresolved_selectable_categories"] = [
            {
                "emag_category_id": tree.rows[id]["emag_category_id"],
                "name": tree.rows[id]["name"],
                "parent_emag_id": tree.rows[id]["parent_id"],
            }
            for id in sorted(tree.selectable)
            if tree.rows[id]["parent_id"] not in (None, 0) and tree.parents[id] is None
        ]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
