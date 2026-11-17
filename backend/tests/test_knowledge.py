"""KNOWLEDGE-01: identification, cross-source linking, value comparison, conflicts,
confidence, learning from approvals and mappings, reuse, permissions and traceability.
Synthetic data only."""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app import knowledge as kb
from app.import_models import SupplierProduct
from app.knowledge_models import (
    KnowledgeConflict,
    KnowledgeEvent,
    KnowledgeLink,
    KnowledgeObservation,
    KnowledgeValue,
)
from app.models import Audit
from app.product_models import ProductParameterValue
from app.reference_products import import_export
from app.unas_models import ParameterMapping, ReferenceProductSource, UnasParameterDefinition
from conftest import login
from test_access_migration import load
from test_category02a_migration import seed
from test_supplier_import import approve, imports, upload, work  # noqa: F401
from test_unas_reference import export, product

BACKEND = Path(__file__).resolve().parents[1]
WIDTH = "Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1"
EAN_A, EAN_B, EAN_C = "5201137061819", "5904517345546", "4006381333931"
WIDTH_PARAM = 6511  # eMAG "Szélesség (mm)"


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    monkeypatch.setattr(kb, "schedule", lambda **kw: None)


@pytest.fixture
def world(imports, tmp_path):
    """One permitted reference export and one tenant import of overlapping products."""
    client, target, supplier = imports
    with Session(target) as db:
        import_export(db, export(tmp_path, [
            product("R-1", "Mosógép 7kg", EAN_A, brand="Acme", **{WIDTH: "60"}),
            product("R-2", "Porszívó", EAN_B, brand="Acme", **{WIDTH: "30"}),
            product("R-3", "Hibás kód", "8,71999E+12", brand="Other"),
        ]))
        width = db.scalar(select(UnasParameterDefinition).where(
            UnasParameterDefinition.name == "Szélesség"))
        # Learning from mappings: UNAS "Szélesség" (cm) is eMAG parameter 6511.
        db.add(ParameterMapping(mapping_key="k1", emag_parameter_id=WIDTH_PARAM,
                                emag_parameter_name="Szélesség (mm)",
                                unas_parameter_id=width.id, status="approved",
                                origin="manual"))
        db.commit()
    csv = ("SKU;NAME;EAN;BRAND;MPN;PRICE;QUANTITY\n"
           f"T-1;Mosógép hétkilós;{EAN_A};ACME;WM-7;199990;5\n"
           f"T-2;Porszívó;{EAN_B};Acme;VC-1;49990;2\n"
           "T-3;Kávéfőző;;Acme;CM-9;29990;1\n").encode()
    run = upload(client, supplier, csv)
    work(target, run)
    approve(client, run, {"0": "sku", "1": "name", "2": "gtin", "3": "brand", "4": "mpn",
                          "5": "price", "6": "stock"}, financial_approved=True)
    work(target, run)
    return client, target


def tenant_product(db, sku):
    return next(p for p in db.scalars(select(SupplierProduct)) if p.data.get("sku") == sku)


def set_parameter(db, sku, value, user=False, unit="mm"):
    p = tenant_product(db, sku)
    row = db.get(ProductParameterValue, (p.id, f"emag:{WIDTH_PARAM}"))
    if row is None:
        row = ProductParameterValue(product_id=p.id, slot_key=f"emag:{WIDTH_PARAM}",
                                    tenant_id=p.tenant_id, emag_parameter_id=WIDTH_PARAM,
                                    name="Szélesség (mm)", state="present", origin="source",
                                    reason_codes=[], details={}, rule_version="t")
        db.add(row)
    row.value, row.unit = value, unit
    row.origin, row.locked = ("user", True) if user else ("source", False)
    db.commit()


def value_of(db, sku, key):
    p = tenant_product(db, sku)
    link = db.scalar(select(KnowledgeLink).where(KnowledgeLink.member_kind == "supplier_product",
                                                 KnowledgeLink.member_id == p.id))
    return db.scalar(select(KnowledgeValue).where(
        KnowledgeValue.knowledge_product_id == link.knowledge_product_id,
        KnowledgeValue.attribute_key == key))


def test_identification_links_sources_by_gtin_mpn_brand_name(world):
    _, target = world
    with Session(target) as db:
        counters = kb.rebuild(db)
        assert counters["linked"] == 6 and counters["sources"] == 2
        links = {(link.member_kind, link.member_id): link for link in db.scalars(
            select(KnowledgeLink))}
        t1 = links[("supplier_product", tenant_product(db, "T-1").id)]
        same = [link for link in links.values() if
                link.knowledge_product_id == t1.knowledge_product_id]
        assert {link.member_kind for link in same} == {"reference_product", "supplier_product"}
        assert t1.method == "gtin" and t1.confidence == Decimal("1")
        # Invalid GTIN never identifies; brand+name still does (own cluster here).
        assert len({link.knowledge_product_id for link in links.values()}) == 4
        tenant = db.scalar(select(ReferenceProductSource).where(
            ReferenceProductSource.kind == "tenant_import"))
        assert tenant.tenant_id == 1 and kb.permitted(tenant)
        # Shareable knowledge only: never price, stock or the store SKU.
        keys = set(db.scalars(select(KnowledgeObservation.attribute_key).distinct()))
        assert keys == {"brand", f"emag:{WIDTH_PARAM}"}
        # Brand "ACME" and "Acme" agree after normalisation.
        brand = value_of(db, "T-1", "brand")
        assert brand.status == "candidate" and brand.support_sources == 2
        # Idempotent: a second run changes nothing.
        events = db.scalar(select(func.count()).select_from(KnowledgeEvent))
        again = kb.rebuild(db)
        assert again["observations_changed"] == 0
        assert db.scalar(select(func.count()).select_from(KnowledgeEvent)) == events


def test_brand_mpn_identity_and_merge_candidate_never_automatic(world):
    _, target = world
    with Session(target) as db:
        kb.rebuild(db)
        p3 = tenant_product(db, "T-3")
        link = db.scalar(select(KnowledgeLink).where(KnowledgeLink.member_id == p3.id,
                                                     KnowledgeLink.member_kind ==
                                                     "supplier_product"))
        # T-3 gains the GTIN of another cluster: linked by its strongest key, no merge.
        p3.data = {**p3.data, "gtin": EAN_B}
        db.commit()
        kb.rebuild(db, tenant_id=1)
        db.refresh(link)
        candidates = list(db.scalars(select(KnowledgeEvent).where(
            KnowledgeEvent.kind == "merge_candidate")))
        assert candidates and len(candidates[0].details["clusters"]) == 2
        assert db.scalar(select(func.count()).select_from(KnowledgeLink).where(
            KnowledgeLink.knowledge_product_id == link.knowledge_product_id)) >= 1


def test_unit_normalised_agreement_raises_confidence_but_never_verifies(world):
    _, target = world
    with Session(target) as db:
        set_parameter(db, "T-1", "600")  # 600 mm == reference 60 cm
        kb.rebuild(db)
        v = value_of(db, "T-1", f"emag:{WIDTH_PARAM}")
        assert v.value_norm == "num:60:cm" and v.status == "candidate"
        assert v.support_sources == 2
        assert Decimal("0.6") < v.confidence < Decimal("0.95")  # 1-(1-0.6)(1-0.5)=0.8
        assert v.confidence == Decimal("0.8000")


def test_conflict_detected_and_resolved_by_administrator(world):
    client, target = world
    with Session(target) as db:
        set_parameter(db, "T-2", "450")  # reference says 30 cm
        kb.rebuild(db)
        v = value_of(db, "T-2", f"emag:{WIDTH_PARAM}")
        assert v.status == "conflict"
        conflict = db.scalar(select(KnowledgeConflict).where(KnowledgeConflict.value_id == v.id))
        assert conflict.state == "open" and conflict.kind == "values_differ"
        assert {c["value_norm"] for c in conflict.candidates} == {"num:30:cm", "num:45:cm"}
        conflict_id, value_id = conflict.id, v.id
    login(client, "admin@example.hu")
    assert client.get("/api/v1/knowledge/conflicts").status_code == 403  # tenant admin
    login(client)  # superadmin: reference.manage
    listed = client.get("/api/v1/knowledge/conflicts").json()
    assert [c["id"] for c in listed] == [conflict_id]
    assert client.post(f"/api/v1/knowledge/conflicts/{conflict_id}/resolve",
                       json={"value_norm": "num:99:cm"}).status_code == 422
    r = client.post(f"/api/v1/knowledge/conflicts/{conflict_id}/resolve",
                    json={"value_norm": "num:30:cm", "reason": "Gyártói adatlap."})
    assert r.status_code == 200 and r.json()["state"] == "resolved"
    assert r.json()["value"]["status"] == "verified"
    assert r.json()["value"]["verification_basis"] == "admin_decision"
    with Session(target) as db:
        kb.rebuild(db)  # the decision survives; the differing claim stays a challenge
        v = db.get(KnowledgeValue, value_id)
        assert v.status == "verified" and v.value_norm == "num:30:cm"
        assert db.scalar(select(KnowledgeConflict).where(
            KnowledgeConflict.value_id == value_id, KnowledgeConflict.state == "open")).kind == \
            "verified_challenged"
        assert db.scalar(select(Audit).where(Audit.action == "knowledge.resolve"))
    detail = client.get(f"/api/v1/knowledge/products/{v.knowledge_product_id}").json()
    width = next(x for x in detail["values"] if x["attribute_key"] == f"emag:{WIDTH_PARAM}")
    assert {o["source_key"] for o in width["observations_detail"]} >= {"tenant:1"}
    kinds = [e["kind"] for e in client.get(
        f"/api/v1/knowledge/products/{v.knowledge_product_id}/events").json()]
    assert {"linked", "conflict_opened", "value_verified", "conflict_resolved"} <= set(kinds)


def test_learning_from_approved_correction_and_rejection(world):
    client, target = world
    with Session(target) as db:
        set_parameter(db, "T-1", "590", user=True)  # a tenant user corrected and locked it
        kb.rebuild(db)
        v = value_of(db, "T-1", f"emag:{WIDTH_PARAM}")
        assert (v.status, v.verification_basis, v.value_norm) == (
            "verified", "approved_correction", "num:59:cm")
        assert db.scalar(select(KnowledgeConflict).where(
            KnowledgeConflict.value_id == v.id)).kind == "verified_challenged"
        brand = value_of(db, "T-2", "brand")
        brand_id = brand.id
    login(client)
    r = client.post(f"/api/v1/knowledge/values/{brand_id}/reject", json={"reason": "teszt"})
    assert r.status_code == 200 and "txt:acme" in r.json()["rejected_values"]
    assert r.json()["value_norm"] is None  # no other candidate left
    with Session(target) as db:
        kb.rebuild(db)
        assert db.get(KnowledgeValue, brand_id).value_norm is None  # never offered again


def test_enrichment_plan_reuses_knowledge_and_avoids_research(world):
    client, target = world
    with Session(target) as db:
        set_parameter(db, "T-1", "600")
        kb.rebuild(db)
        width = value_of(db, "T-1", f"emag:{WIDTH_PARAM}")
        kb.verify_value(db, width, 1, reason="adatlap")
        db.commit()
        set_parameter(db, "T-2", "450")
        kb.rebuild(db)
    login(client, "admin@example.hu")  # a tenant user with products.read
    plan = client.post("/api/v1/knowledge/enrichment-plan", json={
        "gtin": EAN_A, "attributes": [f"emag:{WIDTH_PARAM}", "brand", "emag:1"],
        "threshold": "0.7"}).json()
    assert plan["match"] == "gtin"
    assert [x["attribute_key"] for x in plan["reuse"]] == [f"emag:{WIDTH_PARAM}"]
    assert [x["attribute_key"] for x in plan["suggest"]] == ["brand"]
    assert plan["research"] == [{"attribute_key": "emag:1", "reason": "unknown"}]
    assert plan["research_avoided"] == 2
    assert "observations_detail" not in str(plan) and "tenant" not in str(plan)
    conflict = client.post("/api/v1/knowledge/enrichment-plan", json={
        "gtin": EAN_B, "attributes": [f"emag:{WIDTH_PARAM}"]}).json()
    assert conflict["research"][0]["reason"] == "conflict"
    assert client.post("/api/v1/knowledge/enrichment-plan",
                       json={"attributes": ["brand"]}).status_code == 422
    unknown = client.post("/api/v1/knowledge/enrichment-plan", json={
        "gtin": EAN_C, "attributes": ["brand"]}).json()
    assert unknown["knowledge_product_id"] is None and unknown["research_avoided"] == 0


def test_permission_withdrawal_and_manual_unlink(world):
    client, target = world
    with Session(target) as db:
        set_parameter(db, "T-1", "600")
        kb.rebuild(db)
        tenant = db.scalar(select(ReferenceProductSource).where(
            ReferenceProductSource.kind == "tenant_import"))
        tenant.usage_status, tenant.enrichment_enabled = "restricted", False
        db.commit()
        counters = kb.rebuild(db)
        assert counters["withdrawn"] == 3
        v = value_of(db, "T-1", f"emag:{WIDTH_PARAM}")
        assert v.support_sources == 1 and v.confidence == Decimal("0.6000")
        assert not db.scalar(select(func.count()).select_from(KnowledgeObservation).where(
            KnowledgeObservation.source_id == tenant.id, KnowledgeObservation.current.is_(True)))
        link = db.scalar(select(KnowledgeLink).where(
            KnowledgeLink.member_kind == "reference_product"))
        old_product, link_id = link.knowledge_product_id, link.id
    login(client)
    r = client.post(f"/api/v1/knowledge/links/{link_id}/unlink", json={"reason": "nem azonos"})
    assert r.status_code == 200 and r.json()["knowledge_product_id"] != old_product
    with Session(target) as db:
        kb.rebuild(db)
        moved = db.get(KnowledgeLink, link_id)
        assert moved.knowledge_product_id == r.json()["knowledge_product_id"]  # not re-linked
        assert moved.decided_by == 1 and moved.method == "manual"
    stats = client.get("/api/v1/knowledge/stats").json()
    assert {s["kind"] for s in stats["sources"]} == {"unas_export", "tenant_import"}
    assert client.post("/api/v1/knowledge/rebuild", json={"tenant_id": 1}).json()["queued"] is \
        False


def test_same_brand_and_name_within_one_source_are_variants_not_one_product(imports,
                                                                            tmp_path):
    _, target, _ = imports
    with Session(target) as db:
        import_export(db, export(tmp_path, [
            product("V-S", "Póló", None, brand="Acme", **{WIDTH: "40"}),
            product("V-L", "Póló", None, brand="Acme", **{WIDTH: "60"}),
            product("D-1", "Duplikált", EAN_C, brand="Acme"),
            product("D-2", "Duplikált másik SKU", EAN_C, brand="Acme"),
        ]))
        kb.rebuild(db)
        clusters = {}
        for link in db.scalars(select(KnowledgeLink)):
            clusters.setdefault(link.knowledge_product_id, []).append(link.member_id)
        assert sorted(len(m) for m in clusters.values()) == [1, 1, 2]  # GTIN may join
        assert not db.scalar(select(func.count()).select_from(KnowledgeConflict))


def test_normalisation_and_confidence_rules():
    assert kb.normalize("1,5", "m") == ("num:150:cm", "150 cm")
    assert kb.normalize(" Fehér  ", None)[0] == "txt:feher"
    assert kb.label_unit("Szélesség (mm)") == "mm"
    assert kb.combine([Decimal("0.6"), Decimal("0.6"), Decimal("0.6")]) == Decimal("0.9360")
    assert kb.combine([Decimal("0.9")] * 5) == Decimal("0.95")  # capped: never certainty


def test_0014_chain_additive_and_guarded_downgrade():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0015"]
    assert [r.revision for r in script.iterate_revisions("0015", "0010")] == [
        "0015", "0014", "0013", "0012", "0011"]
    new = {"knowledge_products", "knowledge_identities", "knowledge_links",
           "knowledge_observations", "knowledge_values", "knowledge_conflicts",
           "knowledge_events"}
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted((BACKEND / "migrations/versions").glob("00*.py")):
                if p.name < "0014":
                    load(p).upgrade()
            seed(c)
            before = set(inspect(c).get_table_names())
            migration = load(next((BACKEND / "migrations/versions").glob("0014*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - before == new
            migration.downgrade()
            assert set(inspect(c).get_table_names()) == before
            migration.upgrade()
            c.execute(text("INSERT INTO knowledge_products(id,status,created_at,updated_at) "
                           "VALUES (1,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            c.execute(text("INSERT INTO knowledge_values(id,knowledge_product_id,attribute_key,"
                           "attribute_label,status,confidence,support_sources,observations,"
                           "verified_by,rejected_values,updated_at) VALUES (1,1,'brand','Márka',"
                           "'verified',1,1,1,1,'[]',CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()



def test_admin_tenant_source_reports_supplier_counts_and_safe_history(world):
    client, target = world
    with Session(target) as db:
        set_parameter(db, "T-1", "600")
        kb.rebuild(db)
        source = db.scalar(select(ReferenceProductSource).where(ReferenceProductSource.kind == "tenant_import"))
        source_id = source.id
    login(client)
    source = client.get(f"/api/v1/knowledge-admin/sources/{source_id}").json()
    assert source["products"] == 3
    assert source["parameters"] == 1 and source["attribute_values"] == 1
    assert source["quality"]["valid_gtin_products"] == 2
    assert source["quality"]["with_name"] == 3
    assert source["last_import"]["engine"] == "supplier"
    history = client.get(f"/api/v1/knowledge-admin/sources/{source_id}/imports").json()
    assert history["total"] == 1
    row = history["items"][0]
    assert row["engine"] == "supplier" and not row["uploaded"] and not row["retryable"]
    assert row["preview"] == [] and row["parser"] == {}
    assert "199990" not in str(row) and "49990" not in str(row)
