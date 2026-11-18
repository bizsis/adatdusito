"""IMPORT-MAP-01 (#58): webshop-engine based column mapping and the eMAG donor parameter diff.

Deterministic only: no AI, no credits, no network, no pinfo_db access (donor parameters come
from the owned catalog in the application database, as in CATEGORY-03A). No new tables:

* engine registry  -> store_engines.fields (default UNAS list when nothing was saved);
* saved mappings   -> import_profiles (versioned per supplier, config.engine_mapping);
* donor selection  -> import_runs.config.donor_selection.

Every source column stays visible and is kept (unmapped columns are source attributes, as
before); a parameter is only created when an operator approves it; source categories and
existing values are never rewritten. Contract: docs/design/IMPORT-MAP-01-API.md.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select

from app import unas_schema as us
from app.import_models import ImportProfile, ImportRow, ImportRun, StoreEngine, SupplierProduct
from app.import_parser import (
    FINANCIAL,
    IDENTIFIERS,
    blank,
    blank_row,
    decimal,
    norm,
    normalize,
    rows,
)
from app.models import now


class MappingError(Exception):
    """Error with machine-readable extras; the views keep message a Hungarian string."""

    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra

ENGINE_TYPES = {"integer": "number", "decimal": "number", "date": "date",
                "datetime": "date", "flag": "boolean"}
# Owner decision (#58): the system's own base requirements. UNAS' technical requirement is
# reported separately (unas_required) and never mixed in.
BASE_REQUIRED = ("Cikkszám", "Termék Név", "Kategória", "Nettó Ár", "Bruttó Ár", "Státusz")
INTERNAL = {"Cikkszám": "sku", "Termék Név": "name", "Kategória": "category",
            "Nettó Ár": "price", "Bruttó Ár": "price", "Rövid Leírás": "description",
            "Tulajdonságok": "description", "Kép link": "images", "Raktárkészlet": "stock",
            "Tömeg": "weight", "Egység": "unit", "Akciós Nettó Ár": "sale_price",
            "Akciós Bruttó Ár": "sale_price", "Akció Kezdet": "sale_start",
            "Akció Lejárat": "sale_end"}
SYNONYMS = {
    "Cikkszám": ["sku", "articlenr", "article", "itemnumber", "cikkszam", "cikk", "termekkod",
                 "productcode", "code"],
    "Termék Név": ["name", "productname", "megnevezes", "termeknev", "nev", "title",
                   "description1"],
    "Kategória": ["category", "kategoria", "group", "productgroup", "csoport"],
    "Nettó Ár": ["netprice", "nettoar", "priceNet", "netto"],
    "Bruttó Ár": ["grossprice", "bruttoar", "priceGross", "brutto"],
    "Státusz": ["status", "statusz", "active", "aktiv"],
    "Rövid Leírás": ["shortdescription", "rovidleiras", "short"],
    "Tulajdonságok": ["description", "leiras", "longdescription", "tulajdonsagok"],
    "Kép link": ["image", "images", "imageurl", "picture", "kep", "kepek", "photo"],
    "Raktárkészlet": ["stock", "quantity", "qty", "keszlet", "raktarkeszlet", "inventory"],
    "Tömeg": ["weight", "suly", "tomeg"],
    "Egység": ["unit", "uom", "egyseg", "mertekegyseg"],
}
# Common supplier header words -> Hungarian UNAS parameter name (a proposal only).
TRANSLATIONS = {
    "color": "Szín", "colour": "Szín", "farbe": "Szín", "szin": "Szín",
    "size": "Méret", "meret": "Méret", "grosse": "Méret",
    "material": "Anyag", "anyag": "Anyag",
    "width": "Szélesség", "szelesseg": "Szélesség",
    "height": "Magasság", "magassag": "Magasság",
    "length": "Hosszúság", "depth": "Mélység", "hosszusag": "Hosszúság",
    "brand": "Márka", "manufacturer": "Márka", "gyarto": "Márka", "marka": "Márka",
    "model": "Modell", "modell": "Modell",
    "power": "Teljesítmény", "teljesitmeny": "Teljesítmény",
    "voltage": "Feszültség", "capacity": "Kapacitás", "volume": "Űrtartalom",
    "warranty": "Garancia", "garancia": "Garancia",
}
# Positions 3..9 and 11..13 of a parameter header as seen in the UNAS export sample, per
# type (evidence: export_sample; meaning not documented, so copied verbatim).
PARAMETER_SETTINGS = {"text": "1|0|1|0|0|0", "num": "1|0|0|0|0|0", "enum": "0|0|0|0|0|0",
                      "enummore": "1|0|1|0|0|0", "link_text": "2|0|0|0|0|1"}
VAT_RATES = {Decimal("0"), Decimal("5"), Decimal("18"), Decimal("27")}
YES = {"1", "igen", "yes", "true", "van", "raktaron", "rendelheto", "instock", "available",
       "elerheto", "aktiv", "active"}
NO = {"0", "nem", "no", "false", "nincs", "nemrendelheto", "outofstock", "unavailable",
      "nemelerheto", "inaktiv", "inactive"}
FIELD_KEYS = {"key", "label", "type", "required", "default", "allowed", "validation",
              "internal_field", "header", "kind", "group", "synonyms", "unas_required",
              "parameter"}


def parameter_header(name, param_type="text", group_name="", unit=None):
    """The UNAS parameter export header (backend/app/unas_schema.py layout)."""
    if param_type not in us.PARAMETER_TYPES:
        raise ValueError("invalid_parameter_type")
    clean = (name or "").strip()
    if not clean or "|" in clean or len(clean) > 120 or "|" in (group_name or "") \
            or "|" in (unit or ""):
        raise ValueError("invalid_parameter")
    header = (f"{us.PARAMETER_PREFIX}{clean}|{group_name or ''}|{param_type}|"
              f"{PARAMETER_SETTINGS[param_type]}||{unit or ''}|0|1|1")
    parsed = us.parse_parameter(header)
    assert parsed["name"] == clean and parsed["param_type"] == param_type
    return header


# --- registry -------------------------------------------------------------------------------


def default_unas_fields():
    fields = []
    for header, (group, data_type) in us.STANDARD.items():
        fields.append({
            "key": us.field_key(header), "kind": "standard", "header": header,
            "label": header, "group": group, "type": ENGINE_TYPES.get(data_type, "text"),
            "required": header in BASE_REQUIRED, "unas_required": header in us.REQUIRED,
            "allowed": ["0", "1"] if header == "Státusz" else [],
            "synonyms": SYNONYMS.get(header, []), "internal_field": INTERNAL.get(header),
            "parameter": None})
    for name, internal, synonyms in (("EAN", "gtin", ["ean", "gtin", "barcode", "vonalkod",
                                                      "ean13"]),
                                     ("Márka", "brand", ["brand", "manufacturer", "gyarto",
                                                         "marka"])):
        kind = "enum" if name == "Márka" else "text"
        fields.append({
            "key": "param_" + us.field_key(name), "kind": "parameter",
            "header": parameter_header(name, kind), "label": name, "group": "parameter",
            "type": "text", "required": False, "unas_required": False, "allowed": [],
            "synonyms": synonyms, "internal_field": internal,
            "parameter": {"name": name, "group_name": "", "param_type": kind, "unit": None}})
    # An auxiliary input (UNAS stores no VAT rate): only used to compute a missing price.
    fields.append({
        "key": "afakulcs", "kind": "auxiliary", "header": "Áfakulcs (segédmező)",
        "label": "Áfakulcs (segédmező, nem exportált)", "group": "price", "type": "number",
        "required": False, "unas_required": False, "allowed": [],
        "synonyms": ["vat", "tax", "afa", "afakulcs", "vatrate"], "internal_field": "vat",
        "parameter": None})
    return fields


def complete(field):
    """Old-format registry entries (key/label/type/required) get the new optional keys."""
    out = {"kind": "standard", "header": field.get("label"), "group": None,
           "synonyms": [], "unas_required": False, "parameter": None, "allowed": [],
           "internal_field": None, "required": False, "type": "text", **field}
    if out["kind"] == "parameter" and out.get("parameter") and not field.get("header"):
        p = out["parameter"]
        out["header"] = parameter_header(p["name"], p.get("param_type", "text"),
                                         p.get("group_name", ""), p.get("unit"))
    return out


def engine_registry(db, key):
    engine = db.get(StoreEngine, key)
    if engine is None and key == "unas":
        # Seeded by migration 0006; the built-in list is served without a database write.
        return {"engine_key": key, "name": "UNAS", "version": 0, "source": "default",
                "fields": default_unas_fields()}
    if engine is None:
        raise HTTPException(404, "Ismeretlen webshopmotor.")
    if engine.fields:
        fields, source = [complete(f) for f in engine.fields], "stored"
    elif key == "unas":
        fields, source = default_unas_fields(), "default"
    else:
        fields, source = [], "stored"
    return {"engine_key": key, "name": engine.name,
            "version": engine.version if source == "stored" else 0, "source": source,
            "fields": fields}


def validate_registry_extras(fields):
    """Additional checks of the optional IMPORT-MAP-01 keys (PUT /engines/{key})."""
    headers = set()
    for f in fields:
        if set(f) - FIELD_KEYS:
            raise HTTPException(422, "Ismeretlen meződefiníció.")
        if f.get("kind", "standard") not in ("standard", "parameter", "auxiliary"):
            raise HTTPException(422, "Hibás mezőfajta.")
        synonyms = f.get("synonyms", [])
        if not isinstance(synonyms, list) or len(synonyms) > 30 or any(
                not isinstance(s, str) or not 1 <= len(s) <= 60 for s in synonyms):
            raise HTTPException(422, "Hibás szinonimalista.")
        if not isinstance(f.get("unas_required", False), bool):
            raise HTTPException(422, "Hibás UNAS-kötelezőség.")
        if f.get("kind") == "parameter":
            p = f.get("parameter")
            if not isinstance(p, dict) or set(p) - {"name", "group_name", "param_type",
                                                     "unit"}:
                raise HTTPException(422, "Hibás paraméterleírás.")
            try:
                built = parameter_header(p.get("name"), p.get("param_type", "text"),
                                         p.get("group_name", ""), p.get("unit"))
            except ValueError:
                raise HTTPException(422, "Hibás paraméterleírás.")
            f["header"] = f.get("header") or built
        header = f.get("header")
        if header is not None and (not isinstance(header, str) or not 1 <= len(header) <= 500):
            raise HTTPException(422, "Hibás fejléc.")
        if header in headers:
            raise HTTPException(422, "Ismételt fejléc.")
        headers.add(header)
    return fields


# --- saved mappings and approved parameters -------------------------------------------------


def engine_profiles(db, tenant_id, supplier_id, engine_key):
    return [p for p in db.scalars(select(ImportProfile).where(
        ImportProfile.tenant_id == tenant_id, ImportProfile.supplier_id == supplier_id)
        .order_by(ImportProfile.id.desc()))
        if (p.config.get("engine_mapping") or {}).get("engine_key") == engine_key]


def approved_parameters(db, tenant_id, engine_key):
    """Operator-approved parameters of this tenant and engine (all suppliers), newest first."""
    result = {}
    for p in db.scalars(select(ImportProfile).where(ImportProfile.tenant_id == tenant_id)
                        .order_by(ImportProfile.id.desc())):
        mapping = p.config.get("engine_mapping") or {}
        if mapping.get("engine_key") != engine_key:
            continue
        for param in mapping.get("parameters", []):
            result.setdefault(param["header"], {**param, "profile_id": p.id})
    return list(result.values())


def occurrences(headers):
    """Header identity robust to duplicates: (header, n-th occurrence)."""
    seen, out = {}, []
    for h in headers:
        h = "" if h is None else str(h)
        seen[h] = seen.get(h, 0) + 1
        out.append((h, seen[h]))
    return out


# --- suggestions ----------------------------------------------------------------------------


def suggest(header, samples, fields, approved):
    key = norm(header)
    if not key:
        return None
    for f in fields:
        if norm(f["header"]) == key or norm(f["label"]) == key:
            return target_of(f), 1.0, "exact_header"
    for f in fields:
        if key in {norm(s) for s in f.get("synonyms", [])}:
            return target_of(f), 0.95, "synonym"
    for p in approved:
        if norm(p["name"]) == key:
            return {"kind": "parameter", "header": p["header"]}, 0.9, "approved_parameter"
    name = TRANSLATIONS.get(key)
    if name:
        for f in fields:
            if f["kind"] == "parameter" and norm((f.get("parameter") or {}).get("name")) == \
                    norm(name):
                return target_of(f), 0.7, "translation"
        for p in approved:
            if norm(p["name"]) == norm(name):
                return {"kind": "parameter", "header": p["header"]}, 0.7, "translation"
        parameter = {"name": name, "group_name": "", "param_type": "text", "unit": None}
        return {"kind": "new_parameter", "header": parameter_header(name),
                "parameter": parameter}, 0.7, "translation"
    if samples and all(s.isdigit() and len(s) in (8, 12, 13, 14) for s in samples):
        ean = next((f for f in fields if f.get("internal_field") == "gtin"), None)
        if ean:
            return target_of(ean), 0.65, "content"
    return None


def target_of(f):
    if f["kind"] == "parameter":
        return {"kind": "parameter", "header": f["header"]}
    return {"kind": "field", "key": f["key"], "header": f["header"]}


def column_warnings(samples, target_internal):
    warnings = []
    if any(re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+", s.strip()) for s in samples):
        warnings.append("scientific_notation_identifier")
    if target_internal == "gtin" and any(
            "invalid_gtin" in normalize("gtin", s)[1] for s in samples):
        warnings.append("invalid_gtin_samples")
    if target_internal == "stock" and any(s.strip().startswith("-") for s in samples):
        warnings.append("negative_values")
    return warnings


def analysed(run):
    if run.state in ("uploaded", "analyzing") or not (run.analysis or {}).get("headers"):
        raise HTTPException(409, "Az elemzés még nem készült el.")
    return run.analysis


def scan(db, run, limit_rows=None):
    """Stream the data rows of the stored file (header and blank lines skipped)."""
    from app.import_engine import materialize

    with materialize(db, run) as path:
        for line, raw in rows(path, run.config):
            if line <= run.config["header_line"] or blank_row(raw):
                continue
            yield line, raw
            if limit_rows is not None:
                limit_rows -= 1
                if limit_rows <= 0:
                    return


def column_samples(db, run, width, limit_rows=2000):
    samples = [[] for _ in range(width)]
    filled, empty = [0] * width, [0] * width
    for _, raw in scan(db, run, limit_rows):
        for i in range(width):
            value = raw[i] if i < len(raw) else ""
            if blank(value):
                empty[i] += 1
            else:
                filled[i] += 1
                text = str(value)
                if len(samples[i]) < 5 and text not in samples[i]:
                    samples[i].append(text)
    return samples, filled, empty


def mapping_view(db, run, engine_key):
    analysis = analysed(run)
    registry = engine_registry(db, engine_key)
    fields = registry["fields"]
    by_header = {f["header"]: f for f in fields}
    approved = approved_parameters(db, run.tenant_id, engine_key)
    headers = [("" if h is None else str(h)) for h in analysis["headers"]]
    samples, filled, empty = column_samples(db, run, len(headers))
    profiles = engine_profiles(db, run.tenant_id, run.supplier_id, engine_key)
    saved = profiles[0] if profiles else None
    saved_targets = {}
    if saved:
        for c in saved.config["engine_mapping"]["columns"]:
            saved_targets[(c["header"], c.get("occurrence", 1))] = c["target"]
    idents = occurrences(headers)
    columns = []
    for i, header in enumerate(headers):
        s = suggest(header, samples[i], fields, approved)
        current = saved_targets.get(idents[i]) if saved else None
        target = current or (s[0] if s else None)
        internal = None
        if target and target["kind"] in ("field", "parameter"):
            f = by_header.get(target["header"])
            internal = f.get("internal_field") if f else None
        warnings = column_warnings(samples[i], internal)
        if idents[i][1] > 1 or headers.count(header) > 1:
            warnings.append("duplicate_header")
        columns.append({
            "index": i, "header": header, "samples": samples[i], "filled": filled[i],
            "empty": empty[i], "warnings": warnings,
            "suggestion": {"target": s[0], "confidence": s[1], "method": s[2]} if s else None,
            "current": current, "current_source": "saved_profile" if current else None})
    result = {
        "run_id": run.id, "engine_key": engine_key, "engine_version": registry["version"],
        "rows": {k: analysis.get(k) for k in ("physical_rows", "data_rows", "empty_rows")},
        "columns": columns, "approved_parameters": approved, "saved_profile": None}
    if saved:
        old = {(c["header"], c.get("occurrence", 1)) for c in
               saved.config["engine_mapping"]["columns"]}
        new = set(idents)
        result["saved_profile"] = {
            "id": saved.id, "version": saved.version,
            "missing_headers": sorted(h for h, _ in old - new),
            "new_headers": sorted(h for h, _ in new - old),
            "requires_review": old != new}
    return result


# --- validation -----------------------------------------------------------------------------


def availability(value):
    key = norm(value)
    if key in YES:
        return "1"
    if key in NO:
        return "0"
    return None


def amount(value):
    try:
        return Decimal(decimal(value))
    except (InvalidOperation, ValueError):
        return None


def vat_of(value):
    rate = amount(str(value).replace("%", "")) if value not in (None, "") else None
    return rate if rate in VAT_RATES else None


def validate(db, run, body):
    """A4: validation report; never writes."""
    analysis = analysed(run)
    headers = [("" if h is None else str(h)) for h in analysis["headers"]]
    registry = engine_registry(db, body["engine_key"])
    fields = registry["fields"]
    by_key = {f["key"]: f for f in fields}
    by_header = {f["header"]: f for f in fields}
    approved = {p["header"]: p for p in approved_parameters(db, run.tenant_id,
                                                             body["engine_key"])}
    errors, warnings = [], []
    new_params = {}
    for p in body.get("new_parameters", []):
        try:
            header = parameter_header(p.get("name"), p.get("param_type", "text"),
                                      p.get("group_name", ""), p.get("unit"))
        except ValueError:
            errors.append({"code": "invalid_parameter", "name": p.get("name")})
            continue
        if p.get("approved") is True:
            new_params[header] = {"name": p["name"].strip(), "header": header,
                                  "param_type": p.get("param_type", "text"),
                                  "group_name": p.get("group_name", ""),
                                  "unit": p.get("unit")}
    indexes = [c["index"] for c in body["columns"]]
    if sorted(indexes) != list(range(len(headers))):
        errors.append({"code": "missing_columns",
                       "columns": sorted(set(range(len(headers))) - set(indexes))})
    resolved = {}  # column -> (target_id, field-or-None, target dict)
    seen = {}
    for c in body["columns"]:
        target = c.get("target")
        if not target or not (0 <= c["index"] < len(headers)):
            continue
        if target.get("kind") == "field":
            f = by_key.get(target.get("key"))
            if f is None or f["kind"] == "parameter":
                errors.append({"code": "unknown_target", "columns": [c["index"]],
                               "target": target.get("key")})
                continue
            tid = f["key"]
        elif target.get("kind") == "parameter":
            header = target.get("header")
            f = by_header.get(header)
            if f is None and header not in approved and header not in new_params:
                errors.append({"code": "parameter_not_approved", "columns": [c["index"]],
                               "target": header})
                continue
            tid = header
        else:
            errors.append({"code": "unknown_target", "columns": [c["index"]],
                           "target": target.get("kind")})
            continue
        seen.setdefault(tid, []).append(c["index"])
        resolved[c["index"]] = (tid, f, target)
    for tid, cols in seen.items():
        if len(cols) > 1:
            errors.append({"code": "duplicate_target", "columns": cols, "target": tid})
    internal = {}
    for index, (tid, f, _) in sorted(resolved.items()):
        if f and f.get("internal_field") and len(seen[tid]) == 1:
            internal.setdefault(f["internal_field"], []).append((index, f))
    # Net and gross price both map to the internal "price": net wins, gross stays a source
    # attribute (kept, not lost).
    import_mapping, tax_basis = {}, None
    for field, entries in internal.items():
        if field == "price" and len(entries) > 1:
            entries = [e for e in entries if e[1]["header"] == "Nettó Ár"] or entries[:1]
        if len(entries) > 1:
            errors.append({"code": "duplicate_target", "columns": [e[0] for e in entries],
                           "target": field})
            continue
        index, f = entries[0]
        import_mapping[str(index)] = field
        if field == "price":
            tax_basis = "nettó" if f["header"] == "Nettó Ár" else "bruttó"
    mapped_internal = set(import_mapping.values())
    if not mapped_internal & (IDENTIFIERS | {"name"}):
        errors.append({"code": "identity_missing"})
    identity = body.get("identity_target")
    identity_column = None
    if identity:
        identity_column = next((i for i, (tid, _, _) in resolved.items() if tid == identity),
                               None)
        if identity_column is None:
            errors.append({"code": "identity_target_not_mapped", "target": identity})
    if (mapped_internal & FINANCIAL) and not body.get("financial_approved"):
        errors.append({"code": "financial_approval_required"})
    vat_rate = body.get("vat_rate")
    if vat_rate is not None and Decimal(str(vat_rate)) not in VAT_RATES:
        errors.append({"code": "invalid_vat_rate"})
        vat_rate = None
    column_of = {f["header"]: i for i, (_, f, _) in resolved.items() if f}
    required = row_checks(db, run, fields, column_of, identity_column, vat_rate, errors,
                          warnings)
    return {"valid": not errors, "errors": errors, "warnings": warnings, "required": required,
            "parameters_to_create": [{"name": p["name"], "header": h}
                                     for h, p in new_params.items()
                                     if h in {t for t, *_ in resolved.values()}
                                     and h not in approved and h not in by_header],
            "import_mapping": import_mapping,
            "approval_defaults": {"tax_basis": tax_basis} if tax_basis else {},
            "_resolved": resolved, "_new_params": new_params}


def row_checks(db, run, fields, column_of, identity_column, vat_rate, errors, warnings):
    """Required-field status over every data row; deterministic fallbacks only."""
    required = [f for f in fields if f.get("required")]
    missing = {f["header"]: 0 for f in required}
    fallback_ok = {f["header"]: 0 for f in required}
    status_words = 0
    stock_zero = invalid_vat = scientific = invalid_gtin = 0
    identities, conflicts = {}, []
    net_col, gross_col = column_of.get("Nettó Ár"), column_of.get("Bruttó Ár")
    vat_col = next((i for h, i in column_of.items()
                    if h.startswith("Áfakulcs")), None)
    stock_col, status_col = column_of.get("Raktárkészlet"), column_of.get("Státusz")
    gtin_cols = [i for h, i in column_of.items()
                 if any(f["header"] == h and f.get("internal_field") == "gtin" for f in fields)]

    def cell(raw, i):
        return raw[i] if i is not None and i < len(raw) else ""

    for _, raw in scan(db, run):
        rate = vat_of(cell(raw, vat_col)) if vat_col is not None else None
        if vat_col is not None and not blank(cell(raw, vat_col)) and rate is None:
            invalid_vat += 1
        rate = rate if rate is not None else (Decimal(str(vat_rate)) if vat_rate is not None
                                              else None)
        net = amount(cell(raw, net_col)) if net_col is not None else None
        gross = amount(cell(raw, gross_col)) if gross_col is not None else None
        for f in required:
            col = column_of.get(f["header"])
            value = cell(raw, col) if col is not None else ""
            if not blank(value):
                if f["header"] == "Státusz" and value.strip() not in ("0", "1"):
                    if availability(value) is None:
                        missing[f["header"]] += 1
                    else:
                        status_words += 1
                continue
            if f["header"] == "Státusz" and col is None:
                fallback_ok[f["header"]] += 1
            elif f["header"] == "Nettó Ár" and gross is not None and rate is not None:
                fallback_ok[f["header"]] += 1
            elif f["header"] == "Bruttó Ár" and net is not None and rate is not None:
                fallback_ok[f["header"]] += 1
            else:
                missing[f["header"]] += 1
        if stock_col is not None:
            stock = amount(cell(raw, stock_col))
            if stock is not None and stock == 0:
                stock_zero += 1
        for i in gtin_cols:
            issues = normalize("gtin", cell(raw, i))[1]
            scientific += "scientific_identifier_requires_review" in issues
            invalid_gtin += "invalid_gtin" in issues and \
                "scientific_identifier_requires_review" not in issues
        if identity_column is not None:
            key = cell(raw, identity_column).strip()
            if key:
                digest = hashlib.sha256("\x1f".join(map(str, raw)).encode()).hexdigest()
                previous = identities.setdefault(key, digest)
                if previous != digest and key not in conflicts:
                    conflicts.append(key)
    if conflicts:
        errors.append({"code": "identity_conflict", "count": len(conflicts),
                       "values": conflicts[:10]})
    for code, count in (("stock_zero_rows", stock_zero), ("invalid_vat_rows", invalid_vat),
                        ("scientific_identifier_rows", scientific),
                        ("invalid_gtin_rows", invalid_gtin)):
        if count:
            warnings.append({"code": code, "count": count})
    result = []
    rules = {"Státusz": "default_1", "Nettó Ár": "net_from_gross_vat",
             "Bruttó Ár": "gross_from_net_vat"}
    for f in required:
        header, col = f["header"], column_of.get(f["header"])
        if missing[header]:
            status, rule = ("partial" if col is not None else "missing"), None
        elif fallback_ok[header]:
            status, rule = "fallback", rules.get(header)
        elif header == "Státusz" and status_words:
            status, rule = "fallback", "from_availability"
        else:
            status, rule = "mapped", None
        result.append({"key": f["key"], "header": header, "status": status, "rule": rule,
                       "rows_missing": missing[header]})
    return result


def public_validation(report):
    return {k: v for k, v in report.items() if not k.startswith("_")}


def save_mapping(db, run, body, actor_id):
    """A5: a new versioned mapping profile; approved parameters recorded with the actor."""
    report = validate(db, run, body)
    if not report["valid"]:
        raise MappingError(422, "A megfeleltetés nem menthető; lásd a validációt.",
                           validation=public_validation(report))
    headers = [("" if h is None else str(h)) for h in run.analysis["headers"]]
    idents = occurrences(headers)
    registry = engine_registry(db, body["engine_key"])
    by_header = {f["header"]: f for f in registry["fields"]}
    used = {tid for tid, *_ in report["_resolved"].values()}
    at = now().isoformat()
    parameters = []
    known = {p["header"]: p for p in approved_parameters(db, run.tenant_id,
                                                         body["engine_key"])}
    for header in sorted(used):
        if header in report["_new_params"] and header not in known and \
                header not in by_header:
            p = report["_new_params"][header]
            parameters.append({**p, "approved_by": actor_id, "approved_at": at,
                               "origin": "operator_created"})
        elif header in known:
            parameters.append({k: v for k, v in known[header].items() if k != "profile_id"})
    columns = []
    for c in sorted(body["columns"], key=lambda c: c["index"]):
        target = report["_resolved"].get(c["index"], (None, None, None))[2]
        if target:
            target = {k: v for k, v in target.items() if k in ("kind", "key", "header")}
        columns.append({"column": c["index"], "header": idents[c["index"]][0],
                        "occurrence": idents[c["index"]][1], "target": target})
    previous = db.scalar(select(func.max(ImportProfile.version)).where(
        ImportProfile.tenant_id == run.tenant_id, ImportProfile.supplier_id == run.supplier_id,
        ImportProfile.name == body["name"])) or 0
    profile = ImportProfile(
        tenant_id=run.tenant_id, supplier_id=run.supplier_id, name=body["name"],
        version=previous + 1, approved_by=actor_id,
        config={
            # Keys read by the existing import engine when it matches a later upload.
            "analysis": run.analysis, "mapping": report["import_mapping"],
            "identity_field": next((report["import_mapping"].get(str(i))
                                    for i, (tid, _, _) in report["_resolved"].items()
                                    if tid == body.get("identity_target")), None),
            "automatic": False,
            "engine_mapping": {
                "engine_key": body["engine_key"], "engine_version": registry["version"],
                "columns": columns, "parameters": parameters,
                "identity_target": body.get("identity_target"),
                "vat_rate": body.get("vat_rate"),
                "financial_approved": bool(body.get("financial_approved")),
                "approval_defaults": report["approval_defaults"]}})
    db.add(profile)
    db.flush()
    created = [p for p in parameters if p.get("origin") == "operator_created"
               and p["approved_at"] == at]
    return profile, public_validation(report), created


# --- donor parameters (phase B) -------------------------------------------------------------


def run_products(db, run):
    ids = set(db.scalars(select(ImportRow.product_id).where(
        ImportRow.run_id == run.id, ImportRow.product_id.is_not(None))))
    if not ids:
        return []
    return list(db.scalars(select(SupplierProduct).where(SupplierProduct.id.in_(ids))))


def donor_categories(db, run):
    from app import product_catalog as pc
    from app.models import CatalogCategory
    from app.product_models import ProductClassification, ProductSourceCategory
    from app.catalog_constants import SOURCE

    products = run_products(db, run)
    by_source, without = {}, []
    for p in products:
        if p.source_category_id is None:
            without.append(p)
        else:
            by_source[p.source_category_id] = by_source.get(p.source_category_id, 0) + 1
    sources = []
    for sid, count in sorted(by_source.items()):
        c = db.get(ProductSourceCategory, sid)
        sources.append({"source_category_id": sid, "path": c.path_text if c else None,
                        "products": count})
    donors = {}
    ids = [p.id for p in products]
    for c in (db.scalars(select(ProductClassification).where(
            ProductClassification.product_id.in_(ids))) if ids else []):
        if c.donor_emag_category_id is None:
            continue
        d = donors.setdefault(c.donor_emag_category_id, {
            "emag_category_id": c.donor_emag_category_id, "products": 0,
            "parameter_profile_state": pc.parameter_profile_state(c.navigation_node_id,
                                                                  c.donor_emag_category_id)})
        d["products"] += 1
    for d in donors.values():
        d["name"] = db.scalar(select(CatalogCategory.name).where(
            CatalogCategory.key == f"{SOURCE}:category:{d['emag_category_id']}"))
    suggestions = {}
    for p in without:
        for key in pc.suggestions((p.data or {}).get("name") or ""):
            node = pc.internal_category(key)
            if node is None:
                continue
            s = suggestions.setdefault(key, {
                "navigation_node_id": key, "path": node["path"],
                "emag_category_ids": [d["emag_category_id"] for d in node["donors"]],
                "products": 0})
            s["products"] += 1
    return {"source_categories": sources, "products_without_source_category": len(without),
            "donors": sorted(donors.values(), key=lambda d: -d["products"]),
            "reference_suggestions": list(suggestions.values())}


def current_columns(db, run):
    """(header, target) of every column under the run's mapping (or the latest saved one)."""
    profile = None
    pid = (run.config or {}).get("engine_mapping_profile_id")
    if pid:
        profile = db.get(ImportProfile, pid)
    if profile is None:
        candidates = [p for p in db.scalars(select(ImportProfile).where(
            ImportProfile.tenant_id == run.tenant_id,
            ImportProfile.supplier_id == run.supplier_id).order_by(ImportProfile.id.desc()))
            if p.config.get("engine_mapping")]
        profile = candidates[0] if candidates else None
    headers = [("" if h is None else str(h)) for h in (run.analysis or {}).get("headers", [])]
    idents = occurrences(headers)
    saved = {}
    if profile:
        for c in profile.config["engine_mapping"]["columns"]:
            saved[(c["header"], c.get("occurrence", 1))] = c["target"]
    return profile, [(i, headers[i], saved.get(idents[i])) for i in range(len(headers))]


def target_label(target):
    if not target:
        return None
    header = target.get("header") or ""
    parsed = us.parse_parameter(header)
    return parsed["name"] if parsed else header


def donor_parameters(db, run, emag_category_id):
    from app import product_catalog as pc
    from app.models import CatalogCategory
    from app.catalog_constants import SOURCE
    from app.product_parameters import active_catalog, aliases_for, label_key

    catalog = active_catalog(db)
    if db.scalar(select(CatalogCategory.id).where(
            CatalogCategory.key == f"{SOURCE}:category:{emag_category_id}")) is None:
        raise HTTPException(404, "Ismeretlen donorkategória.")
    params = catalog.parameters(emag_category_id)
    _, columns = current_columns(db, run)
    aliases = aliases_for(db, run.tenant_id, emag_category_id)
    alias_params = {a.emag_parameter_id: a for a in aliases.values()}
    covered_by_label = {}
    for index, header, target in columns:
        if target:
            covered_by_label.setdefault(label_key(pc.split_header(target_label(target))[0]),
                                        (index, header, "parameter_label"))
        else:
            covered_by_label.setdefault(label_key(pc.split_header(header)[0]),
                                        (index, header, "source_header"))
    column_labels = {label_key(pc.split_header(h)[0]): (i, h) for i, h, _ in columns}
    selection = ((run.config or {}).get("donor_selection") or {}).get(str(emag_category_id), {})
    selected = set(selection.get("parameter_ids", []))
    out = []
    for p in params:
        hit = covered_by_label.get(p["label_key"])
        alias = alias_params.get(p["emag_parameter_id"])
        covered_by = None
        if hit:
            covered_by = {"column": hit[0], "header": hit[1], "via": hit[2]}
        elif alias and alias.label_key in column_labels:
            i, h = column_labels[alias.label_key]
            covered_by = {"column": i, "header": h, "via": "alias"}
        status = "covered" if covered_by else "missing"
        out.append({"emag_parameter_id": p["emag_parameter_id"], "name": p["name"],
                    "label": p["label"], "unit": p["target_unit"], "mandatory": p["mandatory"],
                    "is_filter": p["is_filter"], "display_order": p["display_order"],
                    "status": status, "covered_by": covered_by,
                    "selected": status == "missing" and p["emag_parameter_id"] in selected})
    previous = None
    for other in db.scalars(select(ImportRun).where(
            ImportRun.tenant_id == run.tenant_id, ImportRun.supplier_id == run.supplier_id,
            ImportRun.id != run.id).order_by(ImportRun.id.desc()).limit(50)):
        sel = ((other.config or {}).get("donor_selection") or {}).get(str(emag_category_id))
        if sel:
            previous = sel["parameter_ids"]
            break
    return {"emag_category_id": emag_category_id, "catalog_version": catalog.version,
            "total": len(out), "missing": sum(p["status"] == "missing" for p in out),
            "covered": sum(p["status"] == "covered" for p in out),
            "selected": sum(p["selected"] for p in out), "parameters": out,
            "previous_selection": previous}


def set_selection(db, run, emag_category_id, mode, ids, actor_id):
    view = donor_parameters(db, run, emag_category_id)
    missing = {p["emag_parameter_id"] for p in view["parameters"] if p["status"] == "missing"}
    if mode == "all":
        chosen = sorted(missing)
    elif mode == "none":
        chosen = []
    else:
        bad = sorted(set(ids) - missing)
        if bad:
            raise MappingError(422, "Csak hiányzó paraméter jelölhető ki.",
                               reason="not_selectable", emag_parameter_ids=bad)
        chosen = sorted(set(ids))
    config = dict(run.config or {})
    selection = dict(config.get("donor_selection") or {})
    selection[str(emag_category_id)] = {"parameter_ids": chosen, "selected_by": actor_id,
                                        "selected_at": now().isoformat()}
    config["donor_selection"] = selection
    run.config = config  # reassigned: JSON columns do not track in-place changes
    db.flush()
    return chosen


def prepared_fields(db, run):
    profile, columns = current_columns(db, run)
    fields = [{"source": "column", "column": i, "header": h,
               "target": t.get("header") if t else None}
              for i, h, t in columns if t]
    donors = []
    for category, sel in ((run.config or {}).get("donor_selection") or {}).items():
        names = {}
        if sel["parameter_ids"]:
            try:
                view = donor_parameters(db, run, int(category))
                names = {p["emag_parameter_id"]: p["name"] for p in view["parameters"]}
            except HTTPException:
                names = {}
        for pid in sel["parameter_ids"]:
            donors.append({"emag_category_id": int(category), "emag_parameter_id": pid,
                           "name": names.get(pid), "state": "selected_empty"})
    return {"engine_key": (profile.config["engine_mapping"]["engine_key"] if profile else None),
            "profile_id": profile.id if profile else None, "fields": fields,
            "donor_parameters": donors}

