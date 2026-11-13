"""Bounded offline import for category-only TSV coverage checks, never DB writes."""

import csv
from app.category_tree import CategoryTree


def load_category_export(path):
    if path.stat().st_size > 5_000_000:
        raise ValueError("Category export size limit")
    rows, counts = [], {}
    ids, external = set(), set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != [
            "id",
            "emag_category_id",
            "name",
            "parent_id",
            "is_allowed",
            "parameter_count",
        ]:
            raise ValueError("Expected category-only TSV columns")
        for record in reader:
            if (
                len(rows) >= 100_000
                or None in record
                or any(v is None for v in record.values())
            ):
                raise ValueError("Malformed category export")

            def number(value):
                return None if value in ("NULL", "\\N", "") else int(value)

            row = {k: v if k == "name" else number(v) for k, v in record.items()}
            total = row.pop("parameter_count")
            if (
                row["id"] in ids
                or row["emag_category_id"] in external
                or not row["name"].strip()
                or row["is_allowed"] not in (0, 1, None)
                or total is None
                or total < 0
                or row["id"] is None
                or row["id"] <= 0
                or row["emag_category_id"] is None
                or row["emag_category_id"] <= 0
            ):
                raise ValueError("Invalid or duplicate category record")
            ids.add(row["id"])
            external.add(row["emag_category_id"])
            counts[row["id"]] = {
                "total": total,
                "mandatory": 0,
                "optional": 0,
                "unknown": total,
            }
            rows.append(row)
    return CategoryTree(rows, counts)
