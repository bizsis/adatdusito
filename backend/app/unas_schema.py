"""UNAS export header registry (UNAS-REF-01): standard columns, store-specific columns and
parameter headers, parsed losslessly. No network access, no writes to pinfo_db.

Evidence levels used in this module (``*_source`` fields):

* ``unas_help_excerpt``: UNAS help/blog search excerpts read on 2026-11-17 (the unas.hu pages
  themselves were not reachable from the build environment) - treated as provisional;
* ``export_sample``: what the uploaded UNAS export itself shows (fill rate, value shape);
* ``adatdusito``: a project recommendation, not an UNAS rule.

Nothing here claims to be the complete official UNAS schema: a column seen in one export is
a column of that export. Store-specific columns (customer-group prices, the shop's own
parameters) are never global requirements.
"""

import re
import unicodedata

PARAMETER_PREFIX = "Paraméter: "
# Positions of a parameter header after the "Paraméter: " prefix, split on "|". Only the
# positions visible in the export sample are named; every other position is kept raw.
#   0 name, 1 group (may be empty), 2 type, 10 unit (e.g. "cm" on num parameters).
PARAMETER_TYPES = {"text", "num", "enum", "enummore", "link_text"}
CUSTOMER_GROUP_PRICE = re.compile(r"^Ár( típus)?: ")
CUSTOMER_GROUP_COLUMNS = {"Vásárló csoport vásárolhatja", "Vásárló csoport láthatja"}

HELP = "unas_help_excerpt"
SAMPLE = "export_sample"
PROJECT = "adatdusito"

# (group, data_type) for the standard UNAS export columns seen in the sample.
STANDARD = {
    "Cikkszám": ("identity", "text"),
    "Termék Név": ("identity", "text"),
    "Státusz": ("visibility", "integer"),
    "Publikus időszak kezdete": ("visibility", "datetime"),
    "Publikus időszak vége": ("visibility", "datetime"),
    "Nettó Ár": ("price", "decimal"),
    "Bruttó Ár": ("price", "decimal"),
    "Akciós Nettó Ár": ("price", "decimal"),
    "Akciós Bruttó Ár": ("price", "decimal"),
    "Akció Kezdet": ("price", "date"),
    "Akció Lejárat": ("price", "date"),
    "Ár megjelenés": ("price", "text"),
    "Automatikus kuponsablon": ("price", "text"),
    "Kategória": ("category", "category_path"),
    "Rövid Leírás": ("description", "html"),
    "Tulajdonságok": ("description", "html"),
    "Link": ("media", "url"),
    "Kép link": ("media", "url"),
    "Termék link": ("system", "url"),
    "Min. Menny.": ("quantity", "decimal"),
    "Menny. kezdeti érték": ("quantity", "decimal"),
    "Max. Menny.": ("quantity", "decimal"),
    "Lépésköz": ("quantity", "decimal"),
    "Raktárkészlet": ("stock", "decimal"),
    "Vásárolható, ha nincs Raktáron": ("stock", "flag"),
    "Változatokhoz Raktárkészlet": ("stock", "flag"),
    "Alacsony készlet": ("stock", "decimal"),
    "Létrehozás": ("system", "datetime"),
    "Utolsó Módosítás": ("system", "datetime"),
    "Egység": ("unit", "text"),
    "Másodlagos egység": ("unit", "text"),
    "Másodlagos egység váltószám": ("unit", "decimal"),
    "Tömeg": ("unit", "decimal"),
    "Pont": ("loyalty", "integer"),
    "Pontért megvehető": ("loyalty", "text"),
    "Mennyiségi kedvezmény": ("price", "text"),
    "Szállítási mód tiltás": ("shipping_payment", "id_list"),
    "Szállítási mód engedélyezés": ("shipping_payment", "id_list"),
    "Plusz szállítási költség": ("shipping_payment", "decimal"),
    "Fizetési mód tiltás": ("shipping_payment", "id_list"),
    "Fizetési mód engedélyezés": ("shipping_payment", "id_list"),
    "Plusz kezelési költség": ("shipping_payment", "decimal"),
    "Plusz szolgáltatások": ("services", "id_list"),
    "Plusz szolgáltatások működése": ("services", "text"),
    "Export": ("marketplace_export", "flag"),
    "Export Tiltás": ("marketplace_export", "text_list"),
    "Érdeklődjön Státusz": ("visibility", "flag"),
    "Ne legyen közvetlen kedvezmény": ("price", "flag"),
    "Csak ajándékként Státusz": ("visibility", "flag"),
    "Nincs a listában": ("visibility", "flag"),
    "Egyedi sorrend": ("visibility", "integer"),
    "Explicit": ("visibility", "flag"),
    "Letölthető tartalom": ("media", "text"),
    "Matricák": ("visibility", "text"),
    "Kiegészítő Termékek": ("related", "sku_list"),
    "Hasonló Termékek": ("related", "sku_list"),
    "Kiegészítő Kategóriák": ("related", "category_path"),
    "Hasonló Kategóriák": ("related", "category_path"),
    "Csomag termék": ("related", "text"),
    "Kép kapcsolat": ("variants", "text"),
    "Alap Típus": ("variants", "text"),
    "Altípus listában": ("variants", "flag"),
    "Típus sorrend": ("variants", "integer"),
    "SEF URL": ("seo", "text"),
    "Kép ALT/TITLE": ("seo", "text"),
    "Kép filenév": ("media", "text_list"),
    "OG image": ("seo", "url"),
    "SEO Title": ("seo", "text"),
    "SEO Description": ("seo", "text"),
    "SEO Keywords": ("seo", "text"),
    "SEO Robots": ("seo", "text"),
    "Azonosító": ("system", "integer"),
}
# Numbered standard families: "Tartalmi elemek 1", "CrossSale2", ...
NUMBERED = [
    (re.compile(r"^Tartalmi elemek \d+$"), ("content", "html")),
    (re.compile(r"^Adat \d+$"), ("content", "text")),
    (re.compile(r"^Státusz \d+$"), ("visibility", "flag")),
    (re.compile(r"^(CrossSale|UpSale)\d+$"), ("related", "flag")),
    (re.compile(r"^Választható Tulajdonság \d+$"), ("variants", "text")),
    (re.compile(r"^Alternatív Kategória \d+$"), ("category", "category_path")),
    (re.compile(r"^További lapfül címe \d+$"), ("tabs", "text")),
    (re.compile(r"^További lapfül tartalma \d+$"), ("tabs", "html")),
]
# Provisional: UNAS help excerpts say these must be filled for a new product; the product
# is identified by Cikkszám, and both net and gross price are needed (UNAS stores no VAT rate).
REQUIRED = {
    "Cikkszám": "A terméket az UNAS a cikkszám alapján azonosítja.",
    "Termék Név": "Új termékhez kötelező.",
    "Státusz": "Új termékhez kötelező.",
    "Kategória": "Új termékhez kötelező; szintek '|' jellel.",
    "Nettó Ár": "A nettó és a bruttó árat is meg kell adni; áfakulcsot az UNAS nem tárol.",
    "Bruttó Ár": "A nettó és a bruttó árat is meg kell adni; áfakulcsot az UNAS nem tárol.",
}
RECOMMENDED = {
    "Rövid Leírás", "Tulajdonságok", "Kép link", "Raktárkészlet", "Egység", "Tömeg",
}
# Values the shop system generates: exported, but there is no evidence they are importable.
SYSTEM_GENERATED = {"Létrehozás", "Utolsó Módosítás", "Termék link"}
TIME_DEPENDENT_GROUPS = {"price", "stock"}
VALIDATION = {
    "text": {},
    "integer": {"pattern": r"^-?\d+$"},
    "decimal": {"number": True},
    "flag": {"allowed": ["0", "1"]},
    "url": {"scheme": ["http", "https"]},
    "date": {"format": "YYYY.MM.DD"},
    "datetime": {"format": "YYYY.MM.DD HH:MM:SS"},
}


def field_key(header):
    """ASCII snake-case key of a header: "Termék Név" -> "termek_nev"."""
    folded = unicodedata.normalize("NFKD", header.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")[:120] or "column"


def parse_parameter(header):
    """Split a "Paraméter: ..." header; returns None for any other header.

    Unknown positions are never interpreted; they stay in ``settings`` exactly as written.
    """
    if not header.startswith(PARAMETER_PREFIX):
        return None
    parts = header[len(PARAMETER_PREFIX):].split("|")
    name = parts[0].strip()
    group = parts[1].strip() if len(parts) > 1 else ""
    kind = parts[2].strip() if len(parts) > 2 else ""
    unit = parts[10].strip() if len(parts) > 10 and parts[10].strip() else None
    return {
        "name": name,
        "group_name": group,
        "param_type": kind,
        "known_type": kind in PARAMETER_TYPES,
        "unit": unit,
        "unit_source": SAMPLE if unit else None,
        "settings": parts[3:],
        "header": header,
    }


def classify(header):
    """Registry entry for one header (without position, profile or source metadata)."""
    parameter = parse_parameter(header)
    if parameter:
        return {
            "scope": "store_specific",
            "field_group": "parameter",
            "data_type": "parameter:" + parameter["param_type"],
            "requirement": "optional",
            "requirement_source": SAMPLE,
            "importable": True,
            "validation": {"parameter_type": parameter["param_type"]},
            "note": "Az áruház saját paramétere; nem globális UNAS-mező.",
            "parameter": parameter,
        }
    if CUSTOMER_GROUP_PRICE.match(header) or header in CUSTOMER_GROUP_COLUMNS:
        return {
            "scope": "store_specific",
            "field_group": "customer_group",
            "data_type": "decimal" if header.startswith("Ár: ") else "text",
            "requirement": "optional",
            "requirement_source": SAMPLE,
            "importable": True,
            "validation": {},
            "note": "Áruházi vevőcsoport-beállítás; nem kerül a referenciatárba.",
            "parameter": None,
        }
    known = STANDARD.get(header) or next((v for p, v in NUMBERED if p.match(header)), None)
    group, data_type = known or ("unknown", "text")
    if header in REQUIRED:
        requirement, source, note = "required", HELP, REQUIRED[header]
    elif header in RECOMMENDED:
        requirement, source, note = "recommended", PROJECT, "Adatdúsító-javaslat."
    else:
        requirement, source, note = "optional", SAMPLE, None
    return {
        "scope": "standard" if known else "unknown",
        "field_group": group,
        "data_type": data_type,
        "requirement": requirement,
        "requirement_source": source,
        "importable": None if header == "Azonosító" else header not in SYSTEM_GENERATED,
        "validation": {**VALIDATION.get(data_type, {}),
                       **({"required": True} if requirement == "required" else {}),
                       **({"time_dependent": True} if group in TIME_DEPENDENT_GROUPS else {})},
        "note": note,
        "parameter": None,
    }


def registry(headers):
    """Classify every header of an export, in file order; duplicates are reported."""
    seen = {}
    entries = []
    for position, raw in enumerate(headers):
        header = "" if raw is None else str(raw)
        entry = {"position": position, "header": header, "field_key": field_key(header),
                 **classify(header)}
        if header in seen:
            entry["duplicate_of"] = seen[header]
        seen.setdefault(header, position)
        entries.append(entry)
    return entries


def excluded_from_reference(header):
    """Columns never copied into the reference store (store-specific customer-group data)."""
    return bool(CUSTOMER_GROUP_PRICE.match(header)) or header in CUSTOMER_GROUP_COLUMNS
