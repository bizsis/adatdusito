"""Bounded sampling and streaming CSV/XLSX reader; all identifiers stay textual."""

import csv
import re
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from openpyxl import load_workbook

FIELDS = {
    "supplier_id": ("Beszállítói termékazonosító", "id product_id item_code itemid"),
    "sku": (
        "Beszállítói cikkszám",
        "articlenr sku cikkszám cikkszam article itemnumber",
    ),
    "mpn": ("Gyártói cikkszám", "productionnr mpn manufacturer_part_number"),
    "gtin": ("EAN/GTIN", "ean gtin barcode vonalkód vonalkod"),
    "brand": ("Gyártó", "brand manufacturer gyártó gyarto"),
    "model": ("Modell", "model modell"),
    "name": ("Terméknév", "name product_name terméknév megnevezés description1"),
    "description": ("Termékleírás", "description leírás leiras"),
    "category": ("Beszállítói kategória", "category kategória kategora group"),
    "product_type": ("Terméktípus", "type típus"),
    "packaging": ("Kiszerelés", "pack packaging kiszerelés"),
    "unit": ("Mennyiségi egység", "unit uom egység"),
    "weight": ("Tömeg", "weight tömeg súly"),
    "dimensions": ("Méretek", "dimensions méretek"),
    "attributes": ("Műszaki attribútum", "attributes specification paraméter"),
    "purchase_price": ("Beszerzési ár (jóváhagyott)", "purchase_price"),
    "list_price": ("Listaár (jóváhagyott)", "list_price"),
    "price_type": ("Ártípus", "price_type ártípus"),
    "price": ("Ár", "price ár listprice lastinitialcost cost"),
    "tax_basis": ("Nettó/bruttó", "tax_basis net_gross"),
    "currency": ("Pénznem", "currencycode currency pénznem deviza"),
    "vat": ("Áfakulcs", "tax vat áfa afa"),
    "sale_price": ("Akciós ár", "sale_price discountprice"),
    "stock": ("Készlet", "stock quantity qty készlet mennyiség"),
    "availability": ("Elérhetőség", "availability elérhetőség"),
    "shipping": ("Szállítás", "shipping delivery szállítás"),
    "images": ("Képlinkek", "images image picture kép képek"),
    "documents": ("Dokumentumok", "documents dokumentum"),
    "language": ("Forrásnyelv", "language nyelv"),
    "notes": ("Megjegyzések", "notes megjegyzés"),
    "sale_start": ("Akció kezdete", "sale_start specialstart"),
    "sale_end": ("Akció vége", "sale_end specialexpire"),
    "other": ("Egyéb attribútum", "other egyéb"),
}
IDENTIFIERS = {"supplier_id", "sku", "mpn", "gtin", "model"}
NUMERIC = {
    "purchase_price",
    "list_price",
    "price",
    "sale_price",
    "stock",
    "vat",
    "weight",
}
FINANCIAL = {
    "purchase_price",
    "list_price",
    "price",
    "sale_price",
    "currency",
    "tax_basis",
    "vat",
    "price_type",
}


def norm(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(c) and c.isalnum()
    )


def text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def decimal(value):
    value = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Nem véges szám")
    return format(result, "f")


def normalize(field, value):
    raw = text(value).strip()
    issues = []
    if not raw:
        return None, issues
    if field in ("sale_start", "sale_end"):
        for pattern in (
            "%Y-%m-%d",
            "%Y.%m.%d",
            "%Y.%m.%d.",
            "%d.%m.%Y",
            "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(raw, pattern).isoformat(), issues
            except ValueError:
                pass
        return raw, ["uncertain_date"]
    if raw.startswith("="):
        issues.append("formula_requires_review")
    if field in IDENTIFIERS:
        if getattr(value, "uncertain_identifier", False):
            issues.append("excel_identifier_precision_requires_review")
        if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+", raw):
            # Exponent text cannot prove digits already rounded by the producer.
            issues.append("scientific_identifier_requires_review")
        if field == "gtin" and (not raw.isdigit() or len(raw) not in (8, 12, 13, 14)):
            issues.append("invalid_gtin")
        return raw, issues
    if field in NUMERIC:
        try:
            return decimal(raw), issues
        except (InvalidOperation, ValueError):
            return None, ["invalid_number"]
    return raw, issues


def settings(path, filename, config):
    if filename.lower().endswith(".xlsx"):
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > 200_000_000:
                raise ValueError("Túl nagy XLSX kibontási méret")
        w = load_workbook(path, read_only=True, data_only=False)
        names = w.sheetnames
        w.close()
        sheet = config.get("sheet") or names[0]
        if sheet not in names:
            raise ValueError("Ismeretlen munkalap")
        return {**config, "format": "xlsx", "sheet": sheet, "sheets": names}
    with open(path, "rb") as f:
        sample = f.read(65536)
    encoding = config.get("encoding")
    if encoding not in (None, "utf-8-sig", "utf-16", "cp1250", "cp1252"):
        raise ValueError("Nem engedélyezett kódolás")
    if not encoding:
        if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        else:
            try:
                sample.decode("utf-8-sig")
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                encoding = "cp1250"
    content = sample.decode(encoding)
    delimiter = config.get("delimiter")
    if delimiter not in (None, ",", ";", "\t", "|"):
        raise ValueError("Nem engedélyezett elválasztó")
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(content, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ";"
    return {**config, "format": "csv", "encoding": encoding, "delimiter": delimiter}


class CellText(str):
    """Retain Excel type/format evidence alongside the textual cell value."""

    def __new__(cls, cell):
        raw = text(cell.value)
        fmt = getattr(cell, "number_format", "") or ""
        numeric = isinstance(cell.value, (int, float))
        if numeric and cell.value == int(cell.value) and re.fullmatch(r"0+", fmt):
            raw = str(int(cell.value)).zfill(len(fmt))
        obj = super().__new__(cls, raw)
        obj.excel_format = fmt
        obj.numeric = numeric
        obj.uncertain_identifier = numeric and (
            "e+" in fmt.casefold()
            or "e-" in fmt.casefold()
            or len(raw.replace("-", "")) > 15
        )
        return obj


def rows(path, config):
    max_columns = 512
    if config["format"] == "xlsx":
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            for i, row in enumerate(book[config["sheet"]].iter_rows(), 1):
                if len(row) > max_columns:
                    raise ValueError("Túl sok oszlop")
                # Preserve raw numeric spelling/format evidence; never execute formulas.
                yield i, [CellText(c) for c in row]
        finally:
            book.close()
    else:
        csv.field_size_limit(1_000_000)
        with open(path, encoding=config["encoding"], newline="") as f:
            for i, row in enumerate(csv.reader(f, delimiter=config["delimiter"]), 1):
                if len(row) > max_columns:
                    raise ValueError("Túl sok oszlop")
                yield i, row


def analyze(path, filename, config):
    config = settings(path, filename, config)
    sample = []
    for i, row in rows(path, config):
        if i > 100:
            break
        sample.append((i, row))
    if not sample:
        raise ValueError("Üres fájl")

    def score(r):
        return sum(
            any(
                norm(c) == norm(a)
                for _, aliases in FIELDS.values()
                for a in aliases.split()
            )
            for c in r
        ) * 10 + sum(bool(c) and not c.replace(".", "").isdigit() for c in r)

    header_line = int(
        config.get("header_line") or max(sample[:20], key=lambda r: score(r[1]))[0]
    )
    header = next((r for i, r in sample if i == header_line), None)
    if not header or header_line < 1:
        raise ValueError("Érvénytelen fejlécsor")
    config["header_line"] = header_line
    data = [r for i, r in sample if i > header_line and any(c.strip() for c in r)][:30]
    columns = []
    for i, h in enumerate(header):
        matches = [
            key
            for key, (_, aliases) in FIELDS.items()
            if norm(h) in [norm(a) for a in aliases.split()]
        ]
        key = matches[0] if len(matches) == 1 else None
        vals = [r[i] for r in data if i < len(r) and r[i].strip()]
        if (
            not key
            and vals
            and all(v.isdigit() and len(v) in (8, 12, 13, 14) for v in vals)
        ):
            key = "gtin"
            method = "content"
            confidence = 0.65
        else:
            method = "header" if key else "unknown"
            confidence = 0.98 if key else 0
        numeric = (
            sum(not normalize("price", v)[1] for v in vals) / len(vals)
            if vals
            else None
        )
        numeric_values = [
            Decimal(decimal(v)) for v in vals if not normalize("price", v)[1]
        ]
        numeric_mean = (
            str(sum(numeric_values) / len(numeric_values)) if numeric_values else None
        )
        columns.append(
            {
                "index": i,
                "header": h,
                "field": key,
                "confidence": confidence,
                "method": method,
                "approved": False,
                "samples": vals[:3],
                "numeric_ratio": numeric,
                "numeric_mean": numeric_mean,
                "unique_ratio": len(set(vals)) / len(vals) if vals else None,
                "critical": key in FINANCIAL or key == "gtin",
            }
        )
    return config, {"headers": header, "columns": columns, "preview": data[:10]}


class AISuggestionProvider:
    """Optional adapter. No provider or paid call is enabled by default."""

    def suggest(self, columns, *, authorized_credits):
        if authorized_credits <= 0:
            raise ValueError("Nincs engedélyezett AI-kredit")
        raise NotImplementedError(
            "Nincs konfigurált AI-szolgáltató; kézi megfeleltetés használható."
        )
