"""CATEGORY-03A: deterministic parameter slots from supplier data and donors.

For one product the planner compares the supplier's source values
(source_attributes and a few structured fields) with the parameters of the
product's donor eMAG category (catalog_category_parameter_entries of the
active owned catalog) and produces parameter slots:

* emag:<emag_parameter_id> - one per donor parameter and product. A certain
  match (approved alias or normalized label equality) fills it; uncertain
  matches leave it in review with candidates; nothing matching leaves an empty
  `missing` slot; several different source values make a `conflict`.
* src:<source key> - a supplier attribute that is not certainly matched. It
  is kept, never dropped.

Rules that never change: the original header/value/unit/origin stays verbatim
in `details.sources`; units are only converted by the fixed table below; a
locked slot is never written by automation; an existing non-empty value is
only replaced by a newer value of the *same* source column (feed refresh,
logged), never by another source, alias or donor change. No AI, no network,
no pinfo_db access: the owned catalog in the application database is read.

Donor protection (CATEGORY-02C): emag: slots are produced only when the
product's parameter_profile_state is "ready"; otherwise only src: slots.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app import product_catalog as pc
from app.catalog_constants import SOURCE
from app.models import (
    CatalogCategory,
    CatalogLinkEntry,
    CatalogSourceMapping,
    CatalogValue,
    now,
)
from app.product_models import (
    ParameterAlias,
    ProductClassification,
    ProductEvent,
    ProductParameterValue,
)

RULE_VERSION = "category-03a.1"
STATE_LABELS = {
    "present": "Kitöltve",
    "missing": "Hiányzik",
    "review": "Ellenőrzést igényel",
    "conflict": "Ellentmondás",
    "invalid": "Érvénytelen",
    "source_only": "Csak forrásban",
    "detached": "Korábbi profilból",
}
STATES = tuple(STATE_LABELS)
# Structured supplier fields compared with donor parameters (only used when
# they match; unmatched fields already live in the product data).
STRUCTURED_FIELDS = ("brand", "model", "weight", "dimensions", "packaging")
ALLOWED_CACHE_LIMIT = 20_000
MAX_SLOT_KEY = 191

# Verified deterministic conversions: unit -> (dimension, factor to base, display).
UNITS = {
    "mm": ("length", Decimal("0.001"), "mm"), "cm": ("length", Decimal("0.01"), "cm"),
    "m": ("length", Decimal("1"), "m"),
    "g": ("mass", Decimal("0.001"), "g"), "kg": ("mass", Decimal("1"), "kg"),
    "w": ("power", Decimal("1"), "W"), "kw": ("power", Decimal("1000"), "kW"),
    "ml": ("volume", Decimal("0.001"), "ml"), "cl": ("volume", Decimal("0.01"), "cl"),
    "dl": ("volume", Decimal("0.1"), "dl"), "l": ("volume", Decimal("1"), "l"),
    "wh": ("energy", Decimal("1"), "Wh"), "kwh": ("energy", Decimal("1000"), "kWh"),
    "hz": ("frequency", Decimal("1"), "Hz"), "khz": ("frequency", Decimal("1000"), "kHz"),
    "mhz": ("frequency", Decimal("1000000"), "MHz"),
    "ghz": ("frequency", Decimal("1000000000"), "GHz"),
}
NUMBER = re.compile(r"^\s*(?P<num>[+-]?\d+(?:[.,]\d+)?)\s*(?P<unit>[^\d\s][^\s]{0,11})?\s*$")
AMBIGUOUS = re.compile(r"^[+-]?\d{1,3}[.,]\d{3}$")


# --- normalization -------------------------------------------------------------


def label_key(text):
    return " ".join(re.findall(r"[0-9a-z]+", pc.fold(text)))[:160]


def unit_key(unit):
    return pc.fold(unit or "").replace(" ", "")[:24]


def tokens(key):
    return {t for t in key.split() if len(t) > 1}


def similarity(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_number(raw):
    """'2,1 kW' -> (Decimal('2.1'), 'kW', ambiguous)."""
    match = NUMBER.match(raw or "")
    if not match:
        return None
    text = match.group("num")
    try:
        number = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None
    return number, match.group("unit"), bool(AMBIGUOUS.match(text))


def format_number(number):
    text = format(number.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def convert(number, source_unit, target_unit):
    """Return (number, factor) or None when not a verified conversion."""
    s, t = UNITS.get(unit_key(source_unit)), UNITS.get(unit_key(target_unit))
    if not s or not t or s[0] != t[0]:
        return None
    factor = s[1] / t[1]
    return number * factor, factor


def slot_key_for_source(key):
    slot = f"src:{key}"
    if len(slot) <= MAX_SLOT_KEY:
        return slot
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"src:{key[:MAX_SLOT_KEY - 22]}#{digest}"


# --- catalog access (owned catalog in the application database) --------------


class Catalog:
    """Per-run cache of donor parameters and allowed values (read only)."""

    def __init__(self, db, version):
        from app.catalog_store import data_version_id

        self.db, self.version = db, version
        self.data_version = data_version_id(db, version)
        self.donors, self.allowed_cache = {}, {}

    def parameters(self, emag_category_id):
        if emag_category_id in self.donors:
            return self.donors[emag_category_id]
        category = self.db.scalar(select(CatalogCategory.id).where(
            CatalogCategory.key == f"{SOURCE}:category:{emag_category_id}"))
        result = []
        if category is not None:
            rows = self.db.scalars(
                select(CatalogLinkEntry).where(
                    CatalogLinkEntry.version_id == self.data_version,
                    CatalogLinkEntry.category_id == category,
                ).order_by(CatalogLinkEntry.display_order, CatalogLinkEntry.link_id)
            )
            seen = set()
            for row in rows:
                if row.emag_parameter_id in seen:
                    continue  # one slot per eMAG parameter and product
                seen.add(row.emag_parameter_id)
                label, unit = pc.split_header(row.name)
                result.append({
                    "link_id": row.link_id, "emag_parameter_id": row.emag_parameter_id,
                    "name": row.name, "label": label, "label_key": label_key(label),
                    "target_unit": unit, "mandatory": bool(row.is_mandatory),
                    "is_filter": bool(row.is_filter), "allow_new_value": row.allow_new_value,
                    "display_order": row.display_order or 0,
                })
        self.donors[emag_category_id] = result
        return result

    def allowed(self, link_id, candidates):
        """Match folded candidates against the allowed values: (id, text) or None."""
        cached = self.allowed_cache.get(link_id)
        if cached is None:
            query = (
                select(CatalogValue.id, CatalogValue.value_text)
                .join(CatalogSourceMapping, CatalogSourceMapping.target_id == CatalogValue.id)
                .where(CatalogSourceMapping.version_id == self.data_version,
                       CatalogSourceMapping.kind == "value",
                       CatalogSourceMapping.context_id == link_id)
                .distinct()
                .limit(ALLOWED_CACHE_LIMIT + 1)
            )
            rows = self.db.execute(query).all()
            cached = False if len(rows) > ALLOWED_CACHE_LIMIT else {}
            for value_id, text in (rows if cached is not False else []):
                cached.setdefault(pc.fold(text), (value_id, text))
            self.allowed_cache[link_id] = cached
        if cached is False:  # very large value set: exact lookup in SQL
            rows = self.db.execute(
                select(CatalogValue.id, CatalogValue.value_text)
                .join(CatalogSourceMapping, CatalogSourceMapping.target_id == CatalogValue.id)
                .where(CatalogSourceMapping.version_id == self.data_version,
                       CatalogSourceMapping.kind == "value",
                       CatalogSourceMapping.context_id == link_id,
                       CatalogValue.value_text.in_(candidates))
            ).all()
            found = {pc.fold(t): (i, t) for i, t in rows}
        else:
            found = cached
        for candidate in candidates:
            if pc.fold(candidate) in found:
                return found[pc.fold(candidate)]
        return None


def aliases_for(db, tenant_id, donor):
    """{(label_key, unit_key): alias} with tenant aliases overriding global ones."""
    rows = db.scalars(select(ParameterAlias).where(
        ParameterAlias.scope_emag_category_id == donor,
        ParameterAlias.state == "approved",
        (ParameterAlias.tenant_id == tenant_id) | ParameterAlias.tenant_id.is_(None),
    ))
    result = {}
    for alias in sorted(rows, key=lambda a: a.tenant_id is not None):
        result[(alias.label_key, unit_key(alias.unit))] = alias
    return result


def alias_ref(alias):
    return {"id": alias.id, "version": alias.version,
            "scope": "global" if alias.tenant_id is None else "tenant"}


# --- planning (pure: no writes) -----------------------------------------------


def sources_of(product):
    result = []
    for key, stored in (product.source_attributes or {}).items():
        attr = pc.expand_attribute(key, stored)
        if attr["raw"] in (None, ""):
            continue
        result.append({"key": key, "kind": "attribute", "header": attr["header"],
                       "label": attr["label"], "unit": attr["unit"], "raw": str(attr["raw"]),
                       "column": attr["column"], "run_id": attr["run_id"], "line": attr["line"],
                       "present": attr["present"]})
    from app.import_parser import FIELDS

    for name in STRUCTURED_FIELDS:
        value = (product.data or {}).get(name)
        if value in (None, ""):
            continue
        label, unit = pc.split_header(FIELDS[name][0])
        result.append({"key": f"field:{name}", "kind": "field", "header": FIELDS[name][0],
                       "label": label, "unit": unit, "raw": str(value), "column": None,
                       "run_id": product.last_run_id, "line": product.last_line, "present": True})
    for s in result:
        s["label_key"] = label_key(s["label"])
    return result


def evaluate(source, param, catalog):
    """Deterministic value of one source for one donor parameter."""
    raw = source["raw"].strip()
    target = param["target_unit"]
    out = {"value": raw, "unit": None, "value_id": None, "state": "present",
           "reasons": [], "conversion": None}
    if target:
        parsed = parse_number(raw)
        if parsed is None:
            return {**out, "value": None, "state": "invalid", "reasons": ["not_numeric"]}
        number, value_unit, ambiguous = parsed
        unit = value_unit or source["unit"]
        out["unit"] = UNITS.get(unit_key(target), (None, None, target))[2]
        if ambiguous:
            out.update(state="review", reasons=["ambiguous_number"])
        if unit is None:
            out["value"] = format_number(number)
            out["state"] = "review"
            out["reasons"].append("unit_unverified")
        elif unit_key(unit) == unit_key(target):
            out["value"] = format_number(number)
        else:
            converted = convert(number, unit, target)
            if converted is None:
                return {**out, "value": None, "state": "invalid", "reasons": ["unit_mismatch"]}
            out["value"] = format_number(converted[0])
            out["reasons"].append("unit_converted")
            out["conversion"] = {"from": UNITS[unit_key(unit)][2], "to": out["unit"],
                                 "factor": format_number(converted[1]),
                                 "raw_number": NUMBER.match(raw).group("num")}
    if param["allow_new_value"] is False and out["value"] is not None:
        candidates = [out["value"]]
        if out["unit"]:
            candidates += [f"{out['value']} {out['unit']}", f"{out['value']}{out['unit']}"]
        found = catalog.allowed(param["link_id"], candidates)
        if found is None:
            return {**out, "value": None, "value_id": None, "state": "invalid",
                    "reasons": out["reasons"] + ["value_not_allowed"]}
        out["value_id"], out["value"] = found
    return out


def public_source(source):
    return {k: source[k] for k in ("key", "kind", "header", "label", "unit", "raw",
                                   "run_id", "line", "present")}


def plan(product, ready, donor, params, aliases, catalog):
    """Slots computed from current inputs: {slot_key: row fields} (no writes)."""
    sources = sources_of(product)
    by_label = {}
    for p in params:
        by_label.setdefault(p["label_key"], []).append(p)
    params_by_id = {p["emag_parameter_id"]: p for p in params}
    certain, candidates = {}, {}  # emag_parameter_id -> [(source, origin, alias)]
    matched_sources = set()
    for s in sources if ready else []:
        alias = aliases.get((s["label_key"], unit_key(s["unit"]))) or (
            aliases.get((s["label_key"], "")) if s["unit"] is None else None)
        if alias is not None and alias.emag_parameter_id in params_by_id:
            certain.setdefault(alias.emag_parameter_id, []).append((s, "alias", alias))
            matched_sources.add(s["key"])
            continue
        exact = by_label.get(s["label_key"], [])
        if len(exact) == 1:
            certain.setdefault(exact[0]["emag_parameter_id"], []).append((s, "source", None))
            matched_sources.add(s["key"])
            continue
        scored = sorted(
            ((similarity(s["label_key"], p["label_key"]), p) for p in params),
            key=lambda x: (-x[0], x[1]["display_order"], x[1]["emag_parameter_id"]),
        )
        s["candidates"] = [p for score, p in scored if score >= 0.5][:3]
        for p in s["candidates"]:
            candidates.setdefault(p["emag_parameter_id"], []).append(s)
    slots = {}
    common = {"donor_emag_category_id": donor if ready else None, "rule_version": RULE_VERSION,
              "catalog_version_id": catalog.version.id if catalog else None}
    for p in params if ready else []:
        base = {**common, "emag_parameter_id": p["emag_parameter_id"], "catalog_link_id": p["link_id"],
                "name": p["name"], "display_order": p["display_order"], "mandatory": p["mandatory"],
                "value": None, "unit": None, "value_id": None}
        info = {"label": p["label"], "target_unit": p["target_unit"], "is_filter": p["is_filter"],
                "allow_new_value": p["allow_new_value"]}
        found = certain.get(p["emag_parameter_id"], [])
        if not found:
            loose = candidates.get(p["emag_parameter_id"], [])
            if loose:
                slots[f"emag:{p['emag_parameter_id']}"] = {
                    **base, "state": "review", "origin": "added_slot", "reason_codes": ["similar_label"],
                    "details": {**info, "sources": [], "candidates": [
                        {"source_key": s["key"], "header": s["header"], "raw": s["raw"]} for s in loose]}}
            else:
                slots[f"emag:{p['emag_parameter_id']}"] = {
                    **base, "state": "missing", "origin": "added_slot",
                    "reason_codes": ["donor_param_without_source"],
                    "details": {**info, "sources": [], "candidates": []}}
            continue
        results = [(s, origin, alias, evaluate(s, p, catalog)) for s, origin, alias in found]
        distinct = {(r["value"], r["unit"], r["value_id"]) for _, _, _, r in results}
        first_source, origin, alias, first = results[0]
        details = {**info, "sources": [public_source(s) for s, _, _, _ in results], "candidates": []}
        reasons = ["approved_alias" if origin == "alias" else "exact_label_match"]
        if alias is not None:
            details["alias"] = alias_ref(alias)
        if len(distinct) > 1:
            slots[f"emag:{p['emag_parameter_id']}"] = {
                **base, "state": "conflict", "origin": origin, "reason_codes": ["conflicting_sources"],
                "details": {**details, "candidates": [
                    {"source_key": s["key"], "value": r["value"], "unit": r["unit"], "state": r["state"]}
                    for s, _, _, r in results]}}
            continue
        state = first["state"]
        details["unit_conversion"] = first["conversion"]
        slots[f"emag:{p['emag_parameter_id']}"] = {
            **base, "state": state, "origin": origin, "reason_codes": reasons + first["reasons"],
            "value": first["value"], "unit": first["unit"], "value_id": first["value_id"],
            "details": details}
    for s in sources:
        if s["kind"] != "attribute" or s["key"] in matched_sources:
            continue
        slots[slot_key_for_source(s["key"])] = {
            **common, "donor_emag_category_id": None, "emag_parameter_id": None, "catalog_link_id": None,
            "name": s["header"], "display_order": 100_000 + (s["column"] or 0), "mandatory": False,
            "state": "source_only", "origin": "source",
            "reason_codes": [] if ready else ["donor_not_ready"],
            "value": s["raw"][:1000], "unit": s["unit"], "value_id": None,
            "details": {"label": s["label"], "target_unit": None, "is_filter": False,
                        "allow_new_value": None, "sources": [public_source(s)],
                        "candidates": [{"slot_key": f"emag:{p['emag_parameter_id']}",
                                        "emag_parameter_id": p["emag_parameter_id"], "name": p["name"],
                                        "reason": "similar_label"} for p in s.get("candidates", [])]}}
    return slots


# --- merge with stored slots (lock / overwrite / donor-change rules) ----------

COMPARED = ("emag_parameter_id", "donor_emag_category_id", "catalog_link_id", "name", "display_order",
            "state", "origin", "reason_codes", "value", "unit", "value_id", "details", "mandatory",
            "catalog_version_id", "rule_version")


def source_keys(row_or_fields):
    details = row_or_fields["details"] if isinstance(row_or_fields, dict) else row_or_fields.details
    return {s["key"] for s in (details or {}).get("sources", [])}


def view(row):
    return {k: getattr(row, k) for k in COMPARED}


def short(fields):
    return None if fields is None else {k: fields.get(k) for k in ("state", "value", "unit")}


def merge(existing, planned):
    """Decide per slot: [(slot_key, change, before, after_fields)]."""
    decisions = []
    for key in sorted(set(existing) | set(planned)):
        row, new = existing.get(key), planned.get(key)
        before = view(row) if row is not None else None
        if row is not None and row.locked:
            change = "blocked_locked"
            stored = {(o.get("key"), o.get("raw")) for o in (row.details or {}).get("sources", [])}
            incoming = {(s["key"], s["raw"]) for s in new["details"]["sources"]} if new else set()
            if incoming - stored:
                after = {**before, "reason_codes": sorted(set(before["reason_codes"]) | {"source_changed_locked"}),
                         "details": {**before["details"], "pending_source": new["details"]["sources"]}}
                change = "blocked_locked_changed" if after != before else change
                decisions.append((key, change, before, after))
            else:
                decisions.append((key, change, before, before))
            continue
        if new is None:
            if key.startswith("emag:") and before["value"] is not None or (
                    key.startswith("emag:") and before["state"] in ("conflict", "invalid")):
                after = {**before, "state": "detached", "reason_codes": ["profile_changed"]}
                decisions.append((key, "keep" if after == before else "update", before, after))
            else:
                decisions.append((key, "remove", before, None))
            continue
        if before is None:
            decisions.append((key, "create", None, new))
            continue
        after = dict(new)
        had_value = before["value"] is not None and before["state"] in ("present", "detached")
        if had_value and (after["value"], after["unit"], after["value_id"]) != (
                before["value"], before["unit"], before["value_id"]):
            if source_keys(new) and source_keys(new) <= source_keys(row):
                after["reason_codes"] = sorted(set(after["reason_codes"]) | {"source_refreshed"})
            else:
                # Another source/alias/donor must never replace a stored value.
                after.update(state="conflict", value=before["value"], unit=before["unit"],
                             value_id=before["value_id"],
                             reason_codes=sorted(set(after["reason_codes"]) | {"would_overwrite_value"}))
                after["details"] = {**after["details"], "candidates": after["details"].get("candidates", []) + [
                    {"source_key": s["key"], "value": new["value"], "unit": new["unit"]}
                    for s in new["details"]["sources"]]}
        decisions.append((key, "keep" if after == before else "update", before, after))
    return decisions


def product_inputs(db, product, catalog, alias_cache):
    c = db.get(ProductClassification, product.id)
    node = c.navigation_node_id if c else None
    donor = c.donor_emag_category_id if c else None
    state = pc.parameter_profile_state(node, donor)
    ready = state == "ready" and catalog is not None
    params = catalog.parameters(donor) if ready else []
    key = (product.tenant_id, donor)
    if ready and key not in alias_cache:
        alias_cache[key] = aliases_for(db, product.tenant_id, donor)
    return {"node": node, "donor": donor, "profile_state": state, "ready": ready,
            "params": params, "aliases": alias_cache.get(key, {})}


def stored_slots(db, product_ids):
    result = {i: {} for i in product_ids}
    for row in db.scalars(select(ProductParameterValue).where(
            ProductParameterValue.product_id.in_(list(product_ids)))):
        result[row.product_id][row.slot_key] = row
    return result


def compute(db, product, catalog, alias_cache, existing=None):
    inputs = product_inputs(db, product, catalog, alias_cache)
    planned = plan(product, inputs["ready"], inputs["donor"], inputs["params"], inputs["aliases"], catalog)
    if existing is None:
        existing = stored_slots(db, [product.id])[product.id]
    return inputs, existing, merge(existing, planned)


def summary(decisions):
    result = {"create": 0, "update": 0, "remove": 0, "keep": 0, "blocked_locked": 0}
    for _, change, _, _ in decisions:
        result["blocked_locked" if change.startswith("blocked_locked") else change] += 1
    return result


def apply(db, product, decisions, existing, actor_id=None, run_id=None, bump=True):
    """Persist decisions; returns True when the visible slots changed.

    bump=False: the caller already advanced product.revision atomically.
    """
    changed = {"create": [], "update": [], "remove": []}
    refreshed = []
    for key, change, before, after in decisions:
        if change in ("keep", "blocked_locked"):
            continue
        if change == "remove":
            db.delete(existing[key])
            changed["remove"].append(key)
            continue
        row = existing.get(key)
        if row is None:
            row = ProductParameterValue(product_id=product.id, slot_key=key, tenant_id=product.tenant_id,
                                        locked=False)
            db.add(row)
            changed["create"].append(key)
        else:
            changed["update"].append(key)
            if "source_refreshed" in after["reason_codes"] and "source_refreshed" not in before["reason_codes"]:
                refreshed.append({"slot_key": key, "before": short(before), "after": short(after)})
        for field in COMPARED:
            setattr(row, field, after[field])
        row.updated_at = now()
        row.updated_by = actor_id
    if not any(changed.values()):
        return False
    if bump:
        product.revision = (product.revision or 1) + 1
    db.add(ProductEvent(tenant_id=product.tenant_id, product_id=product.id, revision=product.revision,
                        kind="parameter_slots", run_id=None, actor_id=actor_id,
                        after={**changed, **({"job_id": run_id} if run_id else {})}))
    for item in refreshed:
        db.add(ProductEvent(tenant_id=product.tenant_id, product_id=product.id, revision=product.revision,
                            kind="parameter_source_refresh", before=item["before"],
                            after={**item["after"], "slot_key": item["slot_key"]}))
    return True


def active_catalog(db):
    from fastapi import HTTPException

    from app.catalog_store import active_version

    version = active_version(db)
    if version is None:
        raise HTTPException(503, "Nincs aktív, ellenőrzött közös katalógusverzió; paraméterhely nem képezhető.")
    return Catalog(db, version)


def slot_dto(row):
    details = row.details or {}
    return {
        "slot_key": row.slot_key, "emag_parameter_id": row.emag_parameter_id, "name": row.name,
        "label": details.get("label"), "target_unit": details.get("target_unit"),
        "mandatory": row.mandatory, "is_filter": details.get("is_filter", False),
        "allow_new_value": details.get("allow_new_value"),
        "state": row.state, "state_label": STATE_LABELS[row.state], "origin": row.origin,
        "reason_codes": row.reason_codes or [], "value": row.value, "unit": row.unit,
        "value_id": row.value_id, "unit_conversion": details.get("unit_conversion"),
        "sources": details.get("sources", []), "candidates": details.get("candidates", []),
        "alias": details.get("alias"), "locked": row.locked,
        "donor_emag_category_id": row.donor_emag_category_id,
        "catalog_version_id": row.catalog_version_id, "rule_version": row.rule_version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class Row:
    """Unsaved slot for previews (same attribute surface as the model)."""

    def __init__(self, key, fields, locked=False):
        self.slot_key, self.locked, self.updated_by, self.updated_at = key, locked, None, None
        for field in COMPARED:
            setattr(self, field, fields[field])


def ordered(rows):
    return sorted(rows, key=lambda r: (r.slot_key.startswith("src:") or r.state == "detached",
                                       r.display_order, r.slot_key))
