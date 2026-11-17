"""KNOWLEDGE-02: configurable scoring, copy suspicion and lineage, language detection, text
variants, personal-data holds, variant guard, manual merge with preview/undo, migration 0016.
Synthetic data only."""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app import knowledge as kb
from app import knowledge_signals as signals
from app.knowledge_models import (
    KnowledgeEvent,
    KnowledgeLink,
    KnowledgeObservation,
    KnowledgeProduct,
    KnowledgeSourceRelation,
    KnowledgeText,
    KnowledgeValue,
)
from app.models import Audit
from app.reference_products import import_export
from app.system_config import DEFAULTS, config, store
from app.unas_models import ReferenceProduct, ReferenceProductSource
from conftest import login
from test_access_migration import load
from test_category02a_migration import seed
from test_supplier_import import imports  # noqa: F401
from test_unas_reference import export, product

BACKEND = Path(__file__).resolve().parents[1]
WIDTH = "Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1"
HEIGHT = "Paraméter: Magasság||num|1|0|0|0|0|0||cm|0|1|1"
SIZE = "Paraméter: Méret||text|1|0|1|0|0|0|||0|1|1"
MATERIAL = "Paraméter: Anyag||text|1|0|1|0|0|0|||0|1|1"
LONG = "Tulajdonságok"
EAN_A, EAN_B, EAN_C = "5201137061819", "5904517345546", "4006381333931"
HU = ("A termék kiváló minőségű, és egy hosszú használat során is megbízható, mert az "
      "anyaga tartós és könnyen tisztítható.")
EN = "This product is made for daily use and the high quality material is easy to clean."


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    calls = []
    monkeypatch.setattr(kb, "schedule", lambda **kw: calls.append(kw))
    return calls


def ref(db, tmp_path, key, rows, version="20261117-084322"):
    return import_export(db, export(tmp_path, rows, name=f"UnasShop_{key}_{version}.xlsx"),
                         store_key=key, version=version)


def source(db, key):
    return db.scalar(select(ReferenceProductSource).where(
        ReferenceProductSource.store_key == key))


def configure(db, **values):
    store(db, "knowledge", {**config(db, "knowledge"), **values})
    db.commit()


def cluster_of(db, store_key, sku):
    src = source(db, store_key)
    pid = db.scalar(select(ReferenceProduct.id).where(ReferenceProduct.source_id == src.id,
                                                      ReferenceProduct.source_sku == sku))
    return db.scalar(select(KnowledgeLink.knowledge_product_id).where(
        KnowledgeLink.member_kind == "reference_product", KnowledgeLink.member_id == pid))


def value(db, product_id, key):
    return db.scalar(select(KnowledgeValue).where(KnowledgeValue.knowledge_product_id ==
                                                  product_id,
                                                  KnowledgeValue.attribute_key == key))


def rows(desc=HU):
    return [product("C-1", "Mosógép", EAN_A, brand="Acme", **{WIDTH: "60", HEIGHT: "85",
                                                               LONG: desc}),
            product("C-2", "Porszívó", EAN_B, brand="Acme", **{WIDTH: "30", HEIGHT: "40",
                                                                LONG: desc + " 2"})]


@pytest.fixture
def two_copies(imports, tmp_path):
    """Two reference shops whose exports are verbatim copies of each other."""
    client, target, _ = imports
    with Session(target) as db:
        ref(db, tmp_path, "a-unas-hu", rows())
        ref(db, tmp_path, "b-unas-hu", rows())
    return client, target


# --- settings -----------------------------------------------------------------------------------


def test_knowledge_settings_api_is_permissioned_validated_audited_and_recomputes(imports,
                                                                                 no_broker):
    client, target, _ = imports
    body = {**DEFAULTS["knowledge"], "trust_reference": 0.4, "copy_min_shared_values": 10}
    login(client, "admin@example.hu")
    assert client.put("/api/v1/system/settings/knowledge", json=body).status_code == 403
    login(client)
    assert client.get("/api/v1/system/settings").json()["knowledge"]["suggest_threshold"] == 0.8
    bad = [{**body, "suggest_threshold": 0.99}, {**body, "languages": ["HU!"]},
           {**body, "variant_attributes": [""]}, {**body, "copy_identical_ratio": 0},
           {**body, "unknown": 1}]
    for b in bad:
        assert client.put("/api/v1/system/settings/knowledge", json=b).status_code == 422, b
    r = client.put("/api/v1/system/settings/knowledge", json=body)
    assert r.status_code == 200 and r.json()["trust_reference"] == 0.4
    assert no_broker == [{"recompute": True}]
    with Session(target) as db:
        assert config(db, "knowledge")["copy_min_shared_values"] == 10
        audit = db.scalar(select(Audit).where(Audit.action == "settings09.knowledge"))
        assert audit is not None


def test_recompute_applies_new_trust_and_threshold(two_copies):
    client, target = two_copies
    with Session(target) as db:
        kb.rebuild(db)
        pid = cluster_of(db, "a-unas-hu", "C-1")
        obs = db.scalar(select(KnowledgeObservation).where(
            KnowledgeObservation.knowledge_product_id == pid, KnowledgeObservation.current))
        assert obs.confidence == Decimal("0.6") and obs.identity_confidence == Decimal("1")
        configure(db, trust_reference=0.3)
        counters = kb.rebuild(db, recompute=True)
        assert counters["recomputed"] > 0
        db.refresh(obs)
        assert obs.confidence == Decimal("0.3")
        assert kb.rebuild(db, recompute=True)["recomputed"] == 0  # idempotent
        # The suggestion threshold of the enrichment plan follows the settings.
        configure(db, suggest_threshold=0.99, copy_min_shared_values=1_000_000,
                  copy_min_identical_texts=1_000_000)
        plan = kb.enrichment_plan(db, ["brand"], gtin=EAN_A)
        assert plan["research"] and not plan["suggest"]


# --- copy suspicion, lineage --------------------------------------------------------------------


def test_copy_suspicion_lowers_confidence_but_never_verifies(two_copies):
    _, target = two_copies
    with Session(target) as db:
        configure(db, copy_min_shared_values=2)
        counters = kb.rebuild(db)
        relation = db.scalar(select(KnowledgeSourceRelation))
        assert relation.state == "suspected" and counters["relations_changed"] == 1
        assert relation.identical_values == relation.shared_values >= 2
        pid = cluster_of(db, "a-unas-hu", "C-1")
        assert pid == cluster_of(db, "b-unas-hu", "C-1")  # same GTIN, one product
        brand = value(db, pid, "brand")
        # Two copying shops count as one source: no artificial agreement.
        assert brand.support_sources == 2 and brand.independent_sources == 1
        assert brand.confidence == Decimal("0.6") and brand.status == "candidate"
        assert db.scalar(select(func.count()).select_from(KnowledgeEvent).where(
            KnowledgeEvent.kind == "copy_suspected")) == 1


def test_without_suspicion_independent_agreement_combines(two_copies):
    _, target = two_copies
    with Session(target) as db:
        kb.rebuild(db)  # default thresholds (50 values / 20 texts): nothing suspected
        assert db.scalar(select(KnowledgeSourceRelation)).state == "below_threshold"
        brand = value(db, cluster_of(db, "a-unas-hu", "C-1"), "brand")
        assert brand.confidence == Decimal("0.84") and brand.independent_sources == 2
        assert brand.status == "candidate"  # agreement alone never verifies


def test_identical_descriptions_alone_raise_suspicion(two_copies):
    _, target = two_copies
    with Session(target) as db:
        configure(db, copy_min_identical_texts=2)
        kb.rebuild(db)
        relation = db.scalar(select(KnowledgeSourceRelation))
        assert relation.identical_texts == 2 and relation.state == "suspected"


def test_admin_decisions_on_relations_and_lineage(two_copies):
    client, target = two_copies
    with Session(target) as db:
        configure(db, copy_min_shared_values=2)
        kb.rebuild(db)
        relation_id = db.scalar(select(KnowledgeSourceRelation.id))
        pid = cluster_of(db, "a-unas-hu", "C-1")
        a, b = source(db, "a-unas-hu").id, source(db, "b-unas-hu").id
    login(client, "admin@example.hu")
    assert client.get("/api/v1/knowledge/source-relations").status_code == 403
    login(client)
    listed = client.get("/api/v1/knowledge/source-relations?state=suspected").json()
    assert [r["id"] for r in listed] == [relation_id]
    assert client.post(f"/api/v1/knowledge/source-relations/{relation_id}/decision",
                       json={"state": "suspected", "reason": "teszt"}).status_code == 422
    r = client.post(f"/api/v1/knowledge/source-relations/{relation_id}/decision",
                    json={"state": "confirmed_independent", "reason": "külön beszerzés"})
    assert r.status_code == 200 and r.json()["state"] == "confirmed_independent"
    with Session(target) as db:
        brand = value(db, pid, "brand")
        assert brand.confidence == Decimal("0.84") and brand.independent_sources == 2
        kb.rebuild(db)  # an administrator decision survives automatic detection
        assert db.get(KnowledgeSourceRelation, relation_id).state == "confirmed_independent"
    # A shared lineage group (same supplier feed) makes them one source again.
    for sid in (a, b):
        r = client.put(f"/api/v1/knowledge/sources/{sid}/lineage",
                       json={"lineage_group": "acme-feed", "reason": "közös forrás"})
        assert r.status_code == 200
    assert client.put(f"/api/v1/knowledge/sources/{a}/lineage",
                      json={"lineage_group": "bad group", "reason": "x" * 3}).status_code == 422
    with Session(target) as db:
        assert value(db, pid, "brand").independent_sources == 1
        actions = set(db.scalars(select(Audit.action)))
        assert {"knowledge.relation_decision", "knowledge.lineage"} <= actions
    assert client.post("/api/v1/knowledge/source-relations/detect").json() == {"changed": 0}


# --- languages and texts ------------------------------------------------------------------------


def test_language_detection_is_conservative_and_extensible(monkeypatch):
    langs = ["hu", "en", "ro", "de"]
    assert signals.detect_language(HU, langs)[0] == "hu"
    assert signals.detect_language(EN, langs)[0] == "en"
    assert signals.detect_language("Acest produs este de calitate și pentru utilizare zilnică "
                                   "în casă", langs)[0] == "ro"
    assert signals.detect_language("Das Produkt ist hochwertig und für den täglichen Gebrauch "
                                   "mit der Familie", langs)[0] == "de"
    assert signals.detect_language("<p>Acme WM-7</p>", langs) == ("unknown", Decimal("0"))
    assert signals.detect_language("12345 67890 abc def xyz", langs)[0] == "unknown"
    assert signals.detect_language(EN, ["hu"])[0] == "unknown"  # not configured
    monkeypatch.setitem(signals.PROFILES, "sk", {"words": {"je", "na", "pre", "a", "s", "v"},
                                                 "letters": "ľščťžýáíé"})
    assert signals.detect_language("Výrobok je vhodný na každodenné použitie pre celú "
                                   "rodinu a je ľahký", langs + ["sk"])[0] == "sk"


def test_text_variants_are_kept_with_language_history_and_usage(imports, tmp_path):
    client, target, _ = imports
    with Session(target) as db:
        ref(db, tmp_path, "a-unas-hu", rows())
        ref(db, tmp_path, "b-unas-hu", rows(EN))
        kb.rebuild(db)
        pid = cluster_of(db, "a-unas-hu", "C-1")
        ref(db, tmp_path, "a-unas-hu", rows(HU + " Új változat."), version="20261118-000000")
        assert kb.rebuild(db)["texts_changed"] >= 2
        assert kb.rebuild(db)["texts_changed"] == 0  # idempotent
    login(client)
    texts = client.get(f"/api/v1/knowledge/products/{pid}/texts?kind=long_description").json()
    assert sorted(t["language"] for t in texts) == ["en", "hu"]
    assert all(t["usable_for_ai"] and t["verification"] == "unverified" for t in texts)
    history = client.get(f"/api/v1/knowledge/products/{pid}/texts?kind=long_description"
                         "&include_history=true").json()
    assert len(history) == 3 and sum(not t["current"] for t in history) == 1
    english = client.get(f"/api/v1/knowledge/products/{pid}/texts?language=en").json()
    assert [t["language"] for t in english] == ["en"]
    tid = english[0]["id"]
    r = client.put(f"/api/v1/knowledge/texts/{tid}",
                   json={"usage": "internal_only", "language": "de", "reason": "teszt"})
    assert r.status_code == 200 and not r.json()["usable_for_ai"]
    assert r.json()["language_method"] == "admin"
    usable = client.get(f"/api/v1/knowledge/products/{pid}/texts?usable=ai_generation").json()
    assert tid not in {t["id"] for t in usable} and usable
    plan = client.post("/api/v1/knowledge/enrichment-plan",
                       json={"attributes": ["brand"], "gtin": EAN_A,
                             "texts": ["long_description", "name"]}).json()
    assert plan["texts_available"]["long_description"] == {"hu": 1}
    assert "text" not in str(plan["texts_available"])  # counts only, never the text
    assert client.post("/api/v1/knowledge/enrichment-plan",
                       json={"attributes": [], "texts": ["price"]}).status_code == 422


# --- personal data ------------------------------------------------------------------------------


def test_personal_data_is_held_from_shared_knowledge_and_ai_until_reviewed(imports, tmp_path):
    client, target, _ = imports
    with Session(target) as db:
        ref(db, tmp_path, "a-unas-hu", [product(
            "P-1", "Kávéfőző", EAN_C, brand="Acme",
            **{MATERIAL: "Kérdés: info@pelda.hu", LONG: HU + " Hívjon: +36 30 123 4567"})])
        kb.rebuild(db)
        pid = cluster_of(db, "a-unas-hu", "P-1")
        material = value(db, pid, "unas:anyag")
        assert material is not None and material.value_norm is None  # held back
        obs = db.scalar(select(KnowledgeObservation).where(
            KnowledgeObservation.attribute_key == "unas:anyag"))
        assert obs.pii_flags == ["email"]
        held = db.scalar(select(KnowledgeText).where(KnowledgeText.kind == "long_description"))
        assert held.pii_flags == ["phone"]
        assert kb.enrichment_plan(db, ["unas:anyag"], gtin=EAN_C,
                                  texts=("long_description",))["texts_available"] == {}
        obs_id, text_id = obs.id, held.id
    login(client, "admin@example.hu")
    assert client.get("/api/v1/knowledge/pii-holds").status_code == 403
    login(client)
    holds = client.get("/api/v1/knowledge/pii-holds").json()
    assert [o["id"] for o in holds["observations"]] == [obs_id]
    assert [t["id"] for t in holds["texts"]] == [text_id] and "text" not in holds["texts"][0]
    r = client.post(f"/api/v1/knowledge/observations/{obs_id}/pii-review",
                    json={"release": True, "reason": "céges ügyfélszolgálati cím"})
    assert r.status_code == 200
    assert client.post(f"/api/v1/knowledge/observations/{obs_id}/pii-review",
                       json={"release": True, "reason": "ismét"}).status_code == 409
    r = client.put(f"/api/v1/knowledge/texts/{text_id}",
                   json={"pii_release": False, "reason": "magánszám"})
    assert r.status_code == 200 and r.json()["usage"] == "restricted"
    assert not r.json()["usable_for_ai"]
    assert client.get("/api/v1/knowledge/pii-holds").json() == {"observations": [], "texts": []}
    with Session(target) as db:
        assert value(db, pid, "unas:anyag").value_norm == "txt:kerdes: info@pelda.hu"
        kinds = set(db.scalars(select(KnowledgeEvent.kind)))
        assert {"pii_reviewed", "text_decision"} <= kinds


def test_pii_patterns():
    assert signals.pii_flags("Írjon: kovacs.janos@example.com") == ["email"]
    assert signals.pii_flags("Tel.: 06-30/123-4567") == ["phone"]
    assert signals.pii_flags("Adószám: 12345678-2-41") == ["tax_number"]
    assert signals.pii_flags("HU42 1177 3016 1111 1018 0000 0000") == ["iban"]
    assert signals.pii_flags("Méret: 60 x 85 cm, 230 V, 2000 W, EAN 5201137061819") == []


# --- variant guard ------------------------------------------------------------------------------


def test_brand_name_never_links_a_different_size_variant(imports, tmp_path):
    _, target, _ = imports
    with Session(target) as db:
        ref(db, tmp_path, "a-unas-hu", [product("S-1", "Póló", None, brand="Acme",
                                                **{SIZE: "M"})])
        ref(db, tmp_path, "b-unas-hu", [product("S-2", "Póló", None, brand="Acme",
                                                **{SIZE: "XL"}),
                                        product("S-3", "Póló", None, brand="Acme",
                                                **{SIZE: "M"})])
        kb.rebuild(db)
        a = cluster_of(db, "a-unas-hu", "S-1")
        assert cluster_of(db, "b-unas-hu", "S-2") != a
        assert cluster_of(db, "b-unas-hu", "S-3") == a  # same variant still links
        assert db.scalar(select(func.count()).select_from(KnowledgeEvent).where(
            KnowledgeEvent.kind == "variant_candidate")) >= 1


# --- manual merge -------------------------------------------------------------------------------


@pytest.fixture
def separate(imports, tmp_path):
    """The same product in two shops without a shared identifier (two clusters)."""
    client, target, _ = imports
    with Session(target) as db:
        ref(db, tmp_path, "a-unas-hu", [
            product("M-1", "Vízforraló 1,7 l", None, brand="Acme", **{WIDTH: "20"}),
            product("M-3", "Kenyérpirító", None, brand="Acme", **{WIDTH: "30"})])
        ref(db, tmp_path, "b-unas-hu", [
            product("M-2", "Acme vízforraló 1.7L", None, brand="Acme",
                    **{WIDTH: "20", SIZE: "1,7 l"})])
        kb.rebuild(db)
        ids = (cluster_of(db, "a-unas-hu", "M-1"), cluster_of(db, "b-unas-hu", "M-2"),
               cluster_of(db, "a-unas-hu", "M-3"))
    assert len(set(ids)) == 3
    login(client)
    return client, target, ids


def preview(client, survivor, merged):
    r = client.post("/api/v1/knowledge/merges/preview",
                    json={"survivor_id": survivor, "merged_id": merged})
    assert r.status_code == 200, r.text
    return r.json()


def apply(client, survivor, merged, token, **extra):
    return client.post("/api/v1/knowledge/merges", json={
        "survivor_id": survivor, "merged_id": merged, "preview_token": token,
        "reason": "azonos termék", **extra})


def test_merge_preview_apply_and_revert(separate):
    client, target, (p1, p2, _) = separate
    p = preview(client, p1, p2)
    outcomes = {v["attribute_key"]: v["outcome"] for v in p["values"]}
    assert outcomes["brand"] == "same" and outcomes["unas:meret"] == "new"
    assert not p["blocking"] and not p["variant_risk"] and p["moves"]["links"] == 1
    assert apply(client, p1, p2, "0" * 64).json()["error"]["merge_error"] == "stale_preview"
    r = apply(client, p1, p2, p["preview_token"])
    assert r.status_code == 200 and r.json()["state"] == "applied"
    merge_id = r.json()["id"]
    assert r.json()["moved"]["links"] == 1
    merged = client.get(f"/api/v1/knowledge/products/{p2}").json()
    assert merged["status"] == "merged" and merged["merged_into_id"] == p1
    with Session(target) as db:
        width = value(db, p1, "unas:szelesseg")
        assert width.support_sources == 2
        kb.rebuild(db)  # automatic rebuild keeps the manual merge
        assert db.get(KnowledgeProduct, p2).status == "merged"
        assert cluster_of(db, "b-unas-hu", "M-2") == p1
    assert apply(client, p1, p2, p["preview_token"]).json()["error"]["merge_error"] == "not_active"
    assert [m["id"] for m in client.get("/api/v1/knowledge/merges").json()] == [merge_id]
    r = client.post(f"/api/v1/knowledge/merges/{merge_id}/revert", json={"reason": "téves"})
    assert r.status_code == 200 and r.json()["state"] == "reverted"
    assert client.post(f"/api/v1/knowledge/merges/{merge_id}/revert",
                       json={"reason": "téves"}).json()["error"]["merge_error"] == "not_applied"
    with Session(target) as db:
        assert db.get(KnowledgeProduct, p2).status == "active"
        assert cluster_of(db, "b-unas-hu", "M-2") == p2
        assert value(db, p1, "unas:szelesseg").support_sources == 1
        assert value(db, p1, "unas:meret") is None or value(db, p1, "unas:meret").value_norm \
            is None
        actions = set(db.scalars(select(Audit.action)))
        assert {"knowledge.merge", "knowledge.merge_revert"} <= actions
        assert {"merge_applied", "merge_reverted"} <= set(db.scalars(select(KnowledgeEvent.kind)))


def test_merge_requires_variant_ack_blocks_verified_conflicts_and_reverts_lifo(separate):
    client, target, (p1, p2, p3) = separate
    assert client.post("/api/v1/knowledge/merges/preview",
                       json={"survivor_id": p1, "merged_id": p1}).status_code == 422
    assert client.post("/api/v1/knowledge/merges/preview",
                       json={"survivor_id": p1, "merged_id": 999999}).status_code == 404
    # Different widths on a non-variant attribute: would conflict, no variant risk.
    p = preview(client, p1, p3)
    assert {v["attribute_key"]: v["outcome"] for v in p["values"]}["unas:szelesseg"] == \
        "would_conflict"
    with Session(target) as db:
        for pid in (p1, p3):
            kb.verify_value(db, value(db, pid, "unas:szelesseg"), 1, reason="teszt")
        db.commit()
    p = preview(client, p1, p3)
    assert p["blocking"] == [{"code": "verified_values_differ",
                              "attribute_key": "unas:szelesseg"}]
    r = apply(client, p1, p3, p["preview_token"], acknowledge_variant_risk=True)
    assert r.status_code == 409 and r.json()["error"]["merge_error"] == "blocked"
    # Variant attribute (Méret) differs -> explicit acknowledgement required.
    with Session(target) as db:
        db.add(KnowledgeValue(knowledge_product_id=p1, attribute_key="unas:meret",
                              attribute_label="Méret", value_norm="txt:2 l", value_display="2 l",
                              status="candidate", confidence=Decimal("0.6"), support_sources=1,
                              observations=1, rejected_values=[]))
        db.commit()
    p = preview(client, p1, p2)
    assert p["variant_risk"] and {w["code"] for w in p["warnings"]} == \
        {"variant_attribute_differs"}
    r = apply(client, p1, p2, p["preview_token"])
    assert r.status_code == 409 and r.json()["error"]["merge_error"] == \
        "variant_risk_not_acknowledged"
    first = apply(client, p1, p2, p["preview_token"], acknowledge_variant_risk=True).json()
    assert first["variant_risk_acknowledged"] is True
    # A later merge into the same survivor must be undone first (LIFO).
    with Session(target) as db:
        for pid in (p1, p3):
            v = value(db, pid, "unas:szelesseg")
            v.status, v.verification_basis = "candidate", None
        db.commit()
    p = preview(client, p1, p3)
    assert {w["code"] for w in p["warnings"]} == {"same_source_in_both"}  # one shop, twice
    r = apply(client, p1, p3, p["preview_token"], acknowledge_variant_risk=True)
    assert r.status_code == 200, r.text
    second = r.json()
    r = client.post(f"/api/v1/knowledge/merges/{first['id']}/revert", json={"reason": "x" * 3})
    assert r.status_code == 409 and r.json()["error"]["details"]["later_merge_id"] == second["id"]
    for mid in (second["id"], first["id"]):
        assert client.post(f"/api/v1/knowledge/merges/{mid}/revert",
                           json={"reason": "visszavonás"}).status_code == 200
    with Session(target) as db:
        assert {db.get(KnowledgeProduct, p).status for p in (p1, p2, p3)} == {"active"}


def test_merge_endpoints_require_reference_manage(separate):
    client, _, (p1, p2, _) = separate
    login(client, "admin@example.hu")
    assert client.post("/api/v1/knowledge/merges/preview",
                       json={"survivor_id": p1, "merged_id": p2}).status_code == 403
    assert client.get("/api/v1/knowledge/merges").status_code == 403
    assert client.get(f"/api/v1/knowledge/products/{p1}/texts").status_code == 403


# --- migration 0016 -----------------------------------------------------------------------------


def test_0016_single_head_additive_and_guarded_downgrade():
    versions = BACKEND / "migrations/versions"
    migration = load(next(versions.glob("0016*.py")))
    assert (migration.revision, migration.down_revision) == ("0016", "0015")
    new = {"knowledge_source_relations", "knowledge_merges", "knowledge_texts"}
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(versions.glob("00*.py")):
                if p.name < "0016":
                    load(p).upgrade()
            seed(c)
            before = set(inspect(c).get_table_names())
            columns = {t: {col["name"] for col in inspect(c).get_columns(t)}
                       for t in ("reference_product_sources", "knowledge_observations",
                                 "knowledge_values")}
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - before == new
            assert "lineage_group" in {col["name"] for col in inspect(c).get_columns(
                "reference_product_sources")}
            migration.downgrade()
            assert set(inspect(c).get_table_names()) == before
            assert {t: {col["name"] for col in inspect(c).get_columns(t)}
                    for t in columns} == columns
            migration.upgrade()
            c.execute(text("INSERT INTO reference_product_sources(id,key,name,kind,usage_status,"
                           "usage_basis,enrichment_enabled,contribution,lineage_group,"
                           "excluded_columns,created_at) VALUES (99,'s','S','unas_export',"
                           "'restricted','none',0,'automatic','feed','[]',CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()


def test_cli_recompute_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(kb, "rebuild", lambda db, s, t, recompute=False: calls.append(
        (s, t, recompute)) or {})
    monkeypatch.setattr("app.db.engine", lambda: create_engine("sqlite://"))
    assert kb.main(["rebuild", "--recompute"]) == 0
    assert calls == [(None, None, True)]
