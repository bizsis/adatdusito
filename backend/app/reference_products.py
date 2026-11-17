"""UNAS-REF-01: repeatable import of an UNAS XLSX export into the isolated reference store,
and the permission-gated lookup a later enrichment step may use.

* Only the application database is written (reference_* and unas_* tables); eMAG data in
  pinfo_db and catalog_* is never touched.
* Rows are matched on (source, Cikkszám); an unchanged row (same raw hash) is not rewritten,
  so repeating an import creates no duplicates.
* Every row runs in its own savepoint: one bad row is logged and skipped, the rest continue.
* Customer-group columns ("Ár: <group>", "Vásárló csoport ...") are never stored.
* Owner decision (RC-03): an imported reference export is an active knowledge source by
  default (usage_basis "owner_policy:2026-11-17"); an administrator can restrict or revoke
  it, and a later re-import never overrides that decision. Only shareable fields are
  returned by lookup(); nothing is marked verified automatically.

CLI (inside the backend container or venv, never against pinfo_db):
    python -m app.reference_products import <export.xlsx> [--store-key KEY] [--version V]
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import now
from app.unas_models import (
    ReferenceImportRun,
    ReferenceProduct,
    ReferenceProductAttribute,
    ReferenceProductIdentifier,
    ReferenceProductSource,
    UnasFieldDefinition,
    UnasParameterDefinition,
)
from app.unas_schema import excluded_from_reference, registry

BATCH = 500
MAX_ERRORS = 200
EXPORT_NAME = re.compile(r"^UnasShop_(?P<store>[A-Za-z0-9._-]+?)_(?P<version>\d{8}-\d{6})\.xlsx$")
EAN_PARAMETER = re.compile(r"^EAN( \d+)?$")
# Columns mapped to the normalized reference fields (the raw row keeps everything else).
COLUMNS = {
    "sku": "Cikkszám",
    "name": "Termék Név",
    "category": "Kategória",
    "short_description": "Rövid Leírás",
    "long_description": "Tulajdonságok",
    "image": "Kép link",
    "url": "Termék link",
    "record_id": "Azonosító",
}
BRAND_PARAMETER = "Márka"
USAGE_STATUSES = ("restricted", "internal_only", "approved_enrichment", "revoked")
DEFAULT_USAGE_BASIS = "owner_policy:2026-11-17"


def text(value):
    """Identifiers and names stay textual; numbers never lose leading zeros we can see."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value).strip()


def raw_value(value):
    """JSON-safe value as exported (numbers stay numbers, dates become ISO text)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def gtin_issues(code):
    if not code.isdigit():
        return ["non_digit"]
    if len(code) not in (8, 12, 13, 14):
        return ["invalid_length"]
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    return [] if (10 - total % 10) % 10 == digits[-1] else ["check_digit"]


def fold(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def export_identity(path, store_key=None, version=None):
    match = EXPORT_NAME.match(Path(path).name)
    store = store_key or (match["store"] if match else None)
    version = version or (match["version"] if match else None)
    if not store or not version:
        raise ValueError("Az áruház- és verzióazonosító nem állapítható meg; add meg kézzel.")
    return store, version, f"unas_export/{store}/{version}"


def read_rows(path):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = book.worksheets[0].iter_rows(values_only=True)
        headers = [text(h) for h in next(rows, [])]
        for line, row in enumerate(rows, 2):
            yield line, headers, row
    finally:
        book.close()


def profile(path):
    """Content-free column profile: fill counts, value types and maximum text length."""
    headers, total = [], 0
    filled, kinds, longest = {}, {}, {}
    for _, headers, row in read_rows(path):
        total += 1
        for i, value in enumerate(row):
            if value is None or text(value) == "":
                continue
            filled[i] = filled.get(i, 0) + 1
            kinds.setdefault(i, set()).add(type(value).__name__)
            longest[i] = max(longest.get(i, 0), len(text(value)))
    if not headers:
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True)
        headers = [text(h) for h in next(book.worksheets[0].iter_rows(values_only=True), [])]
        book.close()
    return headers, total, {
        i: {"rows": total, "filled": filled.get(i, 0), "types": sorted(kinds.get(i, [])),
            "max_length": longest.get(i, 0)}
        for i in range(len(headers))
    }


def register_schema(db, headers, schema_source, store_key, version, column_profile=None):
    """Store the header registry once per schema source; a repeat with the same headers is a
    no-op, different headers under the same source are refused."""
    existing = list(db.scalars(select(UnasFieldDefinition)
                               .where(UnasFieldDefinition.schema_source == schema_source)
                               .order_by(UnasFieldDefinition.position)))
    if existing:
        if [f.header for f in existing] != list(headers):
            raise ValueError("Ugyanazzal a sémaforrással eltérő fejléc érkezett.")
        return {f.position: f for f in existing}
    fields = {}
    for entry in registry(headers):
        if entry.get("duplicate_of") is not None:
            entry["note"] = f"Ismétlődő fejléc (első: {entry['duplicate_of']}. oszlop)."
        field = UnasFieldDefinition(
            schema_source=schema_source, source_version=version, store_key=store_key,
            position=entry["position"], header=entry["header"], field_key=entry["field_key"],
            scope=entry["scope"], field_group=entry["field_group"],
            data_type=entry["data_type"], requirement=entry["requirement"],
            requirement_source=entry["requirement_source"], importable=entry["importable"],
            default_value=None, validation=entry["validation"], note=entry["note"],
            profile=(column_profile or {}).get(entry["position"], {}),
            shareable=entry["shareable"],
        )
        db.add(field)
        db.flush()
        if entry["parameter"]:
            p = entry["parameter"]
            db.add(UnasParameterDefinition(
                field_id=field.id, schema_source=schema_source, name=p["name"],
                group_name=p["group_name"], param_type=p["param_type"], unit=p["unit"],
                unit_source=p["unit_source"], settings=p["settings"], header=p["header"],
            ))
        fields[entry["position"]] = field
    db.flush()
    return fields


def source_for(db, store_key, schema_source, excluded):
    key = f"unas_export:{store_key}"
    source = db.scalar(select(ReferenceProductSource).where(ReferenceProductSource.key == key))
    if source is None:
        source = ReferenceProductSource(
            key=key, name=f"UNAS-export – {store_key}", kind="unas_export",
            store_key=store_key, schema_source=schema_source,
            usage_status="approved_enrichment", usage_basis=DEFAULT_USAGE_BASIS,
            enrichment_enabled=True, contribution="automatic", excluded_columns=excluded,
        )
        db.add(source)
        db.flush()
    else:
        source.schema_source = schema_source
        source.excluded_columns = excluded
    return source


def build(headers, row, parameters):
    """Normalized fields, identifiers and attributes of one export row."""
    cells = {h: row[i] if i < len(row) else None for i, h in enumerate(headers)}
    raw = {h: raw_value(v) for h, v in cells.items()
           if not excluded_from_reference(h) and v is not None and text(v) != ""}
    sku = text(cells.get(COLUMNS["sku"]))
    identifiers, attributes = [], []
    for position, parameter in parameters.items():
        value = text(row[position]) if position < len(row) else ""
        if not value:
            continue
        if EAN_PARAMETER.match(parameter.name) and not parameter.group_name:
            issues = gtin_issues(value)
            identifiers.append({"kind": "gtin", "value": value[:120], "position": position,
                                "valid": not issues, "issues": issues,
                                "raw_header": parameter.header})
        else:
            attributes.append({"parameter_id": parameter.id, "name": parameter.name,
                               "group_name": parameter.group_name, "value_text": value,
                               "unit": parameter.unit})
    record_id = text(cells.get(COLUMNS["record_id"])) or None
    identifiers.append({"kind": "source_sku", "value": sku[:120], "position": 0, "valid": True,
                        "issues": [], "raw_header": COLUMNS["sku"]})
    if record_id:
        identifiers.append({"kind": "external_id", "value": record_id[:120], "position": 0,
                            "valid": True, "issues": [], "raw_header": COLUMNS["record_id"]})
    brand = next((a["value_text"] for a in attributes
                  if a["name"] == BRAND_PARAMETER and not a["group_name"]), None)
    image = text(cells.get(COLUMNS["image"]))
    return {
        "sku": sku,
        "record_id": record_id,
        "name": text(cells.get(COLUMNS["name"]))[:500] or None,
        "brand": brand[:255] if brand else None,
        "category_path": text(cells.get(COLUMNS["category"])) or None,
        "short_description": text(cells.get(COLUMNS["short_description"])) or None,
        "long_description": text(cells.get(COLUMNS["long_description"])) or None,
        "images": [image] if image else [],
        "source_url": text(cells.get(COLUMNS["url"]))[:1000] or None,
        "raw": raw,
        "raw_sha256": hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest(),
        "identifiers": identifiers,
        "attributes": attributes,
    }


def apply(db, source, run, item):
    product = db.scalar(select(ReferenceProduct).where(
        ReferenceProduct.source_id == source.id, ReferenceProduct.source_sku == item["sku"]))
    if product is not None and product.raw_sha256 == item["raw_sha256"]:
        product.last_import_id = run.id
        return "unchanged"
    created = product is None
    if created:
        product = ReferenceProduct(source_id=source.id, source_sku=item["sku"],
                                   origin=source.kind, first_import_id=run.id,
                                   imported_at=now())
        db.add(product)
    for key in ("record_id", "name", "brand", "category_path", "short_description",
                "long_description", "images", "source_url", "raw", "raw_sha256"):
        setattr(product, "source_record_id" if key == "record_id" else key, item[key])
    product.last_import_id = run.id
    product.updated_at = now()
    db.flush()
    if not created:
        for model in (ReferenceProductIdentifier, ReferenceProductAttribute):
            for old in db.scalars(select(model).where(model.product_id == product.id)):
                db.delete(old)
        db.flush()
    seen = set()
    for ident in item["identifiers"]:
        if (ident["kind"], ident["value"]) in seen:
            continue  # the same EAN in two columns is one identifier
        seen.add((ident["kind"], ident["value"]))
        db.add(ReferenceProductIdentifier(product_id=product.id, **ident))
    for attribute in item["attributes"]:
        db.add(ReferenceProductAttribute(product_id=product.id, **attribute))
    return "created" if created else "updated"


def import_export(db, path, store_key=None, version=None, limit=None):
    """Import one UNAS XLSX export; returns the finished ReferenceImportRun."""
    path = Path(path)
    store, version, schema_source = export_identity(path, store_key, version)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    headers, total, column_profile = profile(path)
    if not headers or "Cikkszám" not in headers:
        raise ValueError("Nem UNAS-termékexport: hiányzik a Cikkszám oszlop.")
    fields = register_schema(db, headers, schema_source, store, version, column_profile)
    excluded = [h for h in headers if excluded_from_reference(h)]
    source = source_for(db, store, schema_source, excluded)
    parameters = {
        position: db.scalar(select(UnasParameterDefinition)
                            .where(UnasParameterDefinition.field_id == field.id))
        for position, field in fields.items() if field.field_group == "parameter"
    }
    run = ReferenceImportRun(source_id=source.id, file_name=path.name[:255], file_sha256=digest,
                             state="running", counters={}, errors=[])
    db.add(run)
    db.commit()
    counters = {"rows": 0, "created": 0, "updated": 0, "unchanged": 0, "errors": 0,
                "empty": 0, "columns": len(headers), "excluded_columns": len(excluded)}
    errors = []
    pending = 0
    for line, _, row in read_rows(path):
        if limit is not None and counters["rows"] >= limit:
            break
        counters["rows"] += 1
        if all(v is None or text(v) == "" for v in row):
            counters["empty"] += 1
            continue
        try:
            with db.begin_nested():
                item = build(headers, row, parameters)
                if not item["sku"]:
                    raise ValueError("missing_sku")
                counters[apply(db, source, run, item)] += 1
        except Exception as exc:  # one row never stops the import
            counters["errors"] += 1
            if len(errors) < MAX_ERRORS:
                code = str(exc) if str(exc) in ("missing_sku",) else type(exc).__name__
                errors.append({"line": line, "code": code})
        pending += 1
        if pending >= BATCH:
            run.counters = dict(counters)
            db.commit()
            pending = 0
    run.counters = counters
    run.errors = errors
    run.state = "completed" if not counters["errors"] else "partial"
    run.finished_at = now()
    db.commit()
    return run


# --- lookup for a later enrichment step ---------------------------------------------------

TIME_DEPENDENT_HEADERS = re.compile(r"(Ár|Akció|Raktárkészlet|Létrehozás|Utolsó Módosítás)")


def usable_sources(db):
    return list(db.scalars(select(ReferenceProductSource.id).where(
        ReferenceProductSource.usage_status == "approved_enrichment",
        ReferenceProductSource.enrichment_enabled.is_(True),
    )))


def candidate(db, product, method, confidence):
    attributes = [
        {"name": a.name, "group": a.group_name, "value": a.value_text, "unit": a.unit}
        for a in db.scalars(
            select(ReferenceProductAttribute)
            .join(UnasParameterDefinition,
                  UnasParameterDefinition.id == ReferenceProductAttribute.parameter_id)
            .join(UnasFieldDefinition, UnasFieldDefinition.id == UnasParameterDefinition.field_id)
            .where(ReferenceProductAttribute.product_id == product.id,
                   UnasFieldDefinition.shareable.is_(True)))
    ]
    return {
        "reference_product_id": product.id,
        "source_id": product.source_id,
        "match": method,
        "confidence": confidence,
        "verification": product.verification,
        "observed_at": product.updated_at.isoformat() if product.updated_at else None,
        "name": product.name,
        "brand": product.brand,
        "category_path": product.category_path,
        "short_description": product.short_description,
        "long_description": product.long_description,
        "images": product.images,
        "attributes": attributes,
        # Prices, stock and timestamps of an old export are never offered as facts.
        "excluded": "time_dependent",
        "overwrites_supplier_data": False,
    }


def lookup(db, gtin=None, brand=None, name=None, source_ids=None):
    """Reference candidates for one product, best evidence first.

    Only sources with an explicit enrichment permission are searched (source_ids may narrow
    them further, never widen them). The result is advisory: nothing is written.
    """
    allowed = set(usable_sources(db))
    if source_ids is not None:
        allowed &= set(source_ids)
    if not allowed:
        return []
    results = []
    if gtin:
        code = text(gtin)
        rows = list(db.execute(
            select(ReferenceProduct, ReferenceProductIdentifier.valid)
            .join(ReferenceProductIdentifier,
                  ReferenceProductIdentifier.product_id == ReferenceProduct.id)
            .where(ReferenceProductIdentifier.kind == "gtin",
                   ReferenceProductIdentifier.value == code,
                   ReferenceProduct.source_id.in_(allowed))
        ))
        ambiguous = len({p.id for p, _ in rows}) > 1
        for product, valid in rows:
            confidence = (0.95 if valid else 0.6) - (0.25 if ambiguous else 0)
            results.append(candidate(db, product, "gtin", round(confidence, 2)))
    if brand and name and not results:
        target = (fold(brand), fold(name))
        for product in db.scalars(select(ReferenceProduct).where(
                ReferenceProduct.source_id.in_(allowed), ReferenceProduct.brand.is_not(None))):
            if (fold(product.brand), fold(product.name or "")) == target:
                results.append(candidate(db, product, "brand_name", 0.5))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("import", help="UNAS XLSX export importálása a referenciatárba")
    run.add_argument("path")
    run.add_argument("--store-key")
    run.add_argument("--version")
    args = parser.parse_args(argv)
    from app.db import engine

    with Session(engine()) as db:
        result = import_export(db, args.path, args.store_key, args.version)
        print(json.dumps({"run_id": result.id, "state": result.state,
                          "counters": result.counters, "errors": result.errors[:20]},
                         ensure_ascii=False))
    return 0 if result.state == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
