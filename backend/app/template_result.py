"""TEMPLATE-RESULT-01: the UNAS product data file built from a saved template version.
Contract: docs/design/TEMPLATE-RESULT-01-API.md.

Read only: the result is recomputed from (template version, source file) on every request;
no product, run or template is written, no import is started, no AI or eMAG is involved.
Only documented UNAS columns are written; nothing is invented (identifiers keep their text,
lost digits stay lost, missing required data is flagged), no currency conversion.
"""

import csv
import io
import re
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException

from app import template_prep as tp
from app import unas_schema as us
from app.import_mapping import availability, occurrences
from app.import_models import ImportRun
from app.import_parser import blank, blank_row, decimal, rows

VAT_RATES = {Decimal("0"), Decimal("5"), Decimal("18"), Decimal("27")}
ORDER = {t["key"]: i for i, t in enumerate(tp.TARGETS)}
NUMBER_TARGETS = {"raktarkeszlet", "masodlagos_mennyiseg", "min_rendelheto", "lepeskoz",
                  "tomeg"}
PRICE_PAIRS = {"netto_ar": ("brutto_ar", "net"), "brutto_ar": ("netto_ar", "gross"),
               "netto_akcios_ar": ("brutto_akcios_ar", "net"),
               "brutto_akcios_ar": ("netto_akcios_ar", "gross")}
DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y.%m.%d",
                "%Y.%m.%d.", "%d.%m.%Y", "%d/%m/%Y")
SCIENTIFIC = re.compile(r"^\+?(\d+)(?:[.,](\d+))?[eE]\+?(\d+)$")
MAX_LIMIT = 200
# UNAS "Kép link": several image URLs in one cell, "|" separated, main image first
# (UNAS help "Termék adatbázis" excerpt + the real UNAS export, where a product carries
# "…/shop_pic/x.jpg|…/shop_altpic/x_altpic_1.jpg|…/shop_altpic/x_altpic_2.jpg").
IMAGE_SEPARATOR = "|"
UNAS_IMAGE_LIMIT = 10  # help excerpt; exceeding it is reported, nothing is dropped


# --- value rules -----------------------------------------------------------------------------


def gtin_valid(digits):
    if len(digits) not in (8, 12, 13, 14) or not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def identifier(raw, cell=None, gtin=True):
    """(text, [warning codes]). Never invents a digit."""
    text = str(raw or "").strip()
    if not text:
        return "", []
    if getattr(cell, "uncertain_identifier", False):
        return "", ["ean_unrecoverable"]  # Excel float beyond its precision
    whole = re.fullmatch(r"(\d+)(?:[.,]0+)?", text)
    if whole:
        digits = whole.group(1)
        if gtin and not gtin_valid(digits):
            return digits, ["invalid_gtin"]
        return digits, []
    sci = SCIENTIFIC.fullmatch(text)
    if sci:
        head, frac, exp = sci.group(1), sci.group(2) or "", int(sci.group(3))
        # Exact only when the mantissa carries every digit of the integer value.
        if len(frac) == exp:
            digits = (head + frac).lstrip("0") or "0"
            if not gtin or gtin_valid(digits):
                return digits, ["ean_reconstructed"]
        return "", ["ean_unrecoverable"]
    return text, (["invalid_gtin"] if gtin else [])


def number(raw):
    try:
        return Decimal(decimal(raw))
    except (InvalidOperation, ValueError):
        return None


def text_of(value):
    return format(value.normalize(), "f") if value is not None else ""


def date_of(raw):
    text = str(raw).strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).strftime("%Y.%m.%d")
        except ValueError:
            pass
    return None


def vat_of(raw):
    text = str(raw).strip().rstrip("%").strip()
    rate = number(text) if text else None
    return rate if rate in VAT_RATES else None


# --- plan ------------------------------------------------------------------------------------


def documented(header):
    return bool(header) and (us.parse_parameter(header) is not None or
                             us.classify(header)["scope"] == "standard")


def plan(template, headers):
    """Output columns of a template version applied to a file with these headers."""
    tpl = template.config["template"]
    position = {ident: i for i, ident in enumerate(occurrences(headers))}
    sources, missing = {}, []
    for c in tpl["columns"]:
        if c["state"] != "mapped" or not c.get("target"):
            continue
        index = position.get((c["header"], c.get("occurrence", 1)))
        if index is None:
            missing.append(c["header"])
            continue
        t = c["target"]
        sources.setdefault(tp.slot(t), []).append((index, t, c.get("unas_header")))
    columns, excluded = [], []
    vat_source = None
    images = sorted((target.get("order") or 1, index) for (key, *_), entries in sources.items()
                    if key == "kep" for index, target, _ in entries)
    if images:
        # Every image column, in the operator's order, into the one UNAS image cell.
        columns.append({"header": "Kép link", "target": {"key": "kep"},
                        "source_columns": [i for _, i in images],
                        "image_orders": [o for o, _ in images],
                        "_rank": (0, ORDER["kep"], 0, 0, images[0][1])})
    for slot_key, entries in sources.items():
        index, target, head = entries[0]
        key = target["key"]
        if key == "afa":
            vat_source = index
            continue
        if key == "kep":
            continue
        if not documented(head):
            excluded.append({"header": head, "source_columns": [index],
                             "code": "undocumented_header_excluded"})
            continue
        rank = (1, index) if key == "parameter" else (
            0, ORDER[key], target.get("instance") or 0, target.get("order") or 0, index)
        columns.append({"header": head, "target": target, "source_columns": [index],
                        "_rank": rank})
    keys = {c["target"]["key"] for c in columns}
    for key, (other, _) in PRICE_PAIRS.items():
        if key not in keys and other in keys:
            columns.append({"header": tp.BY_KEY[key]["unas_header"], "target": {"key": key},
                            "source_columns": [], "computed": True,
                            "_rank": (0, ORDER[key], 0, 0, -1)})
    if "statusz" not in keys:
        columns.append({"header": "Státusz", "target": {"key": "statusz"},
                        "source_columns": [], "default": tpl["defaults"]["statusz"],
                        "_rank": (0, ORDER["statusz"], 0, 0, -1)})
    columns.sort(key=lambda c: c["_rank"])
    return {"columns": columns, "excluded": excluded, "missing": sorted(set(missing)),
            "vat_source": vat_source,
            "defaults": tpl["defaults"], "currency": tpl["currency"]}


# --- rows ------------------------------------------------------------------------------------


def image_links(col, cell):
    """All images of a row in order: source columns by their image order; a cell that
    already holds several "|"-separated links keeps them in place. Empty cells leave no
    gap (UNAS has no empty slot); an empty order before a filled one is reported."""
    links, empty, last_filled = [], [], None
    for order, index in zip(col["image_orders"], col["source_columns"]):
        value = cell(index)
        parts = [] if blank(value) else [
            p.strip() for p in re.split(r"[|\r\n]+", str(value)) if p.strip()]
        if parts:
            links += parts
            last_filled = order
        else:
            empty.append(order)
    codes = []
    gaps = [o for o in empty if last_filled is not None and o < last_filled]
    if gaps:
        codes.append({"code": "image_missing_in_sequence", "orders": gaps})
    if len(links) > UNAS_IMAGE_LIMIT:
        codes.append({"code": "images_over_unas_limit", "count": len(links),
                      "limit": UNAS_IMAGE_LIMIT})
    return IMAGE_SEPARATOR.join(links), codes


def computed_price(known, rate, side):
    factor = Decimal("1") + rate / Decimal("100")
    if side == "gross":  # the known value is net -> gross, 2 decimals
        return (known * factor).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return (known / factor).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def convert(p, raw, cells, duplicates, currency_columns):
    errors, warnings = [], []

    def cell(i):
        return cells[i] if i is not None and i < len(cells) else ""

    rate = Decimal(p["defaults"]["afa"])
    if p["vat_source"] is not None and not blank(cell(p["vat_source"])):
        rate = vat_of(cell(p["vat_source"]))
        if rate is None:
            warnings.append({"code": "invalid_vat"})
    values, prices = {}, {}
    for col in p["columns"]:
        key = col["target"]["key"]
        if col.get("computed") or (col.get("default") is not None and not col["source_columns"]):
            continue
        source = cell(col["source_columns"][0])
        text = "" if blank(source) else str(source).strip()
        if key == "kep":
            text, codes = image_links(col, cell)
            warnings += codes
            values[id(col)] = text
            continue
        if key == "ean":
            text, codes = identifier(source, source)
            warnings += [{"code": c} for c in codes]
        elif key == "gyartoi_cikkszam":
            text, codes = identifier(source, source, gtin=False)
            warnings += [{"code": c} for c in codes if c != "ean_reconstructed"]
        elif key in PRICE_PAIRS:
            amount = number(text) if text else None
            if text and amount is None:
                warnings.append({"code": "invalid_number", "target": key})
            prices[key] = amount
            text = text_of(amount)
        elif key in NUMBER_TARGETS:
            amount = number(text) if text else None
            if text and amount is None:
                warnings.append({"code": "invalid_number", "target": key})
            if key == "raktarkeszlet" and amount is not None and amount < 0:
                warnings.append({"code": "negative_stock"})
            text = text_of(amount)
        elif key in ("akcio_kezdete", "akcio_vege") and text:
            parsed = date_of(text)
            if parsed is None:
                warnings.append({"code": "invalid_date", "target": key})
            text = parsed or ""
        elif key == "statusz":
            if not text:
                text = p["defaults"]["statusz"]
            elif text not in ("0", "1"):
                word = availability(text)
                if word is None:
                    warnings.append({"code": "invalid_status"})
                text = word or ""
        values[id(col)] = text
    for col in p["columns"]:
        key = col["target"]["key"]
        if col.get("default") is not None and not col["source_columns"]:
            values[id(col)] = col["default"]
        if col.get("computed"):
            other, _ = PRICE_PAIRS[key]
            known = prices.get(other)
            side = "gross" if key.startswith("brutto") else "net"
            values[id(col)] = text_of(computed_price(known, rate, side)) \
                if known is not None and rate is not None else ""
    # Both sides given: they must agree with the row's VAT (nothing is changed).
    for net, gross in (("netto_ar", "brutto_ar"), ("netto_akcios_ar", "brutto_akcios_ar")):
        if prices.get(net) is not None and prices.get(gross) is not None and rate is not None:
            expected = computed_price(prices[net], rate, "gross")
            if abs(expected - prices[gross]) > Decimal("0.01"):
                warnings.append({"code": "price_vat_mismatch", "target": gross})
    by_key = {col["target"]["key"]: values.get(id(col), "") for col in p["columns"]}
    if not by_key.get("cikkszam"):
        errors.append({"code": "missing_sku"})
    elif duplicates.get(by_key["cikkszam"], 0) > 1:
        warnings.append({"code": "duplicate_sku"})
    for key in ("termek_megnevezes", "kategoria"):
        if not by_key.get(key):
            warnings.append({"code": "missing_required", "target": key})
    if not by_key.get("netto_ar") and not by_key.get("brutto_ar"):
        warnings.append({"code": "missing_price"})
    for i in currency_columns:
        code = str(cell(i)).strip().upper()
        if code and code != p["currency"]:
            warnings.append({"code": "currency_mismatch", "value": code})
    status = "error" if errors else ("warning" if warnings else "ok")
    return {"values": [values.get(id(col), "") for col in p["columns"]], "status": status,
            "errors": errors, "warnings": warnings}


# --- driver ----------------------------------------------------------------------------------


def resolve(db, tenant_id, template_id, run_id=None):
    template = tp.get_template(db, tenant_id, template_id)
    run_id = run_id or template.config["template"]["source"]["run_id"]
    run = db.get(ImportRun, run_id)
    if run is None or run.tenant_id != tenant_id or run.supplier_id != template.supplier_id:
        raise HTTPException(404, "Az import nem található ennél a beszállítónál.")
    if not (run.analysis or {}).get("headers"):
        raise HTTPException(409, "Az elemzés még nem készült el.")
    return template, run


def data_rows(db, run):
    from app.import_engine import materialize

    try:
        with materialize(db, run) as path:
            for line, raw in rows(path, run.config):
                if line <= run.config["header_line"] or blank_row(raw):
                    continue
                yield line, raw
    except ValueError as exc:
        if "forrásfájl" in str(exc):
            raise HTTPException(409, "A forrásfájl már nem érhető el; töltsd fel újra.")
        raise


def generate(db, template, run):
    """(plan, row iterator). Two passes: SKU counts first (duplicates), then rows."""
    headers = [("" if h is None else str(h)) for h in run.analysis["headers"]]
    p = plan(template, headers)
    sku_col = next((c["source_columns"][0] for c in p["columns"]
                    if c["target"]["key"] == "cikkszam" and c["source_columns"]), None)
    counts = Counter()
    if sku_col is not None:
        for _, raw in data_rows(db, run):
            value = raw[sku_col] if sku_col < len(raw) else ""
            if not blank(value):
                counts[str(value).strip()] += 1
    _, values, _, _ = tp.source_profile(db, run)
    currency_columns = [i for i, vals in enumerate(values)
                        if vals and {v.strip().upper() for v in vals if v.strip()}
                        <= set(tp.CURRENCIES)]

    def iterate():
        for line, raw in data_rows(db, run):
            row = convert(p, raw, raw, counts, currency_columns)
            row["line"] = line
            yield row

    return p, iterate()


def public_columns(p):
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in p["columns"]]


def preview(db, template, run, offset, limit):
    limit = max(1, min(limit, MAX_LIMIT))
    p, items = generate(db, template, run)
    page, total, exportable = [], 0, 0
    errors, warnings = Counter(), Counter()
    for row in items:
        total += 1
        exportable += row["status"] != "error"
        errors.update(e["code"] for e in row["errors"])
        warnings.update(w["code"] for w in row["warnings"])
        if offset < total <= offset + limit:
            page.append({"line": row["line"], "values": row["values"],
                         "status": row["status"], "errors": row["errors"],
                         "warnings": row["warnings"]})
    tpl = template.config["template"]
    return {"template": {"id": template.id, "name": template.name,
                         "version": template.version, "currency": tpl["currency"],
                         "engine": tpl["engine"]},
            "run_id": run.id, "columns": public_columns(p), "rows": page,
            "offset": offset, "limit": limit, "total": total,
            "summary": {"rows": total, "exportable": exportable,
                        "excluded": total - exportable, "errors": dict(errors),
                        "warnings": dict(warnings)},
            "excluded_columns": p["excluded"], "missing_source_columns": p["missing"]}


def export_rows(db, template, run):
    """(headers, iterator of value lists for exportable rows, counters dict)."""
    p, items = generate(db, template, run)
    counters = {"exported": 0, "excluded": 0}

    def iterate():
        for row in items:
            if row["status"] == "error":
                counters["excluded"] += 1
                continue
            counters["exported"] += 1
            yield row["values"]

    return [c["header"] for c in p["columns"]], iterate(), counters


def write_xlsx(path, headers, items):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    book = Workbook(write_only=True)
    sheet = book.create_sheet("UNAS")
    sheet.append(headers)
    for values in items:
        out = []
        for value in values:
            c = WriteOnlyCell(sheet, value=value)
            c.number_format = "@"  # text: identifiers and leading zeros are safe
            c.data_type = "s"
            out.append(c)
        sheet.append(out)
    book.save(path)


def csv_chunks(headers, items):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    buffer.write("﻿")
    writer.writerow(headers)
    for n, values in enumerate(items, 1):
        writer.writerow(values)
        if n % 500 == 0:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue().encode("utf-8")


def filename(template, run, extension):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", template.name).strip("_") or "sablon"
    return f"UNAS_{safe}_v{template.version}_{run.id}.{extension}"
