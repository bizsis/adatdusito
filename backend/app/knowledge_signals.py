"""KNOWLEDGE-02 helpers: configurable scoring, language detection, personal-data flags and
source families (lineage groups and copy-suspicion relations). No network, no new deps."""

import re
from decimal import Decimal

from sqlalchemy import select

from app.reference_products import fold

# --- settings --------------------------------------------------------------------------------


def settings(db):
    from app.system_config import config

    return config(db, "knowledge")


def dec(value):
    return Decimal(str(value))


# --- language detection ----------------------------------------------------------------------

# Extensible: a code listed in the "languages" setting is detected when a profile exists here;
# adding a language = adding a profile (stop words + characteristic letters).
PROFILES = {
    "hu": {"words": {"a", "az", "és", "egy", "hogy", "nem", "is", "van", "vagy", "csak", "ez",
                     "mint", "ezt", "már", "meg", "kell", "termék", "cm", "ml", "darab",
                     "alkalmas", "segítségével", "kiváló", "minőségű", "használat"},
           "letters": "őűáéíóöúü"},
    "en": {"words": {"the", "and", "of", "to", "is", "for", "with", "in", "this", "it", "on",
                     "are", "your", "from", "be", "can", "use", "product", "high", "quality"},
           "letters": ""},
    "ro": {"words": {"și", "si", "de", "la", "în", "cu", "pentru", "este", "un", "o", "care",
                     "din", "pe", "nu", "mai", "produs", "calitate", "utilizare"},
           "letters": "ăâîșțşţ"},
    "de": {"words": {"und", "der", "die", "das", "mit", "für", "ist", "ein", "eine", "nicht",
                     "zu", "von", "auf", "den", "im", "sie", "produkt", "hochwertig"},
           "letters": "äöüß"},
}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
TAG = re.compile(r"<[a-zA-Z/][^>]{0,200}>")


def strip_html(text):
    return TAG.sub(" ", text or "")


def detect_language(text, languages):
    """(code, confidence); "unknown" when the evidence is too thin or too close to call."""
    words = [w.casefold() for w in WORD.findall(strip_html(text))]
    if len(words) < 4:
        return "unknown", Decimal("0")
    scores = {}
    for code in languages:
        profile = PROFILES.get(code)
        if not profile:
            continue
        hits = sum(w in profile["words"] for w in words)
        letters = sum(c in profile["letters"] for w in words for c in w) if profile["letters"] \
            else 0
        scores[code] = hits + letters * 0.5
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    # Enough evidence: at least 2 points and 15% of the words (one configured language would
    # otherwise win on a couple of shared short words).
    if not ranked or ranked[0][1] < max(2, len(words) * 0.15):
        return "unknown", Decimal("0")
    best, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    confidence = Decimal(str(round((top - second) / top, 4)))
    if confidence < Decimal("0.3"):
        return "unknown", confidence
    return best, confidence


# --- personal data -----------------------------------------------------------------------------

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    # +36 / 06 Hungarian or +<country> international numbers with typical separators.
    "phone": re.compile(r"(?:\+\d{2,3}|\b06)[\s/-]?\(?\d{1,2}\)?[\s/-]?\d{3}[\s/-]?\d{3,4}\b"),
    "tax_number": re.compile(r"\b\d{8}-\d-\d{2}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
}


def pii_flags(text):
    """Kinds of personal-data patterns found; detection, not a DLP guarantee."""
    plain = strip_html(text)
    return [kind for kind, pattern in PII_PATTERNS.items() if pattern.search(plain)]


def pii_held(flags, reviewed_by):
    """Flagged content stays excluded until a permitted user has reviewed it."""
    return bool(flags) and reviewed_by is None


# --- variant attributes ---------------------------------------------------------------------------


def variant_key(label, cfg):
    folded = fold(label or "")
    return any(fold(term) and fold(term) in folded for term in cfg.get("variant_attributes", []))


# --- source families ------------------------------------------------------------------------------

DEPENDENT_STATES = ("suspected", "confirmed_dependent")


def families(db):
    """source_id -> family key. One family counts as one independent source.

    Members: the same administrator-set lineage group, or a suspected/confirmed copying
    relation (a suspicion only ever lowers confidence; confirmed_independent splits again).
    """
    from app.knowledge_models import KnowledgeSourceRelation
    from app.unas_models import ReferenceProductSource

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    groups = {}
    for source_id, group in db.execute(select(ReferenceProductSource.id,
                                              ReferenceProductSource.lineage_group)):
        find(source_id)
        if group:
            groups.setdefault(group, []).append(source_id)
    for members in groups.values():
        for other in members[1:]:
            union(members[0], other)
    for a, b in db.execute(select(KnowledgeSourceRelation.source_a_id,
                                  KnowledgeSourceRelation.source_b_id)
                           .where(KnowledgeSourceRelation.state.in_(DEPENDENT_STATES))):
        union(a, b)
    return {s: find(s) for s in list(parent)}
