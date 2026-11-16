"""CATEGORY-02A product catalog services: lossless source data and classification.

Principles (issue #16):
* The customer's own (supplier/webshop) category is stored verbatim and never
  rewritten; the internal classification is a separate record.
* The internal target is the approved fixed navigation (the same product
  categories app.fixed_navigation treats as bindable leaves); eMAG categories
  are only parameter donors (reviewed_parameter_bindings.json).
* Supplier values always win: automation never overwrites them, and manual
  decisions are locked, audited and revisioned.
* Only an approved tenant category map, or a method whose measured precision
  reaches the configured threshold (default 98 %), classifies automatically.
  No method is calibrated yet, so every other case needs review.
"""

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update

from app.import_models import SupplierProduct
from app.models import now
from app.product_models import (
    CategoryMap,
    ProductClassification,
    ProductEvent,
    ProductSourceCategory,
)

RULE_VERSION = "category-02a.1"
AUTO = "auto_classified"
REVIEW = "needs_review"
STATUS_LABELS = {AUTO: "Automatikusan besorolt", REVIEW: "Ellenőrzést igényel"}
# Measured precision per automatic method (0..1). Empty until a calibration
# against a labelled gold set is reviewed; uncalibrated methods never auto-apply.
CALIBRATED_PRECISION: dict[str, float] = {}
DEFAULT_AUTO_THRESHOLD = 0.98
PENDING = "pending_review"
RUN_PRODUCT_LIMIT = 50_000
SEPARATORS = re.compile(r"\s*(?:>|»|/|\||\\)\s*")
UNIT = re.compile(r"^(?P<label>.*?)\s*[\(\[]\s*(?P<unit>[^()\[\]]{1,24}?)\s*[\)\]]\s*$")


# --- reference: internal categories and donors (offline, versioned JSON) ----


@lru_cache(maxsize=1)
def internal_categories():
    """Bindable product categories of the approved fixed tree with their donors."""
    from app.curated_taxonomy import apply_taxonomy
    from app.parameter_profiles import reviewed_bindings
    from app.web_navigation import Navigation, navigation

    base = apply_taxonomy(navigation())
    fixed = {k: n for k, n in base.nodes.items() if n.get("taxonomy_version")}
    nav = Navigation(
        {
            **base.data,
            "nodes": list(fixed.values()),
            "retired_nodes": base.curated_spec.get("retired_nodes", []),
        }
    )
    rules = {r["node_id"]: r for r in reviewed_bindings()["rules"]}
    review = donor_review()
    result = {}
    for key, node in fixed.items():
        if node["kind"] != "category" or node.get("structural_only"):
            continue
        result[key] = {
            "id": key,
            "name": node["name"],
            "path": [fixed[p]["name"] for p in nav.path(key)],
            "path_ids": nav.path(key),
            "donors": [
                {
                    "emag_category_id": d["emag_category_id"],
                    "name": d["expected_name"],
                    "review_state": review.get((key, d["emag_category_id"]), "reviewed"),
                }
                for d in rules.get(key, {}).get("donors", [])
            ],
        }
    unknown = set(review) - {(k, d["emag_category_id"]) for k, n in result.items() for d in n["donors"]}
    if unknown:
        raise ValueError(f"donor_review.json names donors outside the bindable tree: {sorted(unknown)}")
    return result


@lru_cache(maxsize=1)
def donor_review():
    """CATEGORY-02C: donors whose parameter scope still awaits human approval."""
    path = Path(__file__).resolve().parents[1] / "reference_data/donor_review.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    states = set(data["states"])
    result = {}
    for entry in data["entries"]:
        if entry["state"] not in states:
            raise ValueError(f"Unknown donor review state: {entry['state']}")
        result[(entry["node_id"], entry["emag_category_id"])] = entry["state"]
    return result


def donor_state(node_id, donor):
    node = internal_category(node_id)
    for d in node["donors"] if node else []:
        if d["emag_category_id"] == donor:
            return d["review_state"]
    return None


def parameter_profile_state(node_id, donor):
    """Gate for any (future) automatic parameter enrichment of one product.

    ready          -> the donor is chosen, belongs to the node and is reviewed
    choice_required-> several profiles, none chosen explicitly
    pending_review -> the donor (or the node's only donor) awaits approval
    none           -> no classification target or no donor at all
    Only "ready" may ever feed automatic parameter enrichment.
    """
    node = internal_category(node_id)
    if node is None or not node["donors"]:
        return "none"
    if donor is None:
        if len(node["donors"]) > 1:
            return "choice_required"
        return "pending_review" if node["donors"][0]["review_state"] == PENDING else "none"
    state = donor_state(node_id, donor)
    if state is None:
        return "none"
    return "ready" if state == "reviewed" else "pending_review"


def internal_category(node_id):
    return internal_categories().get(node_id) if node_id else None


def default_donor(node_id):
    """The donor an automatic decision may store: the only, reviewed one."""
    node = internal_category(node_id)
    if node and len(node["donors"]) == 1 and node["donors"][0]["review_state"] != PENDING:
        return node["donors"][0]["emag_category_id"]
    return None


def donor_reasons(node_id, donor):
    state = parameter_profile_state(node_id, donor)
    if state == "choice_required":
        return ["parameter_profile_choice_required"]
    if state == "pending_review":
        return ["parameter_profile_pending_review"]
    return []


def validate_target(node_id, donor):
    """Raise 422 unless node is a bindable internal category and donor belongs to it."""
    node = internal_category(node_id)
    if node is None:
        raise HTTPException(422, "Ismeretlen vagy nem besorolható belső kategória.")
    allowed = {d["emag_category_id"] for d in node["donors"]}
    if donor is not None and donor not in allowed:
        raise HTTPException(422, "A paraméterprofil nem tartozik a kiválasztott kategóriához.")
    return donor if donor is not None else default_donor(node_id)


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().casefold()


@lru_cache(maxsize=1)
def names_index():
    index = {}
    for key, node in internal_categories().items():
        index.setdefault(fold(node["name"]), []).append(key)
    return index


# --- search ------------------------------------------------------------------

SEARCH_FIELDS = ("name", "sku", "gtin")
SEARCH_MAX_TERMS = 5
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def search_text(data):
    """Folded, tab-separated name/SKU/GTIN; terms never contain a tab."""
    parts = [fold(CONTROL.sub(" ", str(data.get(k) or ""))) for k in SEARCH_FIELDS]
    return "\t".join(parts)[:1024]


def search_terms(q):
    """Whitespace-separated terms, folded; each must match (AND), any field."""
    terms = [t for t in fold(CONTROL.sub(" ", q or "")).split(" ") if t]
    return terms[:SEARCH_MAX_TERMS]


# --- own/source categories -----------------------------------------------


def path_segments(text):
    return [s for s in SEPARATORS.split((text or "").strip()) if s]


def path_key(text):
    return hashlib.sha256(" > ".join(fold(s) for s in path_segments(text)).encode()).hexdigest()


def source_category_id(db, cache, tenant_id, supplier_id, text):
    """Find or create the own category record; text is kept verbatim."""
    text = (text or "").strip()
    if not text:
        return None
    key = path_key(text)
    marker = (tenant_id, supplier_id, key)
    if marker in cache:
        return cache[marker]
    row = db.scalar(
        select(ProductSourceCategory).where(
            ProductSourceCategory.tenant_id == tenant_id,
            ProductSourceCategory.supplier_id == supplier_id,
            ProductSourceCategory.origin == "supplier",
            ProductSourceCategory.path_key == key,
        )
    )
    if row is None:
        row = ProductSourceCategory(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            origin="supplier",
            path_key=key,
            path_text=text[:1000],
        )
        db.add(row)
        db.flush()
    cache[marker] = row.id
    return row.id


# --- lossless source attributes ---------------------------------------------


def split_header(header):
    """'Teljesítmény (W)' -> ('Teljesítmény', 'W'); purely syntactic."""
    text = (header or "").strip()
    match = UNIT.match(text)
    if match and match.group("label"):
        return match.group("label").strip(), match.group("unit").strip()
    return text, None


def source_attributes(headers, raw, mapped, run_id, line):
    """Every column not mapped to an internal field, keyed by its header.

    Stored compactly: {key: {raw, column, run_id, line, present[, header]}};
    label and unit are derived from the header (expand_attribute), so they are
    not duplicated in the database.
    """
    result, seen = {}, {}
    for index, header in enumerate(headers):
        if index in mapped:
            continue
        name = (str(header) if header is not None else "").strip() or f"Oszlop {index + 1}"
        seen[name] = seen.get(name, 0) + 1
        key = name if seen[name] == 1 else f"{name} #{seen[name]}"
        value = raw[index] if index < len(raw) else ""
        entry = {"raw": value if value != "" else None, "column": index,
                 "run_id": run_id, "line": line, "present": True}
        if key != name:
            entry["header"] = name
        result[key] = entry
    return result


def expand_attribute(key, value):
    """API view of one stored source attribute (adds header, label, unit)."""
    header = value.get("header", key)
    label, unit = split_header(header)
    return {"key": key, "header": header, "label": label, "unit": unit, **{
        k: value.get(k) for k in ("raw", "column", "run_id", "line", "present")}}


def merge_attributes(previous, incoming, full_feed):
    """Return (merged, delta). Columns missing from this file are retained."""
    previous = dict(previous or {})
    merged, delta = {}, {}
    for key, old in previous.items():
        if key not in incoming:
            merged[key] = {**old, "present": False}
            if old.get("present", True):
                delta[key] = {"before": old.get("raw"), "after": None, "column_present": False}
    for key, new in incoming.items():
        old = previous.get(key)
        if new["raw"] is None and not full_feed and old is not None:
            # Partial feeds never erase a stored value with an empty cell.
            merged[key] = {**old, "present": True, "run_id": new["run_id"], "line": new["line"]}
            continue
        merged[key] = new
        if old is None or old.get("raw") != new["raw"]:
            delta[key] = {"before": old.get("raw") if old else None, "after": new["raw"]}
    return merged, delta


# --- classification ---------------------------------------------------------


def auto_threshold(db):
    from app.system_config import config

    return float(config(db, "classification")["auto_threshold"])


def method_is_automatic(method, threshold):
    precision = CALIBRATED_PRECISION.get(method)
    return precision is not None and precision >= threshold


def suggestions(path_text):
    """Exact (accent/case-insensitive) name equality, leaf segment first."""
    found = []
    for segment in reversed(path_segments(path_text)):
        for key in names_index().get(fold(segment), []):
            if key not in found:
                found.append(key)
        if found:
            break
    return found


def alternative(key):
    node = internal_categories()[key]
    return {"navigation_node_id": key, "path": node["path"], "score": None}


def decide(db, product, maps, threshold, source_text):
    """The automatic decision for an unlocked product (no writes)."""
    category_map = maps.get(product.source_category_id) if product.source_category_id else None
    if category_map is not None and category_map.state == "approved":
        donor = category_map.donor_emag_category_id or default_donor(category_map.navigation_node_id)
        reasons = ["approved_category_map"]
        node = internal_category(category_map.navigation_node_id)
        if node is None:
            reasons = ["category_map_target_unavailable"]
            return dict(status=REVIEW, origin="category_map", method="category_map",
                        navigation_node_id=None, donor_emag_category_id=None,
                        reason_codes=reasons, alternatives=[], confidence=None,
                        map_revision=category_map.revision)
        reasons += donor_reasons(category_map.navigation_node_id, donor)
        return dict(status=AUTO, origin="category_map", method="category_map",
                    navigation_node_id=category_map.navigation_node_id,
                    donor_emag_category_id=donor, reason_codes=reasons,
                    alternatives=[], confidence=None, map_revision=category_map.revision)
    if not product.source_category_id:
        return dict(status=REVIEW, origin="none", method=None, navigation_node_id=None,
                    donor_emag_category_id=None, reason_codes=["no_source_category"],
                    alternatives=[], confidence=None, map_revision=None)
    candidates = suggestions(source_text)
    reasons = []
    if category_map is not None and category_map.state == "rejected":
        reasons.append("category_map_rejected")
    if not candidates:
        reasons.append("no_candidate")
    elif len(candidates) > 1:
        reasons.append("ambiguous_candidates")
    elif method_is_automatic("exact_name_match", threshold):
        key = candidates[0]
        return dict(status=AUTO, origin="suggestion", method="exact_name_match",
                    navigation_node_id=key, donor_emag_category_id=default_donor(key),
                    reason_codes=["calibrated_rule", *donor_reasons(key, default_donor(key))],
                    alternatives=[alternative(k) for k in candidates[:3]],
                    confidence=CALIBRATED_PRECISION["exact_name_match"], map_revision=None)
    else:
        reasons.append("uncalibrated_suggestion")
    return dict(status=REVIEW, origin="suggestion" if candidates else "none",
                method="exact_name_match" if candidates else None,
                navigation_node_id=None, donor_emag_category_id=None,
                reason_codes=reasons, alternatives=[alternative(k) for k in candidates[:3]],
                confidence=None,
                map_revision=category_map.revision if category_map is not None else None)


def snapshot(c):
    if c is None:
        return None
    return {
        "status": c.status,
        "origin": c.origin,
        "navigation_node_id": c.navigation_node_id,
        "donor_emag_category_id": c.donor_emag_category_id,
        "locked": c.locked,
    }


def classify(db, product, maps, threshold, source_text, run_id=None, record_event=True):
    """Apply the automatic decision unless the classification is locked.

    Returns True when the visible classification changed (revision bumped).
    """
    current = db.get(ProductClassification, product.id)
    if current is not None and current.locked:
        return False
    decision = decide(db, product, maps, threshold, source_text)
    if current is None:
        db.add(ProductClassification(product_id=product.id, tenant_id=product.tenant_id,
                                     rule_version=RULE_VERSION, decided_at=now(), **decision))
        return False
    before = snapshot(current)
    for key, value in decision.items():
        setattr(current, key, value)
    current.rule_version = RULE_VERSION
    after = snapshot(current)
    if before == after:
        return False
    current.decided_at = now()
    current.decided_by = None
    product.revision = (product.revision or 1) + 1
    if record_event:
        db.add(ProductEvent(tenant_id=product.tenant_id, product_id=product.id,
                            revision=product.revision, kind="classification_auto",
                            run_id=run_id, before=before, after=after))
    return True


def bump_revision(db, product, expected):
    """Atomic optimistic-concurrency check; 409 when the client is stale."""
    result = db.execute(
        update(SupplierProduct)
        .where(SupplierProduct.id == product.id, SupplierProduct.revision == expected)
        .values(revision=SupplierProduct.revision + 1)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "A terméket időközben módosították. Töltsd be újra a friss állapotot.")
    db.refresh(product)
    return product.revision


def maps_for(db, tenant_id):
    return {m.source_category_id: m for m in db.scalars(select(CategoryMap).where(CategoryMap.tenant_id == tenant_id))}
