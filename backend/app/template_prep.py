"""TEMPLATE-PREP-01: webshop-engine based template preparation (Import -> Előkészítés ->
Sablonkészítés). Contract: docs/design/TEMPLATE-PREP-01-API.md.

A template is a versioned import_profiles row (config.template); no new tables. Saving a
template never approves an import or processes a product. No AI, no eMAG lookup, no export,
no pinfo_db access. Every source column is kept; only the operator can mark a column
"unused"; identifiers stay text; no currency conversion, no fictitious price.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select

from app import unas_schema as us
from app.import_mapping import TRANSLATIONS, approved_parameters, occurrences, parameter_header
from app.import_models import ImportProfile
from app.import_parser import blank, blank_row, decimal, norm, normalize, rows
from app.models import now

ENGINES = {"unas": "UNAS"}
CURRENCIES = ["HUF", "EUR", "USD", "GBP", "CHF", "CZK", "PLN", "RON", "BGN", "RSD", "UAH"]
DEFAULTS = {"statusz": "1", "afa": "27"}
VAT_RATES = {"0", "5", "18", "27"}
AUTO_THRESHOLD = 0.9
SCAN_ROWS = 500

MARKA = "Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1"


def T(key, label, header, evidence, type_="text", group="product", synonyms=(),
      internal=None, multiple=None, required=False, price=False):
    return {"key": key, "label": label, "unas_header": header, "evidence": evidence,
            "type": type_, "group": group, "synonyms": list(synonyms),
            "internal_field": internal, "multiple": multiple, "required": required,
            "price": price, "default": DEFAULTS.get(key)}


# The fixed operator target list (owner decision); labels exactly as given.
TARGETS = [
    T("cikkszam", "Cikkszám", "Cikkszám", "unas_schema", group="identity", required=True,
      internal="sku", synonyms=["sku", "cikkszam", "articlenr", "article", "articleno",
                                "itemnumber", "itemno", "productcode", "termekkod", "code",
                                "kod", "cikk", "ref", "reference", "productid"]),
    T("termek_megnevezes", "Termék megnevezés", "Termék Név", "unas_schema", group="identity",
      internal="name", synonyms=["name", "nev", "productname", "termeknev", "termeknév",
                                 "termekmegnevezes", "megnevezes", "title", "description1",
                                 "productitle", "producttitle"]),
    T("kategoria", "Kategória", "Kategória", "unas_schema", group="category",
      internal="category", synonyms=["category", "kategoria", "categories", "productcategory",
                                     "csoport", "group", "productgroup", "categorypath"]),
    T("alternativ_kategoria", "Alternatív kategória", "Alternatív Kategória {n}",
      "unas_schema", group="category", multiple="instances",
      synonyms=["alternativkategoria", "alternativecategory", "altcategory",
                "secondarycategory", "extracategory"]),
    T("gyarto", "Gyártó", MARKA, "export_sample", internal="brand",
      synonyms=["brand", "manufacturer", "gyarto", "marka", "vendor", "maker", "producer"]),
    T("raktarkeszlet", "Raktárkészlet #0", "Raktárkészlet", "unas_schema", "number", "stock",
      internal="stock", multiple="instances",
      synonyms=["stock", "quantity", "qty", "keszlet", "raktarkeszlet", "inventory", "raktar",
                "stockqty", "onhand"]),
    T("netto_ar", "Nettó ár", "Nettó Ár", "unas_schema", "price", "price", internal="price",
      price=True, synonyms=["netprice", "nettoar", "netto", "pricenet", "priceexvat",
                            "nettoeladasiar", "eladasinettoar", "price", "ar", "listprice",
                            "listaar"]),
    T("brutto_ar", "Bruttó ár", "Bruttó Ár", "unas_schema", "price", "price", price=True,
      synonyms=["grossprice", "bruttoar", "brutto", "pricegross", "priceincvat",
                "fogyasztoiar", "retailprice", "bruttoeladasiar"]),
    T("netto_akcios_ar", "Nettó akciós ár", "Akciós Nettó Ár", "unas_schema", "price", "price",
      internal="sale_price", price=True,
      synonyms=["salenetprice", "akciosnettoar", "nettoakciosar", "specialpricenet",
                "discountnet"]),
    T("brutto_akcios_ar", "Bruttó akciós ár", "Akciós Bruttó Ár", "unas_schema", "price",
      "price", price=True, synonyms=["salegrossprice", "akciosbruttoar", "bruttoakciosar",
                                     "specialprice", "discountprice", "saleprice",
                                     "akciosar"]),
    T("akcio_kezdete", "Akció kezdete", "Akció Kezdet", "unas_schema", "date", "price",
      internal="sale_start", synonyms=["salestart", "akciokezdete", "akciokezdet",
                                       "specialstart", "discountstart", "promostart"]),
    T("akcio_vege", "Akció vége", "Akció Lejárat", "unas_schema", "date", "price",
      internal="sale_end", synonyms=["saleend", "akciovege", "akciolejarat",
                                     "specialexpire", "specialend", "discountend",
                                     "promoend"]),
    T("afa", "ÁFA", None, "none", "percent", "price", internal="vat",
      synonyms=["vat", "afa", "tax", "vatrate", "afakulcs", "taxrate"]),
    T("ean", "EAN", parameter_header("EAN").replace("|1|0|1|0|0|0|", "|1|0|0|0|0|0|"),
      "export_sample", group="identity", internal="gtin",
      synonyms=["ean", "gtin", "barcode", "vonalkod", "ean13", "upc", "gtin13"]),
    T("gyartoi_cikkszam", "Gyártói cikkszám", parameter_header("Gyártói cikkszám"),
      "unverified", group="identity", internal="mpn",
      synonyms=["mpn", "manufacturerpartnumber", "gyartoicikkszam", "partnumber",
                "productionnr", "manufacturercode"]),
    T("reszletes_leiras", "Részletes leírás", "Tulajdonságok", "unas_schema", "html",
      "description", internal="description",
      synonyms=["description", "longdescription", "leiras", "reszletesleiras",
                "tulajdonsagok", "details", "fulldescription"]),
    T("rovid_leiras", "Rövid leírás", "Rövid Leírás", "unas_schema", "html", "description",
      synonyms=["shortdescription", "rovidleiras", "summary", "short"]),
    T("mennyisegi_egyseg", "Mennyiségi egység", "Egység", "unas_schema", group="unit",
      internal="unit", synonyms=["unit", "uom", "egyseg", "mennyisegiegyseg",
                                 "mertekegyseg"]),
    T("masodlagos_egyseg", "Másodlagos egység", "Másodlagos egység", "unas_schema",
      group="unit", synonyms=["secondaryunit", "masodlagosegyseg"]),
    T("masodlagos_mennyiseg", "Másodlagos mennyiség", "Másodlagos egység váltószám",
      "unas_schema", "number", "unit",
      synonyms=["secondaryquantity", "masodlagosmennyiseg", "valtoszam"]),
    T("min_rendelheto", "Min. rendelhető mennyiség", "Min. Menny.", "unas_schema", "number",
      "quantity", synonyms=["minorder", "minqty", "minimumorder", "minrendelheto",
                            "minmenny", "minorderquantity", "minrendelhetomennyiseg"]),
    T("lepeskoz", "Lépésköz", "Lépésköz", "unas_schema", "number", "quantity",
      synonyms=["step", "lepeskoz", "orderstep"]),
    T("statusz", "Státusz", "Státusz", "unas_schema", "flag", "visibility",
      synonyms=["status", "statusz", "active", "aktiv", "enabled"]),
    T("tomeg", "Tömeg", "Tömeg", "unas_schema", "number", "unit", internal="weight",
      synonyms=["weight", "tomeg", "suly", "grossweight", "netweight"]),
    T("osszevonas_alapja", "Termék összevonás alapja", "Alap Típus", "unverified",
      group="variants", synonyms=["parentsku", "mastersku", "variantparent", "alaptipus",
                                  "groupsku", "osszevonasalapja", "termekosszevonasalapja"]),
    T("export_tiltas", "Export tiltás", "Export Tiltás", "unas_schema",
      group="marketplace_export", synonyms=["exporttiltas", "noexport", "exportdisabled"]),
    T("kep", "Kép", "Kép link", "unas_schema", group="media", internal="images",
      multiple="ordered", synonyms=["image", "images", "imageurl", "picture", "photo", "kep",
                                    "kepek", "keplink", "img", "imagelink", "pictureurl"]),
    T("lapful_1", "További lapfül 1", "További lapfül tartalma 1", "unas_schema", "html",
      "tabs", synonyms=["tovabbilapful1", "lapful1", "tab1"]),
    T("lapful_2", "További lapfül 2", "További lapfül tartalma 2", "unas_schema", "html",
      "tabs", synonyms=["tovabbilapful2", "lapful2", "tab2"]),
    T("lapful_3", "További lapfül 3", "További lapfül tartalma 3", "unas_schema", "html",
      "tabs", synonyms=["tovabbilapful3", "lapful3", "tab3"]),
    T("kiegeszito_termekek", "Kiegészítő termékek", "Kiegészítő Termékek", "unas_schema",
      group="related", synonyms=["accessories", "kiegeszitotermekek", "crosssell"]),
    T("hasonlo_termekek", "Hasonló termékek", "Hasonló Termékek", "unas_schema",
      group="related", synonyms=["similarproducts", "hasonlotermekek", "related",
                                 "relatedproducts"]),
    T("parameter", "Paraméter", "Paraméter: <név>|<csoport>|<típus>|…", "unas_schema",
      group="parameter", multiple="instances"),
]
# TEMPLATE-FIX-02: every documented, importable UNAS column not yet in the list above. The
# label is the technical UNAS header itself (no invented operator names); system-generated
# columns, "Azonosító" (importability unproven) and customer-group prices stay out.
ADDED = "template-fix-02"
SCHEMA_TYPES = {"integer": "number", "decimal": "number", "date": "date",
                "datetime": "date", "flag": "flag", "html": "html"}
# Numbered families with the numbers seen in the real UNAS export (nothing beyond).
NUMBERED_TARGETS = [
    ("tartalmi_elemek", "Tartalmi elemek {n}", 1, 3, "content", "html"),
    ("adat", "Adat {n}", 1, 3, "content", "text"),
    ("statusz_n", "Státusz {n}", 1, 3, "visibility", "flag"),
    ("crosssale", "CrossSale{n}", 1, 3, "related", "flag"),
    ("upsale", "UpSale{n}", 1, 2, "related", "flag"),
    ("valaszthato_tulajdonsag", "Választható Tulajdonság {n}", 1, 3, "variants", "text"),
    ("tovabbi_lapful_cime", "További lapfül címe {n}", 1, 3, "tabs", "text"),
]
INSTANCE_RANGE = {"alternativ_kategoria": (1, 99), "raktarkeszlet": (0, 99)}


def extra_targets():
    have = {t["unas_header"] for t in TARGETS if t["unas_header"]}
    out = []
    for header, (group, data_type) in us.STANDARD.items():
        if header in have or header in us.SYSTEM_GENERATED or header == "Azonosító":
            continue
        out.append(T(us.field_key(header), header, header, "unas_schema",
                     SCHEMA_TYPES.get(data_type, "text"), group) | {"added_in": ADDED})
    for key, header, low, high, group, type_ in NUMBERED_TARGETS:
        out.append(T(key, header.replace("{n}", " n").replace("  ", " "), header,
                     "unas_schema", type_, group, multiple="instances") | {"added_in": ADDED})
        INSTANCE_RANGE[key] = (low, high)
    return out


TARGETS += extra_targets()
for _t in TARGETS:
    if _t["key"] in INSTANCE_RANGE:
        _t["min_instance"], _t["max_instance"] = INSTANCE_RANGE[_t["key"]]
BY_KEY = {t["key"]: t for t in TARGETS}
PARAMETER_PREFIX = re.compile(r"^\s*param[eé]ter\s*:\s*", re.IGNORECASE)


def clean_name(name):
    """A parameter name without the "Paraméter:" prefix (never doubled) or a technical tail."""
    text = (name or "").strip()
    while PARAMETER_PREFIX.match(text):
        text = PARAMETER_PREFIX.sub("", text, count=1).split("|", 1)[0].strip()
    return text.strip()


def parameter_label(name):
    return f"Paraméter: {clean_name(name)}"


def source_parameter(header):
    """A source column whose header already declares a UNAS parameter."""
    if not PARAMETER_PREFIX.match(header or ""):
        return None
    rest = PARAMETER_PREFIX.sub("", header, count=1)
    if "|" in rest:
        full = us.PARAMETER_PREFIX + rest
        parsed = us.parse_parameter(full)
        if parsed and parsed["name"] and parsed["known_type"]:
            # A documented full header is kept exactly as the source wrote it.
            return {"key": "parameter", "header": full, "parameter": {
                "name": parsed["name"], "param_type": parsed["param_type"],
                "group_name": parsed["group_name"], "unit": parsed["unit"]}}
    name = clean_name(header)
    return {"key": "parameter", "parameter": new_spec(name)} if name else None
PURCHASE = re.compile(r"(cost|beszerz|purchase|lastinitialcost|initialcost|wholesale|"
                      r"nagyker|dealer|vetelar|bekerul)")
TECHNICAL = re.compile(r"^(unknown|column|col|field|oszlop|id|code|kod)?[_\s-]*\d*$|"
                       r"(^|[_\s-])(id|unknown)([_\s-]?\d+)?$", re.IGNORECASE)
IMAGE_URL = re.compile(r"^https?://\S+\.(jpe?g|png|gif|webp)(\?\S*)?$", re.IGNORECASE)


class TemplateError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def targets_payload():
    public = [{k: v for k, v in t.items() if k not in ("synonyms", "price")} | {
        "price": t["price"]} for t in TARGETS]
    return {"engine": {"key": "unas", "name": "UNAS"},
            "engines": [{"key": k, "name": v} for k, v in ENGINES.items()],
            "currencies": CURRENCIES, "default_currency": "HUF", "defaults": dict(DEFAULTS),
            "targets": public}


def unas_header(target, instance=None, parameter_head=None):
    key = target["key"]
    if key == "raktarkeszlet":
        return "Raktárkészlet" if not instance else f"Raktárkészlet #{instance}"
    if key == "parameter":
        return parameter_head
    if key in INSTANCE_RANGE:
        return target["unas_header"].replace("{n}", str(instance))
    return target["unas_header"]


# --- reading the source ----------------------------------------------------------------------


def source_profile(db, run):
    """(headers, per-column samples [first nonempty, values...], source_available)."""
    from app.import_engine import materialize

    headers = [("" if h is None else str(h)) for h in run.analysis["headers"]]
    width = len(headers)
    values = [[] for _ in range(width)]
    cells = [[] for _ in range(width)]
    try:
        with materialize(db, run) as path:
            seen = 0
            for line, raw in rows(path, run.config):
                if line <= run.config["header_line"] or blank_row(raw):
                    continue
                seen += 1
                for i in range(width):
                    cell = raw[i] if i < len(raw) else ""
                    if not blank(cell) and len(values[i]) < 20:
                        values[i].append(str(cell))
                        cells[i].append(cell)
                if seen >= SCAN_ROWS:
                    break
        return headers, values, cells, True
    except ValueError:
        # Older import whose source file expired: the analysis keeps headers and samples.
        stored = {c["index"]: c.get("samples") or [] for c in run.analysis.get("columns", [])}
        for i in range(width):
            values[i] = [str(v) for v in stored.get(i, []) if not blank(v)]
        return headers, values, [[] for _ in range(width)], False


def column_warnings(values, cells, headers, index):
    warnings = []
    if any(re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+", v.strip()) for v in values):
        warnings.append("scientific_notation_identifier")
    if any(getattr(c, "uncertain_identifier", False) for c in cells):
        warnings.append("uncertain_excel_number")
    if headers.count(headers[index]) > 1:
        warnings.append("duplicate_header")
    return warnings


# --- suggestions -----------------------------------------------------------------------------


def base_key(header):
    """'Image 2' / 'image #2' -> 'image' (numbered copies of multi targets)."""
    return re.sub(r"\d+$", "", norm(header))


def suggest(header, values, approved):
    key = norm(header)
    if not key:
        return None
    declared = source_parameter(header)
    if declared:
        return declared, 1.0, "source_parameter"
    for t in TARGETS:  # TEMPLATE-FIX-02 numbered families: "Tartalmi elemek 2" -> instance 2
        if t.get("added_in") and t["multiple"] == "instances":
            pattern = re.escape(t["unas_header"]).replace(r"\{n\}", r"(\d+)")
            match = re.fullmatch(pattern, header.strip())
            low, high = INSTANCE_RANGE[t["key"]]
            if match and low <= int(match.group(1)) <= high:
                return {"key": t["key"], "instance": int(match.group(1))}, 1.0, "exact"
    purchase = bool(PURCHASE.search(key))
    for t in TARGETS:
        if t["key"] == "parameter" or (purchase and t["price"]):
            continue
        names = {norm(t["label"])} | ({norm(t["unas_header"])} if t["unas_header"] else set())
        if key in names:
            return {"key": t["key"]}, 1.0, "exact"
    for t in TARGETS:
        if t["key"] == "parameter" or (purchase and t["price"]):
            continue
        synonyms = set(t["synonyms"])
        if key in synonyms or (t["multiple"] and base_key(header) in synonyms):
            return {"key": t["key"]}, 0.95, "synonym"
    for p in approved:
        if norm(p["name"]) == key:
            return {"key": "parameter", "parameter": spec_of(p)}, 0.9, "approved_parameter"
    if values and not purchase:
        sample = values[:20]
        if all(v.strip().isdigit() and len(v.strip()) in (8, 12, 13, 14) for v in sample):
            return {"key": "ean"}, 0.8, "content"
        if all(IMAGE_URL.match(v.strip()) for v in sample):
            return {"key": "kep"}, 0.8, "content"
        if all(v.strip().rstrip("%").strip() in VAT_RATES for v in sample) and \
                any(v.strip().rstrip("%").strip() != "0" for v in sample):
            return {"key": "afa"}, 0.7, "content"
        if all(v.strip() in ("0", "1") for v in sample):
            return {"key": "statusz"}, 0.65, "content"
    if purchase:
        return None  # a purchase price is never proposed as a sale price
    name = TRANSLATIONS.get(key)
    if name:
        for p in approved:
            if norm(p["name"]) == norm(name):
                return {"key": "parameter", "parameter": spec_of(p)}, 0.7, "approved_parameter"
        return {"key": "parameter", "parameter": new_spec(name)}, 0.7, "new_parameter"
    clean = header.strip()
    if values and 2 <= len(clean) <= 60 and re.search(r"[^\W\d_]", clean) and \
            not TECHNICAL.search(clean) and "|" not in clean:
        return {"key": "parameter", "parameter": new_spec(clean)}, 0.4, "new_parameter"
    return None


def new_spec(name):
    return {"name": clean_name(name), "param_type": "text", "group_name": "", "unit": None}


def spec_of(p):
    return {"name": p["name"], "param_type": p.get("param_type", "text"),
            "group_name": p.get("group_name", ""), "unit": p.get("unit")}


def auto_assignable(target, confidence, method):
    t = BY_KEY[target["key"]]
    return confidence >= AUTO_THRESHOLD and not t["price"] and method != "new_parameter"


# --- templates -------------------------------------------------------------------------------


def all_profiles(db, tenant_id, supplier_id):
    return list(db.scalars(select(ImportProfile).where(
        ImportProfile.tenant_id == tenant_id, ImportProfile.supplier_id == supplier_id)
        .order_by(ImportProfile.id.desc())))


def latest_templates(db, tenant_id, supplier_id):
    latest = {}
    for p in all_profiles(db, tenant_id, supplier_id):
        tpl = p.config.get("template")
        if tpl and tpl["template_key"] not in latest:
            latest[tpl["template_key"]] = p
    return list(latest.values())


def template_parameters(db, tenant_id):
    """Approved parameters of this tenant: templates and IMPORT-MAP-01 mappings."""
    result = {}
    for p in db.scalars(select(ImportProfile).where(ImportProfile.tenant_id == tenant_id)
                        .order_by(ImportProfile.id.desc())):
        for param in (p.config.get("template") or {}).get("parameters", []):
            result.setdefault(param["header"], param)
    for param in approved_parameters(db, tenant_id, "unas"):
        result.setdefault(param["header"], param)
    return list(result.values())


def score(headers, template):
    mine = set(occurrences(headers))
    theirs = {(c["header"], c.get("occurrence", 1)) for c in template.config["template"]
              ["columns"]}
    union = mine | theirs
    return round(len(mine & theirs) / len(union), 4) if union else 0.0


def get_template(db, tenant_id, template_id):
    p = db.get(ImportProfile, template_id)
    if p is None or p.tenant_id != tenant_id or not p.config.get("template"):
        raise HTTPException(404, "A sablon nem található.")
    return p


def check_engine_currency(engine, currency):
    if engine not in ENGINES:
        raise TemplateError(422, "Nem támogatott webshopmotor.", reason="unsupported_engine")
    if currency not in CURRENCIES:
        raise TemplateError(422, "Nem támogatott pénznem.", reason="unsupported_currency")


def preparation(db, run, engine="unas", currency="HUF", template_id=None):
    check_engine_currency(engine, currency)
    if not (run.analysis or {}).get("headers"):
        raise HTTPException(409, "Az elemzés még nem készült el.")
    headers, values, cells, available = source_profile(db, run)
    idents = occurrences(headers)
    approved = template_parameters(db, run.tenant_id)
    candidates = sorted(((score(headers, p), p) for p in latest_templates(
        db, run.tenant_id, run.supplier_id)), key=lambda x: (-x[0], -x[1].id))
    chosen = None
    if template_id:
        chosen = get_template(db, run.tenant_id, template_id)
        if chosen.supplier_id != run.supplier_id:
            raise HTTPException(404, "A sablon nem található.")
    elif template_id is None and candidates and candidates[0][0] >= 0.5:
        chosen = candidates[0][1]
    stored = {}
    if chosen:
        for c in chosen.config["template"]["columns"]:
            stored[(c["header"], c.get("occurrence", 1))] = c
    taken = set()
    columns = []
    for i, header in enumerate(headers):
        s = suggest(header, values[i], approved)
        entry = {"index": i, "header": header, "occurrence": idents[i][1],
                 "sample": values[i][0] if values[i] else None,
                 "sample_source": "file" if available else "analysis",
                 "empty": not values[i],
                 "warnings": column_warnings(values[i], cells[i], headers, i),
                 "suggestion": {"target": s[0], "confidence": s[1], "method": s[2],
                                "label": target_label(s[0])} if s
                 else None,
                 "assignment": None, "assignment_source": None, "status": "unmapped"}
        saved = stored.get(idents[i])
        if saved is not None:
            entry["assignment"] = {"state": saved["state"], "target": saved.get("target")}
            entry["assignment_source"], entry["status"] = "template", "from_template"
            if saved["state"] == "mapped" and saved.get("target"):
                taken.add(slot(saved["target"]))
        elif chosen is not None:
            entry["status"] = "new"
        columns.append(entry)
    # Automatic assignments for certain, non-price recognitions not taken by the template.
    for entry in sorted(columns, key=lambda e: -(e["suggestion"] or {}).get("confidence", 0)):
        s = entry["suggestion"]
        if entry["assignment"] or not s or not auto_assignable(s["target"], s["confidence"],
                                                              s["method"]):
            continue
        key = slot(s["target"])
        if key in taken and BY_KEY[s["target"]["key"]]["multiple"] is None:
            continue
        taken.add(key)
        entry["assignment"] = {"state": "mapped", "target": s["target"]}
        entry["assignment_source"] = "auto"
        if entry["status"] == "unmapped":
            entry["status"] = "suggested"
    result = {
        "run_id": run.id, "supplier_id": run.supplier_id, "engine": engine,
        "currency": currency,
        "file": {**{k: run.config.get(k) for k in ("format", "sheet", "sheets", "encoding",
                                                   "delimiter", "header_line",
                                                   "record_path")},
                 "data_rows": run.analysis.get("data_rows"), "source_available": available},
        "columns": columns, "template": None,
        "template_candidates": [{"id": p.id, "name": p.name, "version": p.version,
                                 "score": sc} for sc, p in candidates],
        "approved_parameters": [{"name": p["name"], "header": p["header"],
                                 "label": parameter_label(p["name"])} for p in approved],
        "occupied": occupied([(c["index"], c["assignment"]["target"]) for c in columns
                              if (c["assignment"] or {}).get("state") == "mapped"
                              and c["assignment"].get("target")]),
        "defaults": dict(chosen.config["template"]["defaults"]) if chosen else dict(DEFAULTS),
        "warnings": currency_warnings(values, currency)}
    if chosen:
        mine = set(idents)
        theirs = set(stored)
        result["template"] = {
            "id": chosen.id, "name": chosen.name, "version": chosen.version,
            "template_key": chosen.config["template"]["template_key"],
            "currency": chosen.config["template"]["currency"],
            "score": score(headers, chosen),
            "missing_headers": sorted(h for h, _ in theirs - mine),
            "new_headers": sorted(h for h, _ in mine - theirs)}
    return result


def slot(target):
    key = target["key"]
    if key == "parameter":
        p = target.get("parameter") or {}
        return ("parameter", target.get("header") or p.get("name"))
    if key in INSTANCE_RANGE:
        return (key, target.get("instance"))
    if key == "kep":
        return (key, target.get("order"))
    return (key,)


def currency_warnings(values, currency):
    mismatched, columns = set(), []
    for i, vals in enumerate(values):
        codes = {v.strip().upper() for v in vals if v.strip()}
        if codes and codes <= set(CURRENCIES) and codes - {currency}:
            columns.append(i)
            mismatched |= codes - {currency}
    if columns:
        return [{"code": "currency_mismatch", "columns": columns, "values": sorted(mismatched)}]
    return []


# --- validation ------------------------------------------------------------------------------


def amount(value):
    try:
        return Decimal(decimal(value))
    except (InvalidOperation, ValueError):
        return None


def validate(db, run, body):
    """Report only; never writes."""
    check_engine_currency(body["engine"], body["currency"])
    if not (run.analysis or {}).get("headers"):
        raise HTTPException(409, "Az elemzés még nem készült el.")
    headers = [("" if h is None else str(h)) for h in run.analysis["headers"]]
    errors, warnings = [], []
    defaults = {**DEFAULTS, **(body.get("defaults") or {})}
    if defaults["statusz"] not in ("0", "1") or defaults["afa"] not in VAT_RATES:
        errors.append({"code": "invalid_default"})
    approved = {p["header"]: p for p in template_parameters(db, run.tenant_id)}
    new_params = {}
    for p in body.get("new_parameters", []):
        # TEMPLATE-FIX-02: the name is enough; the "Paraméter:" prefix is never doubled.
        p = {**p, "name": clean_name(p.get("name"))}
        try:
            header = parameter_header(p["name"], p.get("param_type") or "text",
                                      p.get("group_name") or "", p.get("unit"))
        except ValueError:
            errors.append({"code": "invalid_parameter", "name": p.get("name")})
            continue
        if p.get("approved") is True:
            new_params[header] = {**spec_of(p), "header": header}
    declared = declared_parameters(headers)
    indexes = sorted(c["index"] for c in body["columns"])
    if indexes != list(range(len(headers))):
        errors.append({"code": "missing_columns",
                       "columns": sorted(set(range(len(headers))) - set(indexes))})
    resolved, seen, undecided = [], {}, []
    next_instance = {k: low for k, (low, _) in INSTANCE_RANGE.items()}
    used_instances = {k: set() for k in INSTANCE_RANGE}
    used_orders = set()
    mapped = sorted((c for c in body["columns"] if c.get("state") == "mapped"),
                    key=lambda c: c["index"])
    for c in mapped:  # explicit instances/orders first, so automatic ones skip them
        t = c.get("target") or {}
        if t.get("key") in used_instances and t.get("instance") is not None:
            used_instances[t["key"]].add(t["instance"])
        if t.get("key") == "kep" and t.get("order") is not None:
            used_orders.add(t["order"])
    for c in sorted(body["columns"], key=lambda c: c["index"]):
        if not 0 <= c["index"] < len(headers):
            continue
        if c.get("state") is None:
            undecided.append(c["index"])
            continue
        if c["state"] == "unused":
            continue
        t = dict(c.get("target") or {})
        target = BY_KEY.get(t.get("key"))
        if target is None:
            errors.append({"code": "unknown_target", "columns": [c["index"]],
                           "target": t.get("key")})
            continue
        head = None
        if target["key"] == "parameter":
            spec = t.get("parameter") or {}
            try:
                head = t.get("header") or parameter_header(
                    clean_name(spec.get("name")), spec.get("param_type") or "text",
                    spec.get("group_name") or "", spec.get("unit"))
            except ValueError:
                errors.append({"code": "invalid_parameter", "columns": [c["index"]]})
                continue
            if head not in approved and head not in new_params and head not in declared:
                errors.append({"code": "parameter_not_approved", "columns": [c["index"]],
                               "target": head})
                continue
            parsed = us.parse_parameter(head)
            t = {"key": "parameter", "header": head,
                 "parameter": {"name": parsed["name"], "param_type": parsed["param_type"],
                               "group_name": parsed["group_name"], "unit": parsed["unit"]}}
        elif target["key"] in used_instances:
            if t.get("instance") is None:
                n = next_instance[target["key"]]
                while n in used_instances[target["key"]]:
                    n += 1
                t["instance"] = n
                used_instances[target["key"]].add(n)
                next_instance[target["key"]] = n + 1
            minimum, maximum = INSTANCE_RANGE[target["key"]]
            if not isinstance(t["instance"], int) or not minimum <= t["instance"] <= maximum:
                errors.append({"code": "unknown_target", "columns": [c["index"]],
                               "target": target["key"]})
                continue
        elif target["key"] == "kep":
            if t.get("order") is None:
                n = 1
                while n in used_orders:
                    n += 1
                t["order"] = n
                used_orders.add(n)
            if not isinstance(t["order"], int) or not 1 <= t["order"] <= 99:
                errors.append({"code": "unknown_target", "columns": [c["index"]],
                               "target": "kep"})
                continue
        t = {k: v for k, v in t.items() if k in ("key", "instance", "order", "header",
                                                  "parameter") and v is not None}
        seen.setdefault(slot(t), []).append(c["index"])
        resolved.append({"index": c["index"], "header": headers[c["index"]], "target": t,
                         "unas_header": unas_header(target, t.get("instance"), head),
                         "label": target_label(t, head)})
    for key, cols in seen.items():
        if len(cols) > 1:
            errors.append({"code": "duplicate_target", "columns": cols, "target": key[0]})
    by_key = {}
    for r in resolved:
        by_key.setdefault(r["target"]["key"], []).append(r)
    if "cikkszam" not in by_key:
        errors.append({"code": "cikkszam_required"})
    for r in resolved:
        if BY_KEY[r["target"]["key"]]["price"] and PURCHASE.search(norm(r["header"])):
            warnings.append({"code": "purchase_price_as_sale_price", "columns": [r["index"]],
                             "target": r["target"]["key"]})
    if undecided:
        warnings.append({"code": "undecided_columns", "columns": undecided})
    _, values, _, available = source_profile(db, run)
    warnings += currency_warnings(values, body["currency"])
    price_missing = "netto_ar" not in by_key and "brutto_ar" not in by_key
    if price_missing:
        warnings.append({"code": "price_missing"})
    fields = field_report(by_key, defaults)
    if available:
        warnings += row_warnings(db, run, by_key)
    return {"valid": not errors, "errors": errors, "warnings": warnings, "fields": fields,
            "price_missing": price_missing,
            "parameters_to_create": [{"name": p["name"], "header": h}
                                     for h, p in new_params.items()
                                     if h not in approved and ("parameter", h) in seen],
            "resolved": resolved,
            "occupied": occupied([(r["index"], r["target"]) for r in resolved]),
            "_new_params": new_params, "_approved": approved, "_declared": declared,
            "_defaults": defaults}


def declared_parameters(headers):
    """Parameters the source file itself declares ("Paraméter: …" headers): no approval."""
    out = {}
    for h in headers:
        spec = source_parameter(h)
        if spec:
            p = spec["parameter"]
            head = spec.get("header") or parameter_header(p["name"])
            out[head] = {**spec_of(p), "header": head}
    return out


def target_label(target, head=None):
    if target["key"] == "parameter":
        name = (target.get("parameter") or {}).get("name") or (
            (us.parse_parameter(head or target.get("header") or "") or {}).get("name"))
        return parameter_label(name or "")
    base = BY_KEY[target["key"]]
    if target["key"] == "raktarkeszlet":
        return f"Raktárkészlet #{target.get('instance') or 0}"
    if target["key"] in INSTANCE_RANGE and target.get("instance") is not None:
        return unas_header(base, target["instance"]) if base.get("added_in") \
            else f"{base['label']} {target['instance']}"
    return base["label"]


def occupied(entries):
    """Targets taken by the given (column, target) pairs; a cleared assignment frees one."""
    slots = {}
    for index, target in entries:
        key = target["key"]
        base = BY_KEY.get(key)
        if base is None:
            continue
        if key == "parameter":
            name = clean_name((target.get("parameter") or {}).get("name") or (
                us.parse_parameter(target.get("header") or "") or {}).get("name") or "")
            ident = f"parameter:{name}"
        elif key in INSTANCE_RANGE and target.get("instance") is not None:
            ident = f"{key}#{target['instance']}"
        else:
            ident = key
        item = slots.setdefault(ident, {"slot": ident, "key": key, "columns": [],
                                        "label": target_label(target),
                                        "multiple": base["multiple"]})
        if key in INSTANCE_RANGE and target.get("instance") is not None:
            item["instance"] = target["instance"]
        item["columns"].append(index)
    return list(slots.values())


def field_report(by_key, defaults):
    out = []
    pairs = {"netto_ar": ("brutto_ar", "net_from_gross_vat"),
             "brutto_ar": ("netto_ar", "gross_from_net_vat"),
             "netto_akcios_ar": ("brutto_akcios_ar", "net_from_gross_vat"),
             "brutto_akcios_ar": ("netto_akcios_ar", "gross_from_net_vat")}
    for t in TARGETS:
        key = t["key"]
        if key in by_key:
            item = {"key": key, "status": "mapped",
                    "columns": [r["index"] for r in by_key[key]]}
        elif key in DEFAULTS:
            item = {"key": key, "status": "default", "value": defaults[key]}
        elif key in pairs and pairs[key][0] in by_key:
            item = {"key": key, "status": "computed", "rule": pairs[key][1]}
        elif key in ("netto_ar", "brutto_ar"):
            item = {"key": key, "status": "missing"}
        else:
            item = {"key": key, "status": "empty"}
        out.append(item)
    return out


def row_warnings(db, run, by_key):
    """Counts over every data row of the stored file (identifiers stay text)."""
    from app.import_engine import materialize

    def col(key):
        return by_key[key][0]["index"] if key in by_key else None

    net, gross, vat, ean = col("netto_ar"), col("brutto_ar"), col("afa"), col("ean")
    price_rows = invalid_vat = scientific = 0
    with materialize(db, run) as path:
        for line, raw in rows(path, run.config):
            if line <= run.config["header_line"] or blank_row(raw):
                continue

            def cell(i):
                return raw[i] if i is not None and i < len(raw) else ""

            if (net is not None or gross is not None) and \
                    all(blank(cell(i)) for i in (net, gross) if i is not None):
                price_rows += 1
            if vat is not None and not blank(cell(vat)) and \
                    str(cell(vat)).strip().rstrip("%").strip() not in VAT_RATES:
                invalid_vat += 1
            if ean is not None and "scientific_identifier_requires_review" in \
                    normalize("gtin", cell(ean))[1]:
                scientific += 1
    out = []
    for code, count in (("price_rows_missing", price_rows), ("invalid_vat_rows", invalid_vat),
                        ("scientific_identifier_rows", scientific)):
        if count:
            out.append({"code": code, "count": count})
    return out


def public_report(report):
    return {k: v for k, v in report.items() if not k.startswith("_")}


# --- saving ----------------------------------------------------------------------------------


def internal_mapping(resolved):
    """Mapping for the existing import engine (one column per internal field). Net prices
    win over gross ones; the first image (order 1) feeds "images"; extra stock instances
    stay source attributes."""
    gross = {"brutto_ar": "price", "brutto_akcios_ar": "sale_price"}
    candidates = []
    for r in resolved:
        key = r["target"]["key"]
        internal = gross.get(key, BY_KEY[key]["internal_field"])
        if not internal or (key == "raktarkeszlet" and r["target"].get("instance")):
            continue
        rank = (internal, key in gross, r["target"].get("order") or 0, r["index"])
        candidates.append((rank, r["index"], internal))
    mapping, used = {}, set()
    for _, index, internal in sorted(candidates):
        if internal not in used:
            mapping[str(index)] = internal
            used.add(internal)
    return mapping


def save(db, run, body, actor_id):
    report = validate(db, run, body)
    if not report["valid"]:
        raise TemplateError(422, "A sablon nem menthető; lásd a validációt.",
                            validation=public_report(report))
    name = body["name"].strip()
    previous = None
    if body.get("template_id"):
        previous = get_template(db, run.tenant_id, body["template_id"])
        if previous.supplier_id != run.supplier_id:
            raise HTTPException(404, "A sablon nem található.")
    key = previous.config["template"]["template_key"] if previous else uuid.uuid4().hex
    for p in latest_templates(db, run.tenant_id, run.supplier_id):
        if p.name == name and p.config["template"]["template_key"] != key:
            raise TemplateError(409, "Ennél a beszállítónál már van ilyen nevű sablon.",
                                reason="template_name_taken")
    version = 1 + max(
        db.scalar(select(func.max(ImportProfile.version)).where(
            ImportProfile.tenant_id == run.tenant_id,
            ImportProfile.supplier_id == run.supplier_id, ImportProfile.name == name)) or 0,
        max((p.version for p in all_profiles(db, run.tenant_id, run.supplier_id)
             if (p.config.get("template") or {}).get("template_key") == key), default=0))
    headers = [("" if h is None else str(h)) for h in run.analysis["headers"]]
    idents = occurrences(headers)
    _, values, _, _ = source_profile(db, run)
    resolved = {r["index"]: r for r in report["resolved"]}
    columns = []
    for c in sorted(body["columns"], key=lambda c: c["index"]):
        r = resolved.get(c["index"])
        columns.append({"column": c["index"], "header": idents[c["index"]][0],
                        "occurrence": idents[c["index"]][1],
                        "sample": values[c["index"]][0] if values[c["index"]] else None,
                        "state": c.get("state"), "target": r["target"] if r else None,
                        "unas_header": r["unas_header"] if r else None})
    at = now().isoformat()
    parameters, created = [], []
    for r in report["resolved"]:
        if r["target"]["key"] != "parameter":
            continue
        head = r["target"]["header"]
        if head in report["_approved"]:
            parameters.append(report["_approved"][head])
        elif head in report["_declared"] and head not in report["_new_params"]:
            p = {**report["_declared"][head], "approved_by": actor_id, "approved_at": at,
                 "origin": "source_header"}  # declared by the source file itself
            parameters.append(p)
            created.append(p)
        else:
            p = {**report["_new_params"][head], "approved_by": actor_id, "approved_at": at,
                 "origin": "operator_created"}
            parameters.append(p)
            created.append(p)
    profile = ImportProfile(
        tenant_id=run.tenant_id, supplier_id=run.supplier_id, name=name, version=version,
        approved_by=actor_id,
        config={
            "analysis": run.analysis, "mapping": internal_mapping(report["resolved"]),
            "automatic": False,  # a template never processes products by itself
            "template": {
                "template_key": key, "engine": body["engine"], "currency": body["currency"],
                "columns": columns, "defaults": report["_defaults"], "parameters": parameters,
                "price_missing": report["price_missing"],
                "source": {"run_id": run.id, "format": run.config.get("format"),
                           "headers": headers},
                "previous_version_id": previous.id if previous else None}})
    db.add(profile)
    db.flush()
    return profile, public_report(report), created


def template_dto(p, versions=None):
    tpl = p.config["template"]
    return {"id": p.id, "template_key": tpl["template_key"], "name": p.name,
            "version": p.version, "versions": versions, "engine": tpl["engine"],
            "currency": tpl["currency"], "columns": tpl["columns"], "defaults": tpl["defaults"],
            "parameters": tpl["parameters"], "price_missing": tpl["price_missing"],
            "source": tpl["source"], "approved_by": p.approved_by, "created_at": p.created_at}


def supplier_templates(db, tenant_id, supplier_id):
    profiles = all_profiles(db, tenant_id, supplier_id)
    counts = {}
    for p in profiles:
        tpl = p.config.get("template")
        if tpl:
            counts[tpl["template_key"]] = counts.get(tpl["template_key"], 0) + 1
    templates = []
    for p in latest_templates(db, tenant_id, supplier_id):
        dto = template_dto(p, counts[p.config["template"]["template_key"]])
        dto["columns"] = len(dto["columns"])
        for k in ("defaults", "parameters", "source"):
            dto.pop(k)
        templates.append(dto)
    legacy = [{"id": p.id, "name": p.name, "version": p.version,
               "kind": "engine_mapping" if p.config.get("engine_mapping") else "import_profile"}
              for p in profiles if not p.config.get("template")]
    return {"templates": templates, "legacy": legacy}


def versions(db, tenant_id, template):
    key = template.config["template"]["template_key"]
    return [template_dto(p) for p in all_profiles(db, tenant_id, template.supplier_id)
            if (p.config.get("template") or {}).get("template_key") == key]
