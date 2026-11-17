"""KNOWLEDGE-01: the self-learning central product knowledge base.

Built on the RC-03 reference store and the tenants' imported products; it links and
consolidates those records, it is not a second product store.

* Sources: every permitted reference source (reference_product_sources: approved_enrichment,
  enrichment_enabled, contribution "automatic") and one source per tenant (kind
  "tenant_import", created automatically under the owner policy; an administrator can
  restrict it). A source that loses its permission stops contributing on the next rebuild.
* Identity: valid GTIN > brand + manufacturer part number > brand + name (folded). A record
  belongs to one cluster; a record whose identifiers point to several clusters is linked to
  the strongest match and a merge candidate is logged - clusters are never merged
  automatically.
* Observations: only shareable product knowledge (brand and product parameters); never
  prices, stock, customer-group data, the store SKU or integration identifiers. Parameters
  are keyed by eMAG parameter when an approved eMAG-UNAS mapping exists ("learning from
  mappings"), units are normalised (mm/cm/m, g/kg, ml/l).
* Consolidation: confidence = source trust x identity confidence, combined over distinct
  sources and capped below 1. Agreement of several sources only raises confidence; a value
  becomes "verified" only through a human decision - a tenant user's approved correction
  (locked user value) or an administrator decision. Differing values open a conflict.
* Every change is written to knowledge_events.

CLI: python -m app.knowledge rebuild [--source-id N] [--tenant-id N]
"""

import argparse
import json
import logging
import re
import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge_models import (
    KnowledgeConflict,
    KnowledgeEvent,
    KnowledgeIdentity,
    KnowledgeLink,
    KnowledgeMerge,
    KnowledgeObservation,
    KnowledgeProduct,
    KnowledgeSourceRelation,
    KnowledgeText,
    KnowledgeValue,
)
from app.models import now
from app.reference_products import DEFAULT_USAGE_BASIS, fold, gtin_issues
from app.unas_models import (
    ParameterMapping,
    ReferenceProduct,
    ReferenceProductAttribute,
    ReferenceProductIdentifier,
    ReferenceProductSource,
    UnasFieldDefinition,
    UnasParameterDefinition,
)
from app.worker import celery
from app import knowledge_signals as signals

log = logging.getLogger(__name__)
LINK_CONFIDENCE = {"gtin": Decimal("1"), "mpn": Decimal("0.9"), "brand_name": Decimal("0.6"),
                   "new": Decimal("1"), "manual": Decimal("1")}
DEFAULT_TRUST = {"unas_export": Decimal("0.6"), "tenant_import": Decimal("0.5")}
APPROVED_TRUST = Decimal("0.9")
CAP = Decimal("0.95")  # agreement alone never reaches certainty
CANONICAL_UNITS = {
    "mm": ("cm", Decimal("0.1")), "cm": ("cm", Decimal("1")), "m": ("cm", Decimal("100")),
    "g": ("kg", Decimal("0.001")), "kg": ("kg", Decimal("1")),
    "ml": ("l", Decimal("0.001")), "l": ("l", Decimal("1")),
}
LABEL_UNIT = re.compile(r"\(\s*([A-Za-z]{1,4})\s*\)\s*$")


# --- normalisation -------------------------------------------------------------------------


def label_unit(label):
    match = LABEL_UNIT.search(label or "")
    return match.group(1) if match else None


def normalize(raw, unit=None):
    """(value_norm, display): numbers in a canonical unit, text folded."""
    text = str(raw).strip()
    unit = (unit or "").strip() or None
    try:
        number = Decimal(text.replace(" ", "").replace(" ", "").replace(",", "."))
        if not number.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        return "txt:" + fold(text), text
    canonical = CANONICAL_UNITS.get((unit or "").casefold())
    if canonical:
        unit_name, factor = canonical
        number = number * factor
    else:
        unit_name = unit
    value = format(number.normalize(), "f")
    return f"num:{value}:{unit_name or ''}", f"{value} {unit_name}".strip()


def combine(confidences, cap=CAP):
    """1 - prod(1 - c) over independent sources, capped below certainty."""
    remaining = Decimal("1")
    for c in confidences:
        remaining *= Decimal("1") - Decimal(c)
    return min(Decimal(cap), (Decimal("1") - remaining)).quantize(Decimal("0.0001"))


class Context:
    """KNOWLEDGE-02 scoring context: settings and source families, loaded once per run."""

    def __init__(self, db):
        self.cfg = signals.settings(db)
        self.cap = signals.dec(self.cfg["confidence_cap"])
        self.family = signals.families(db)

    def trust(self, source, origin):
        if origin == "approved_correction":
            return signals.dec(self.cfg["trust_approved_correction"])
        if source.trust_level is not None:
            return source.trust_level
        key = "trust_tenant" if source.kind == "tenant_import" else "trust_reference"
        return signals.dec(self.cfg[key])


# --- sources ---------------------------------------------------------------------------------


def permitted(source):
    return (source.usage_status == "approved_enrichment" and source.enrichment_enabled
            and source.contribution == "automatic")


def tenant_source(db, tenant_id):
    key = f"tenant:{tenant_id}"
    source = db.scalar(select(ReferenceProductSource).where(ReferenceProductSource.key == key))
    if source is None:
        source = ReferenceProductSource(
            key=key, name=f"Ügyfélfeltöltések – {tenant_id}", kind="tenant_import",
            tenant_id=tenant_id, usage_status="approved_enrichment",
            usage_basis=DEFAULT_USAGE_BASIS, enrichment_enabled=True, contribution="automatic",
            excluded_columns=["prices", "stock", "supplier_sku", "customer_groups"])
        db.add(source)
        db.flush()
    return source


def trust(source):
    """KNOWLEDGE-01 defaults; KNOWLEDGE-02 scoring uses Context.trust (configurable)."""
    return source.trust_level if source.trust_level is not None else DEFAULT_TRUST.get(
        source.kind, Decimal("0.5"))


def event(db, kind, product_id=None, value_id=None, link_id=None, actor_id=None, **details):
    db.add(KnowledgeEvent(kind=kind, knowledge_product_id=product_id, value_id=value_id,
                          link_id=link_id, actor_id=actor_id, details=details))


# --- identity --------------------------------------------------------------------------------


def identity_keys(gtins=(), mpn=None, brand=None, name=None):
    """Ordered identity keys of a record; only valid GTINs identify a product."""
    keys = [("gtin", g) for g in dict.fromkeys(gtins) if g and not gtin_issues(g)]
    if mpn and brand:
        keys.append(("mpn", f"{fold(brand)}|{fold(mpn)}"))
    if brand and name:
        keys.append(("brand_name", f"{fold(brand)}|{fold(name)}"[:255]))
    return keys


def variant_conflict(db, product_id, variant):
    """Does the cluster hold a different value for a variant attribute (size, colour...)?"""
    if not variant:
        return False
    for key, norm in variant.items():
        # Current claims, not consolidated values: those are only written at the end of a
        # rebuild batch, while records of the same batch are being linked.
        claims = set(db.scalars(select(KnowledgeObservation.value_norm).where(
            KnowledgeObservation.knowledge_product_id == product_id,
            KnowledgeObservation.attribute_key == key,
            KnowledgeObservation.current.is_(True))))
        if claims and norm not in claims:
            return True
    return False


def link_member(db, member_kind, member_id, source, tenant_id, keys, display_name, brand,
                variant=None):
    link = db.scalar(select(KnowledgeLink).where(KnowledgeLink.member_kind == member_kind,
                                                KnowledgeLink.member_id == member_id))
    if link is not None and link.decided_by is not None:
        return link  # an administrator placed this record; never re-link it automatically
    found = []
    for kind, value in keys:
        hit = db.scalar(select(KnowledgeIdentity.knowledge_product_id).where(
            KnowledgeIdentity.kind == kind, KnowledgeIdentity.value == value))
        if hit is not None and kind == "brand_name" and db.scalar(
                select(KnowledgeLink.id).where(
                    KnowledgeLink.knowledge_product_id == hit,
                    KnowledgeLink.source_id == source.id,
                    (KnowledgeLink.member_kind != member_kind) |
                    (KnowledgeLink.member_id != member_id)).limit(1)):
            # One source lists a product once: the same brand+name twice in one source is a
            # variant (size, colour...), not the same product. Only a GTIN may say so.
            continue
        if hit is not None and kind == "brand_name" and variant_conflict(db, hit, variant):
            # KNOWLEDGE-02: same brand+name but a different size/colour/... is a variant.
            event(db, "variant_candidate", hit, member=f"{member_kind}:{member_id}")
            continue
        if hit is not None:
            found.append((kind, hit))
    clusters = list(dict.fromkeys(c for _, c in found))
    if found and link is not None and found[0][1] == link.knowledge_product_id:
        # Finding its own cluster again (e.g. the record that founded it) is no new evidence.
        method, product_id = link.method, link.knowledge_product_id
    elif found:
        method, product_id = found[0]
    elif link is not None:
        method, product_id = link.method, link.knowledge_product_id
    else:
        product = KnowledgeProduct(status="active", display_name=display_name, brand=brand)
        db.add(product)
        db.flush()
        method, product_id = "new", product.id
        event(db, "product_created", product.id, member=f"{member_kind}:{member_id}")
    if len(clusters) > 1:
        event(db, "merge_candidate", product_id, clusters=clusters,
              member=f"{member_kind}:{member_id}")
    for kind, value in keys:
        exists = db.scalar(select(KnowledgeIdentity.id).where(KnowledgeIdentity.kind == kind,
                                                              KnowledgeIdentity.value == value))
        if exists is None:
            db.add(KnowledgeIdentity(knowledge_product_id=product_id, kind=kind, value=value))
    confidence = LINK_CONFIDENCE[method]
    if link is None:
        link = KnowledgeLink(member_kind=member_kind, member_id=member_id, source_id=source.id,
                             tenant_id=tenant_id, knowledge_product_id=product_id,
                             method=method, confidence=confidence)
        db.add(link)
        db.flush()
        event(db, "linked", product_id, link_id=link.id, method=method,
              member=f"{member_kind}:{member_id}")
    elif link.knowledge_product_id != product_id or link.method != method:
        before = link.knowledge_product_id
        link.knowledge_product_id, link.method, link.confidence = product_id, method, confidence
        link.updated_at = now()
        for obs in db.scalars(select(KnowledgeObservation).where(
                KnowledgeObservation.link_id == link.id)):
            obs.knowledge_product_id = product_id
        event(db, "relinked", product_id, link_id=link.id, before=before, method=method)
    product = db.get(KnowledgeProduct, product_id)
    product.display_name = product.display_name or display_name
    product.brand = product.brand or brand
    return link


# --- observations ----------------------------------------------------------------------------


def mapping_index(db):
    """Approved eMAG-UNAS mappings: UNAS parameter id -> (emag_parameter_id, eMAG name)."""
    index = {}
    for m in db.scalars(select(ParameterMapping).where(ParameterMapping.status == "approved",
                                                       ParameterMapping.unas_parameter_id
                                                       .is_not(None))):
        index.setdefault(m.unas_parameter_id, (m.emag_parameter_id, m.emag_parameter_name))
    return index


def reference_items(db, product, mappings):
    items = []
    if product.brand:
        items.append(("brand", "Márka", product.brand, None, "reference"))
    rows = db.execute(
        select(ReferenceProductAttribute, UnasParameterDefinition)
        .join(UnasParameterDefinition,
              UnasParameterDefinition.id == ReferenceProductAttribute.parameter_id)
        .join(UnasFieldDefinition, UnasFieldDefinition.id == UnasParameterDefinition.field_id)
        .where(ReferenceProductAttribute.product_id == product.id,
               UnasFieldDefinition.shareable.is_(True)))
    for attribute, parameter in rows:
        if attribute.name == "Márka" and not attribute.group_name:
            continue  # already the brand
        mapped = mappings.get(parameter.id)
        if mapped:
            key, label = f"emag:{mapped[0]}", mapped[1]
        else:
            group = f"{fold(parameter.group_name)}/" if parameter.group_name else ""
            key, label = f"unas:{group}{fold(parameter.name)}"[:191], parameter.name
        items.append((key, label, attribute.value_text, attribute.unit, "reference"))
    return items


def supplier_items(db, product):
    from app.product_models import ProductParameterValue

    items = []
    brand = (product.data or {}).get("brand")
    if brand:
        items.append(("brand", "Márka", str(brand), None, "tenant"))
    for p in db.scalars(select(ProductParameterValue).where(
            ProductParameterValue.product_id == product.id,
            ProductParameterValue.state == "present",
            ProductParameterValue.emag_parameter_id.is_not(None),
            ProductParameterValue.value.is_not(None))):
        approved = p.origin == "user" and p.locked
        items.append((f"emag:{p.emag_parameter_id}", p.name, p.value,
                      p.unit or label_unit(p.name),
                      "approved_correction" if approved else "tenant"))
    return items


def sync_observations(db, link, source, items, ctx=None):
    """Keep exactly the current claims of one record; history is kept (current=False).

    KNOWLEDGE-02: confidence from the configurable trust; the identity confidence is kept for
    recomputation; values with personal-data patterns are held back until reviewed."""
    current = {o.attribute_key: o for o in db.scalars(select(KnowledgeObservation).where(
        KnowledgeObservation.link_id == link.id, KnowledgeObservation.current.is_(True)))}
    touched = set()
    seen = set()
    for key, label, raw, unit, origin in items:
        if key in seen or raw is None or str(raw).strip() == "":
            continue
        seen.add(key)
        norm, _ = normalize(raw, unit)
        if ctx is not None:
            base = ctx.trust(source, origin)
        else:
            base = APPROVED_TRUST if origin == "approved_correction" else trust(source)
        confidence = (Decimal(base) * Decimal(link.confidence)).quantize(Decimal("0.0001"))
        old = current.get(key)
        if old and old.value_norm == norm and old.origin == origin and \
                old.confidence == confidence:
            continue
        if old:
            old.current, old.superseded_at = False, now()
        db.add(KnowledgeObservation(
            knowledge_product_id=link.knowledge_product_id, link_id=link.id,
            source_id=source.id, attribute_key=key, attribute_label=label[:255],
            value_raw=str(raw)[:1000], value_norm=norm[:1000], unit=unit, origin=origin,
            confidence=confidence, current=True, identity_confidence=link.confidence,
            pii_flags=signals.pii_flags(str(raw)) or None))
        touched.add(key)
    for key, old in current.items():
        if key not in seen:
            old.current, old.superseded_at = False, now()
            touched.add(key)
    return touched


def retire_link(db, link):
    """A record whose source lost its permission no longer contributes."""
    touched = set()
    for obs in db.scalars(select(KnowledgeObservation).where(
            KnowledgeObservation.link_id == link.id, KnowledgeObservation.current.is_(True))):
        obs.current, obs.superseded_at = False, now()
        touched.add(obs.attribute_key)
    if touched:
        event(db, "source_withdrawn", link.knowledge_product_id, link_id=link.id,
              source_id=link.source_id)
    return touched


# --- consolidation ---------------------------------------------------------------------------


def groups_of(observations, rejected, ctx=None):
    """Group current claims by normalised value. KNOWLEDGE-02: sources of one family (lineage
    group or suspected/confirmed copying) count once; personal-data holds are skipped."""
    family = ctx.family if ctx else {}
    cap = ctx.cap if ctx else CAP
    groups = {}
    for o in observations:
        if o.value_norm in rejected or signals.pii_held(o.pii_flags, o.pii_reviewed_by):
            continue
        g = groups.setdefault(o.value_norm, {"value_norm": o.value_norm, "display": None,
                                             "unit": None, "by_source": {}, "by_family": {},
                                             "approved": False, "observations": 0})
        g["observations"] += 1
        g["by_source"][o.source_id] = max(g["by_source"].get(o.source_id, 0), o.confidence)
        fam = family.get(o.source_id, o.source_id)
        g["by_family"][fam] = max(g["by_family"].get(fam, 0), o.confidence)
        g["approved"] |= o.origin == "approved_correction"
        g["display"] = g["display"] or normalize(o.value_raw, o.unit)[1]
    for g in groups.values():
        g["confidence"] = combine(g["by_family"].values(), cap)
        g["sources"] = len(g["by_source"])
        g["independent"] = len(g["by_family"])
    return sorted(groups.values(), key=lambda g: (g["approved"], g["confidence"],
                                                   g["sources"]), reverse=True)


def open_conflict(db, value, kind, groups):
    candidates = [{"value_norm": g["value_norm"], "display": g["display"],
                   "sources": g["sources"], "confidence": str(g["confidence"]),
                   "approved": g["approved"]} for g in groups]
    conflict = db.scalar(select(KnowledgeConflict).where(KnowledgeConflict.value_id == value.id,
                                                         KnowledgeConflict.state == "open"))
    if conflict is None:
        db.add(KnowledgeConflict(value_id=value.id, knowledge_product_id=value.knowledge_product_id,
                                 attribute_key=value.attribute_key, kind=kind,
                                 candidates=candidates, state="open"))
        event(db, "conflict_opened", value.knowledge_product_id, value_id=value.id,
              conflict_kind=kind,
              candidates=[c["value_norm"] for c in candidates])
    else:
        conflict.kind, conflict.candidates = kind, candidates


def close_conflicts(db, value, resolution, actor_id=None, reason=None):
    for conflict in db.scalars(select(KnowledgeConflict).where(
            KnowledgeConflict.value_id == value.id, KnowledgeConflict.state == "open")):
        conflict.state, conflict.resolution = "resolved", resolution
        conflict.resolved_by, conflict.resolved_at, conflict.reason = actor_id, now(), reason
        event(db, "conflict_resolved", value.knowledge_product_id, value_id=value.id,
              actor_id=actor_id, resolution=resolution, automatic=actor_id is None)


def consolidate(db, product_id, key, ctx=None):
    observations = list(db.scalars(select(KnowledgeObservation).where(
        KnowledgeObservation.knowledge_product_id == product_id,
        KnowledgeObservation.attribute_key == key, KnowledgeObservation.current.is_(True))))
    value = db.scalar(select(KnowledgeValue).where(KnowledgeValue.knowledge_product_id ==
                                                   product_id,
                                                   KnowledgeValue.attribute_key == key))
    if value is None:
        if not observations:
            return None
        value = KnowledgeValue(knowledge_product_id=product_id, attribute_key=key,
                               attribute_label=observations[0].attribute_label,
                               status="candidate", confidence=Decimal("0"),
                               support_sources=0, observations=0, rejected_values=[])
        db.add(value)
        db.flush()
    before = (value.value_norm, value.status, value.confidence)
    ctx = ctx or Context(db)
    groups = groups_of(observations, set(value.rejected_values or []), ctx)
    value.observations = len(observations)
    admin_verified = value.status == "verified" and value.verification_basis == "admin_decision"
    approved = [g for g in groups if g["approved"]]
    if admin_verified:
        best = next((g for g in groups if g["value_norm"] == value.value_norm), None)
        value.support_sources = best["sources"] if best else 0
        challengers = [g for g in groups if g["value_norm"] != value.value_norm]
        if challengers:
            open_conflict(db, value, "verified_challenged", ([best] if best else []) + challengers)
        else:
            close_conflicts(db, value, value.value_norm)
    elif len(approved) == 1:
        best = approved[0]
        value.value_norm, value.value_display, value.status = best["value_norm"], \
            best["display"], "verified"
        value.verification_basis, value.verified_by, value.verified_at = \
            "approved_correction", None, value.verified_at or now()
        value.confidence, value.support_sources = best["confidence"], best["sources"]
        others = [g for g in groups if g is not best]
        if others:
            open_conflict(db, value, "verified_challenged", [best] + others)
        else:
            close_conflicts(db, value, best["value_norm"])
    elif not groups:
        value.value_norm = value.value_display = None
        value.status, value.confidence, value.support_sources = "candidate", Decimal("0"), 0
        value.verification_basis = None
        close_conflicts(db, value, "no_current_observation")
    elif len(groups) == 1 and not approved:
        best = groups[0]
        value.value_norm, value.value_display = best["value_norm"], best["display"]
        value.status, value.confidence = "candidate", best["confidence"]
        value.support_sources, value.verification_basis = best["sources"], None
        close_conflicts(db, value, best["value_norm"])
    else:
        best = groups[0]
        value.value_norm, value.value_display = best["value_norm"], best["display"]
        value.status, value.verification_basis = "conflict", None
        # A contested value is reported with halved confidence and never reused as a fact.
        value.confidence = (best["confidence"] / 2).quantize(Decimal("0.0001"))
        value.support_sources = best["sources"]
        open_conflict(db, value, "values_differ", groups)
    current_group = next((g for g in groups if g["value_norm"] == value.value_norm), None)
    value.independent_sources = current_group["independent"] if current_group else 0
    value.updated_at = now()
    if (value.value_norm, value.status, value.confidence) != before:
        event(db, "value_changed", product_id, value_id=value.id, key=key,
              before={"value": before[0], "status": before[1], "confidence": str(before[2])},
              after={"value": value.value_norm, "status": value.status,
                     "confidence": str(value.confidence)})
    return value


# --- rebuild ---------------------------------------------------------------------------------


TEXT_KINDS = ("name", "short_description", "long_description")


def variant_signature(items, ctx):
    """{key: value_norm} of the variant attributes (size, colour...) of one record."""
    return {key: normalize(raw, unit)[0] for key, label, raw, unit, _ in items
            if raw not in (None, "") and signals.variant_key(label, ctx.cfg)}


def sync_texts(db, link, source, texts, ctx):
    """Keep every name/description variant verbatim (KNOWLEDGE-02); no consolidation."""
    import hashlib

    changed = 0
    for kind in TEXT_KINDS:
        text = (texts.get(kind) or "").strip()
        current = db.scalar(select(KnowledgeText).where(
            KnowledgeText.link_id == link.id, KnowledgeText.kind == kind,
            KnowledgeText.current.is_(True)))
        digest = hashlib.sha256(text.encode()).hexdigest() if text else None
        if current is not None and current.text_hash == digest:
            if current.knowledge_product_id != link.knowledge_product_id:
                current.knowledge_product_id = link.knowledge_product_id
            continue
        if current is not None:
            current.current, current.superseded_at = False, now()
            changed += 1
        if not text:
            continue
        variant = db.scalar(select(KnowledgeText).where(
            KnowledgeText.link_id == link.id, KnowledgeText.kind == kind,
            KnowledgeText.text_hash == digest))
        if variant is not None:  # an earlier variant came back
            variant.current, variant.superseded_at = True, None
            variant.knowledge_product_id = link.knowledge_product_id
        else:
            language, confidence = signals.detect_language(text, ctx.cfg["languages"])
            db.add(KnowledgeText(
                knowledge_product_id=link.knowledge_product_id, link_id=link.id,
                source_id=source.id, kind=kind, text=text, text_hash=digest,
                format="html" if signals.TAG.search(text) else "plain", language=language,
                language_confidence=confidence, language_method="heuristic",
                verification="unverified", usage="inherited",
                pii_flags=signals.pii_flags(text), current=True))
        changed += 1
    return changed


def reference_texts(product):
    return {"name": product.name, "short_description": product.short_description,
            "long_description": product.long_description}


def supplier_texts(product):
    data = product.data or {}
    return {"name": data.get("name"), "long_description": data.get("description")}


def rebuild(db, source_id=None, tenant_id=None, batch=200, recompute=False):
    """Bring the knowledge base up to date for one source, one tenant, or everything.

    Idempotent: an unchanged record changes nothing. Commits every `batch` records.
    recompute=True (KNOWLEDGE-02 settings change) recalculates every current observation's
    confidence from its stored identity confidence and the current settings.
    """
    from app.import_models import SupplierProduct

    counters = {"records": 0, "linked": 0, "observations_changed": 0, "values": 0,
                "withdrawn": 0, "sources": 0, "texts_changed": 0, "recomputed": 0,
                "relations_changed": 0}
    ctx = Context(db)
    mappings = mapping_index(db)
    touched = set()

    def flush_touched():
        for product_id, key in sorted(touched):
            if consolidate(db, product_id, key, ctx) is not None:
                counters["values"] += 1
        touched.clear()
        db.commit()

    if recompute:
        sources = {s.id: s for s in db.scalars(select(ReferenceProductSource))}
        for i, obs in enumerate(db.scalars(select(KnowledgeObservation).where(
                KnowledgeObservation.current.is_(True))).all(), 1):
            identity = obs.identity_confidence
            if identity is None:
                identity = db.scalar(select(KnowledgeLink.confidence).where(
                    KnowledgeLink.id == obs.link_id))
            value = (Decimal(ctx.trust(sources[obs.source_id], obs.origin)) *
                     Decimal(identity)).quantize(Decimal("0.0001"))
            if value != obs.confidence:
                obs.confidence = value
                counters["recomputed"] += 1
            touched.add((obs.knowledge_product_id, obs.attribute_key))
            if i % 1000 == 0:
                flush_touched()
        for product_id, key in db.execute(select(KnowledgeValue.knowledge_product_id,
                                                 KnowledgeValue.attribute_key)):
            touched.add((product_id, key))
        flush_touched()
        return counters

    def handle(kind, pid, source, tid, keys_, name, brand, items, texts):
        link = link_member(db, kind, pid, source, tid, keys_, name, brand,
                           variant_signature(items, ctx))
        counters["linked"] += 1
        keys = sync_observations(db, link, source, items, ctx)
        counters["observations_changed"] += len(keys)
        counters["texts_changed"] += sync_texts(db, link, source, texts, ctx)
        touched.update((link.knowledge_product_id, k) for k in keys)

    def withdraw(kind, pid):
        link = db.scalar(select(KnowledgeLink).where(KnowledgeLink.member_kind == kind,
                                                     KnowledgeLink.member_id == pid))
        if link:
            keys = retire_link(db, link)
            counters["withdrawn"] += bool(keys)
            touched.update((link.knowledge_product_id, k) for k in keys)

    reference_sources = select(ReferenceProductSource).where(
        ReferenceProductSource.kind != "tenant_import")
    if source_id is not None:
        reference_sources = reference_sources.where(ReferenceProductSource.id == source_id)
    if tenant_id is None:
        for source in list(db.scalars(reference_sources)):
            counters["sources"] += 1
            products = list(db.scalars(select(ReferenceProduct.id).where(
                ReferenceProduct.source_id == source.id).order_by(ReferenceProduct.id)))
            for i, pid in enumerate(products, 1):
                product = db.get(ReferenceProduct, pid)
                counters["records"] += 1
                if not permitted(source):
                    withdraw("reference_product", pid)
                    continue
                gtins = list(db.scalars(select(ReferenceProductIdentifier.value).where(
                    ReferenceProductIdentifier.product_id == pid,
                    ReferenceProductIdentifier.kind == "gtin",
                    ReferenceProductIdentifier.valid.is_(True))))
                handle("reference_product", pid, source, None,
                       identity_keys(gtins, None, product.brand, product.name),
                       product.name, product.brand, reference_items(db, product, mappings),
                       reference_texts(product))
                if i % batch == 0:
                    flush_touched()
    if source_id is None:
        tenants = list(db.scalars(select(SupplierProduct.tenant_id).distinct()))
        if tenant_id is not None:
            tenants = [t for t in tenants if t == tenant_id]
        for tid in tenants:
            source = tenant_source(db, tid)
            counters["sources"] += 1
            ids = list(db.scalars(select(SupplierProduct.id).where(
                SupplierProduct.tenant_id == tid).order_by(SupplierProduct.id)))
            for i, pid in enumerate(ids, 1):
                product = db.get(SupplierProduct, pid)
                counters["records"] += 1
                if not permitted(source):
                    withdraw("supplier_product", pid)
                    continue
                data = product.data or {}
                keys_ = identity_keys([str(data.get("gtin") or "")], data.get("mpn"),
                                      data.get("brand"), data.get("name"))
                if not keys_:
                    continue  # nothing reliable to identify the product across sources
                handle("supplier_product", pid, source, tid, keys_, data.get("name"),
                       data.get("brand"), supplier_items(db, product), supplier_texts(product))
                if i % batch == 0:
                    flush_touched()
    flush_touched()
    changed = detect_relations(db, ctx)
    counters["relations_changed"] = len(changed)
    if changed:
        refresh_sources(db, changed)
    return counters


# --- copy suspicion (KNOWLEDGE-02) -------------------------------------------------------------


def relation_stats(db):
    """Per source pair over shared clusters: shared values, verbatim-identical values and
    identical long descriptions. Only current, non-held claims count."""
    from sqlalchemy import and_, case, func
    from sqlalchemy.orm import aliased

    a, b = aliased(KnowledgeObservation), aliased(KnowledgeObservation)
    stats = {}
    rows = db.execute(
        select(a.source_id, b.source_id, func.count(),
               func.sum(case((a.value_raw == b.value_raw, 1), else_=0)))
        .join(b, and_(a.knowledge_product_id == b.knowledge_product_id,
                      a.attribute_key == b.attribute_key, a.source_id < b.source_id))
        .where(a.current.is_(True), b.current.is_(True))
        .group_by(a.source_id, b.source_id))
    for sa_, sb, shared, identical in rows:
        stats[(sa_, sb)] = [int(shared), int(identical or 0), 0]
    ta, tb = aliased(KnowledgeText), aliased(KnowledgeText)
    for sa_, sb, count in db.execute(
            select(ta.source_id, tb.source_id, func.count())
            .join(tb, and_(ta.knowledge_product_id == tb.knowledge_product_id,
                           ta.kind == tb.kind, ta.text_hash == tb.text_hash,
                           ta.source_id < tb.source_id))
            .where(ta.kind == "long_description", ta.current.is_(True), tb.current.is_(True))
            .group_by(ta.source_id, tb.source_id)):
        stats.setdefault((sa_, sb), [0, 0, 0])[2] = int(count)
    return stats


def detect_relations(db, ctx):
    """Update copy-suspicion relations; returns the source pairs whose dependency changed.

    A match is only a suspicion (state "suspected"); it never verifies anything, it only makes
    the pair count as one independent source. Administrator decisions are kept.
    """
    cfg = ctx.cfg
    changed = []
    for (sa_, sb), (shared, identical, texts) in relation_stats(db).items():
        ratio = Decimal(identical) / Decimal(shared) if shared else Decimal("0")
        suspected = (shared >= int(cfg["copy_min_shared_values"]) and
                     ratio >= signals.dec(cfg["copy_identical_ratio"])) or \
            texts >= int(cfg["copy_min_identical_texts"])
        relation = db.scalar(select(KnowledgeSourceRelation).where(
            KnowledgeSourceRelation.source_a_id == sa_,
            KnowledgeSourceRelation.source_b_id == sb))
        if relation is None:
            relation = KnowledgeSourceRelation(source_a_id=sa_, source_b_id=sb,
                                               state="below_threshold")
            db.add(relation)
        relation.shared_values, relation.identical_values = shared, identical
        relation.identical_texts, relation.ratio = texts, ratio.quantize(Decimal("0.0001"))
        relation.updated_at = now()
        if relation.decided_by is None:
            state = "suspected" if suspected else "below_threshold"
            if state != relation.state:
                relation.state = state
                changed.append((sa_, sb))
                event(db, "copy_suspected" if suspected else "copy_suspicion_cleared",
                      source_a=sa_, source_b=sb, shared=shared, identical=identical,
                      texts=texts)
    db.commit()
    return changed


def refresh_sources(db, pairs):
    """Re-score the values of clusters shared by sources whose dependency changed."""
    ctx = Context(db)
    sources = {s for pair in pairs for s in pair}
    keys = set(db.execute(select(KnowledgeObservation.knowledge_product_id,
                                 KnowledgeObservation.attribute_key)
                          .where(KnowledgeObservation.source_id.in_(sources),
                                 KnowledgeObservation.current.is_(True))).all())
    for product_id, key in sorted(keys):
        consolidate(db, product_id, key, ctx)
    db.commit()


# --- decisions (learning from people) ------------------------------------------------------


def verify_value(db, value, actor_id, value_norm=None, reason=None):
    """An administrator confirms a value (optionally one of the conflict candidates)."""
    if value_norm is not None and value_norm != value.value_norm:
        candidate = db.scalar(select(KnowledgeObservation).where(
            KnowledgeObservation.knowledge_product_id == value.knowledge_product_id,
            KnowledgeObservation.attribute_key == value.attribute_key,
            KnowledgeObservation.value_norm == value_norm,
            KnowledgeObservation.current.is_(True)))
        if candidate is None:
            raise ValueError("unknown_candidate")
        value.value_norm = value_norm
        value.value_display = normalize(candidate.value_raw, candidate.unit)[1]
    if value.value_norm is None:
        raise ValueError("no_value")
    value.status, value.verification_basis = "verified", "admin_decision"
    value.verified_by, value.verified_at, value.updated_at = actor_id, now(), now()
    value.rejected_values = [v for v in (value.rejected_values or []) if v != value.value_norm]
    event(db, "value_verified", value.knowledge_product_id, value_id=value.id,
          actor_id=actor_id, value=value.value_norm, reason=reason)
    close_conflicts(db, value, value.value_norm, actor_id, reason)
    consolidate(db, value.knowledge_product_id, value.attribute_key)


def reject_value(db, value, actor_id, reason=None):
    """The current value is wrong: never offered again; the next best candidate follows."""
    if value.value_norm is None:
        raise ValueError("no_value")
    rejected = value.value_norm
    value.rejected_values = list(dict.fromkeys([*(value.rejected_values or []), rejected]))
    value.status, value.verification_basis, value.verified_by = "candidate", None, None
    value.value_norm = None
    event(db, "value_rejected", value.knowledge_product_id, value_id=value.id,
          actor_id=actor_id, value=rejected, reason=reason)
    consolidate(db, value.knowledge_product_id, value.attribute_key)


def unlink(db, link, actor_id, reason=None):
    """A record does not belong to this product: it gets its own cluster, permanently."""
    old = link.knowledge_product_id
    product = KnowledgeProduct(status="active")
    db.add(product)
    db.flush()
    link.knowledge_product_id, link.method, link.confidence = product.id, "manual", Decimal("1")
    link.decided_by, link.decided_at, link.updated_at = actor_id, now(), now()
    keys = set()
    for obs in db.scalars(select(KnowledgeObservation).where(KnowledgeObservation.link_id ==
                                                             link.id)):
        obs.knowledge_product_id = product.id
        keys.add(obs.attribute_key)
    for text in db.scalars(select(KnowledgeText).where(KnowledgeText.link_id == link.id)):
        text.knowledge_product_id = product.id
    event(db, "unlinked", old, link_id=link.id, actor_id=actor_id, new_product=product.id,
          reason=reason)
    for key in keys:
        consolidate(db, old, key)
        consolidate(db, product.id, key)
    return product


# --- manual merge (KNOWLEDGE-02) ---------------------------------------------------------------


class MergeError(ValueError):
    def __init__(self, code, status=409, **details):
        super().__init__(code)
        self.code, self.status, self.details = code, status, details


def _state(db, product_id):
    links = sorted(db.scalars(select(KnowledgeLink.id).where(
        KnowledgeLink.knowledge_product_id == product_id)))
    values = sorted((v.attribute_key, v.value_norm or "", v.status) for v in db.scalars(
        select(KnowledgeValue).where(KnowledgeValue.knowledge_product_id == product_id)))
    return {"links": links, "values": values}


def merge_preview(db, survivor_id, merged_id):
    """What a manual merge would do; changes nothing. The token binds a later apply to this
    exact state of both products."""
    import hashlib

    if survivor_id == merged_id:
        raise MergeError("same_product", 422)
    survivor, merged = db.get(KnowledgeProduct, survivor_id), db.get(KnowledgeProduct, merged_id)
    if survivor is None or merged is None:
        raise MergeError("not_found", 404)
    if survivor.status != "active" or merged.status != "active":
        raise MergeError("not_active")
    ctx = Context(db)
    s_state, m_state = _state(db, survivor_id), _state(db, merged_id)
    token = hashlib.sha256(json.dumps([survivor_id, merged_id, s_state, m_state],
                                      default=str).encode()).hexdigest()
    s_values = {v.attribute_key: v for v in db.scalars(select(KnowledgeValue).where(
        KnowledgeValue.knowledge_product_id == survivor_id))}
    m_values = {v.attribute_key: v for v in db.scalars(select(KnowledgeValue).where(
        KnowledgeValue.knowledge_product_id == merged_id))}
    values, blocking, warnings = [], [], []
    for key in sorted(set(s_values) | set(m_values)):
        a, b = s_values.get(key), m_values.get(key)
        if a is None or a.value_norm is None:
            outcome = "new"
        elif b is None or b.value_norm is None or a.value_norm == b.value_norm:
            outcome = "same"
        else:
            outcome = "would_conflict"
            if a.status == "verified" and b.status == "verified":
                blocking.append({"code": "verified_values_differ", "attribute_key": key})
            if signals.variant_key((a or b).attribute_label, ctx.cfg):
                warnings.append({"code": "variant_attribute_differs", "attribute_key": key,
                                 "label": (a or b).attribute_label})
        values.append({"attribute_key": key, "outcome": outcome,
                       "survivor": a.value_display if a else None,
                       "merged": b.value_display if b else None})
    gtins = {pid: set(db.scalars(select(KnowledgeIdentity.value).where(
        KnowledgeIdentity.knowledge_product_id == pid, KnowledgeIdentity.kind == "gtin")))
        for pid in (survivor_id, merged_id)}
    if gtins[survivor_id] and gtins[merged_id] and \
            not gtins[survivor_id] & gtins[merged_id]:
        warnings.append({"code": "different_gtins"})
    sources = {pid: set(db.scalars(select(KnowledgeLink.source_id).where(
        KnowledgeLink.knowledge_product_id == pid))) for pid in (survivor_id, merged_id)}
    if sources[survivor_id] & sources[merged_id]:
        warnings.append({"code": "same_source_in_both",
                         "sources": sorted(sources[survivor_id] & sources[merged_id])})
    moves = {}
    for link in db.scalars(select(KnowledgeLink).where(
            KnowledgeLink.knowledge_product_id == merged_id)):
        moves[link.source_id] = moves.get(link.source_id, 0) + 1
    return {"survivor_id": survivor_id, "merged_id": merged_id, "preview_token": token,
            "moves": {"links": len(m_state["links"]), "by_source": moves},
            "values": values, "warnings": warnings, "blocking": blocking,
            "variant_risk": bool(warnings)}


def merge_apply(db, survivor_id, merged_id, preview_token, reason, actor_id,
                acknowledge_variant_risk=False):
    preview = merge_preview(db, survivor_id, merged_id)
    if preview["preview_token"] != preview_token:
        raise MergeError("stale_preview")
    if preview["blocking"]:
        raise MergeError("blocked", blocking=preview["blocking"])
    if preview["variant_risk"] and not acknowledge_variant_risk:
        raise MergeError("variant_risk_not_acknowledged", warnings=preview["warnings"])
    moved = {"links": [], "identities": [], "observations": [], "texts": []}
    keys = set()
    for link in db.scalars(select(KnowledgeLink).where(
            KnowledgeLink.knowledge_product_id == merged_id)):
        link.knowledge_product_id = survivor_id
        moved["links"].append(link.id)
    for identity in db.scalars(select(KnowledgeIdentity).where(
            KnowledgeIdentity.knowledge_product_id == merged_id)):
        identity.knowledge_product_id = survivor_id
        moved["identities"].append(identity.id)
    for obs in db.scalars(select(KnowledgeObservation).where(
            KnowledgeObservation.knowledge_product_id == merged_id)):
        obs.knowledge_product_id = survivor_id
        moved["observations"].append(obs.id)
        keys.add(obs.attribute_key)
    for text in db.scalars(select(KnowledgeText).where(
            KnowledgeText.knowledge_product_id == merged_id)):
        text.knowledge_product_id = survivor_id
        moved["texts"].append(text.id)
    merged = db.get(KnowledgeProduct, merged_id)
    merged.status, merged.merged_into_id, merged.updated_at = "merged", survivor_id, now()
    record = KnowledgeMerge(survivor_id=survivor_id, merged_id=merged_id, state="applied",
                            preview_token=preview_token,
                            variant_risk_acknowledged=bool(acknowledge_variant_risk),
                            moved=moved, reason=reason, applied_by=actor_id)
    db.add(record)
    db.flush()
    ctx = Context(db)
    for key in sorted(keys | set(db.scalars(select(KnowledgeValue.attribute_key).where(
            KnowledgeValue.knowledge_product_id == survivor_id)))):
        consolidate(db, survivor_id, key, ctx)
    event(db, "merge_applied", survivor_id, actor_id=actor_id, merge_id=record.id,
          merged_id=merged_id, moved={k: len(v) for k, v in moved.items()}, reason=reason,
          variant_risk_acknowledged=bool(acknowledge_variant_risk))
    return record


def merge_revert(db, record, actor_id, reason):
    """Undo one merge exactly from its movement log (last merge first)."""
    if record.state != "applied":
        raise MergeError("not_applied")
    later = db.scalar(select(KnowledgeMerge.id).where(
        KnowledgeMerge.state == "applied", KnowledgeMerge.id > record.id,
        (KnowledgeMerge.survivor_id.in_([record.survivor_id, record.merged_id])) |
        (KnowledgeMerge.merged_id.in_([record.survivor_id, record.merged_id]))).limit(1))
    if later is not None:
        raise MergeError("later_merge_first", later_merge_id=later)
    moved = record.moved
    keys = set()
    for link in db.scalars(select(KnowledgeLink).where(KnowledgeLink.id.in_(moved["links"]))):
        link.knowledge_product_id = record.merged_id
    for identity in db.scalars(select(KnowledgeIdentity).where(
            KnowledgeIdentity.id.in_(moved["identities"]))):
        identity.knowledge_product_id = record.merged_id
    for obs in db.scalars(select(KnowledgeObservation).where(
            KnowledgeObservation.id.in_(moved["observations"]))):
        obs.knowledge_product_id = record.merged_id
        keys.add(obs.attribute_key)
    for text in db.scalars(select(KnowledgeText).where(KnowledgeText.id.in_(moved["texts"]))):
        text.knowledge_product_id = record.merged_id
    merged = db.get(KnowledgeProduct, record.merged_id)
    merged.status, merged.merged_into_id, merged.updated_at = "active", None, now()
    record.state, record.reverted_by, record.reverted_at = "reverted", actor_id, now()
    record.revert_reason = reason
    db.flush()
    ctx = Context(db)
    for product_id in (record.survivor_id, record.merged_id):
        for key in sorted(keys | set(db.scalars(select(KnowledgeValue.attribute_key).where(
                KnowledgeValue.knowledge_product_id == product_id)))):
            consolidate(db, product_id, key, ctx)
    event(db, "merge_reverted", record.survivor_id, actor_id=actor_id, merge_id=record.id,
          merged_id=record.merged_id, reason=reason)


# --- texts and personal-data review (KNOWLEDGE-02) --------------------------------------------


def text_usable(text, source):
    """May this text feed AI generation / other customers' shared knowledge?"""
    return (permitted(source) and text.current and text.verification != "rejected"
            and text.usage not in ("internal_only", "restricted")
            and not signals.pii_held(text.pii_flags, text.pii_reviewed_by))


def review_observation_pii(db, obs, actor_id, release, reason):
    """A permitted user reviewed a held value: release it, or keep it excluded for good."""
    obs.pii_reviewed_by, obs.pii_reviewed_at = actor_id, now()
    if not release:
        obs.current, obs.superseded_at = False, now()
    event(db, "pii_reviewed", obs.knowledge_product_id, actor_id=actor_id,
          observation_id=obs.id, released=release, reason=reason)
    consolidate(db, obs.knowledge_product_id, obs.attribute_key)


def decide_text(db, text, actor_id, reason, verification=None, usage=None, language=None,
                pii_release=None):
    before = {"verification": text.verification, "usage": text.usage,
              "language": text.language, "pii_reviewed": text.pii_reviewed_by is not None}
    if verification is not None:
        text.verification = verification
    if usage is not None:
        text.usage = usage
    if language is not None:
        text.language, text.language_method = language, "admin"
        text.language_confidence = Decimal("1")
    if pii_release is not None and text.pii_flags:
        text.pii_reviewed_by, text.pii_reviewed_at = actor_id, now()
        if not pii_release:
            text.usage = "restricted"  # reviewed and kept out of shared/AI use
    text.decided_by, text.decided_at = actor_id, now()
    event(db, "text_decision", text.knowledge_product_id, actor_id=actor_id, text_id=text.id,
          before=before, after={"verification": text.verification, "usage": text.usage,
                                "language": text.language,
                                "pii_reviewed": text.pii_reviewed_by is not None},
          reason=reason)


# --- reuse in enrichment ---------------------------------------------------------------------


def find_product(db, gtin=None, mpn=None, brand=None, name=None):
    for kind, value in identity_keys([gtin] if gtin else [], mpn, brand, name):
        hit = db.scalar(select(KnowledgeIdentity.knowledge_product_id).where(
            KnowledgeIdentity.kind == kind, KnowledgeIdentity.value == value))
        if hit is not None:
            return hit, kind
    return None, None


def enrichment_plan(db, attributes, gtin=None, mpn=None, brand=None, name=None,
                    threshold=None, texts=()):
    """Which requested attributes can come from knowledge and which still need research.

    reuse: verified values (facts); suggest: unconflicted candidates at or above the
    threshold (offered, not facts); research: everything else (missing, conflicting, weak).
    Only consolidated values are returned - never another tenant's records or provenance.
    """
    if threshold is None:  # KNOWLEDGE-02: configurable suggestion threshold
        threshold = signals.dec(signals.settings(db)["suggest_threshold"])
    product_id, method = find_product(db, gtin, mpn, brand, name)
    plan = {"knowledge_product_id": product_id, "match": method, "reuse": [], "suggest": [],
            "research": []}
    values = {}
    if product_id is not None:
        values = {v.attribute_key: v for v in db.scalars(select(KnowledgeValue).where(
            KnowledgeValue.knowledge_product_id == product_id))}
    for key in attributes:
        v = values.get(key)
        item = {"attribute_key": key}
        if v is not None and v.value_norm is not None:
            item |= {"value": v.value_display, "value_norm": v.value_norm, "status": v.status,
                     "confidence": str(v.confidence)}
        if v is not None and v.status == "verified":
            plan["reuse"].append(item)
        elif v is not None and v.status == "candidate" and v.value_norm and \
                v.confidence >= threshold:
            plan["suggest"].append(item)
        else:
            item["reason"] = ("conflict" if v is not None and v.status == "conflict" else
                              "low_confidence" if v is not None and v.value_norm else "unknown")
            plan["research"].append(item)
    plan["research_avoided"] = len(plan["reuse"]) + len(plan["suggest"])
    if texts:
        # Counts only (never another tenant's text): usable variants per kind and language.
        available = {}
        if product_id is not None:
            sources = {s.id: s for s in db.scalars(select(ReferenceProductSource))}
            for t in db.scalars(select(KnowledgeText).where(
                    KnowledgeText.knowledge_product_id == product_id,
                    KnowledgeText.kind.in_(list(texts)), KnowledgeText.current.is_(True))):
                if text_usable(t, sources[t.source_id]):
                    by_kind = available.setdefault(t.kind, {})
                    by_kind[t.language] = by_kind.get(t.language, 0) + 1
        plan["texts_available"] = available
    return plan


# --- automatic updates -----------------------------------------------------------------------


@celery.task(name="knowledge.rebuild", acks_late=True)
def process_rebuild(source_id=None, tenant_id=None, recompute=False):
    from app.db import engine

    with Session(engine()) as db:
        return rebuild(db, source_id=source_id, tenant_id=tenant_id, recompute=recompute)


def schedule(source_id=None, tenant_id=None, recompute=False):
    """Queue an incremental rebuild; never breaks the caller (import, reference import)."""
    try:
        # No publish retries: an unavailable broker must not delay the import that called
        # us; the next import or an explicit rebuild catches up (rebuild is idempotent).
        process_rebuild.apply_async(kwargs={"source_id": source_id, "tenant_id": tenant_id,
                                            "recompute": recompute}, retry=False)
    except Exception:
        log.exception("Knowledge rebuild scheduling failed: source=%s tenant=%s",
                      source_id, tenant_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("rebuild")
    run.add_argument("--source-id", type=int)
    run.add_argument("--tenant-id", type=int)
    run.add_argument("--recompute", action="store_true",
                     help="recalculate every confidence from the current knowledge settings")
    args = parser.parse_args(argv)
    from app.db import engine

    with Session(engine()) as db:
        print(json.dumps(rebuild(db, args.source_id, args.tenant_id,
                                 recompute=args.recompute)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
