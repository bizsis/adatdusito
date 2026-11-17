"""UNAS-REF-01: UNAS schema registry, parameter definitions, eMAG-UNAS mappings and the
isolated reference store. Synthetic XLSX files only (no commercial data in the repository)."""

import time
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from openpyxl import Workbook
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app.models import Audit, CatalogParameter, ReferenceSource
from app.reference_products import gtin_issues, import_export, lookup
from app.unas_models import (
    ParameterMapping,
    ReferenceImportRun,
    ReferenceProduct,
    ReferenceProductAttribute,
    ReferenceProductIdentifier,
    UnasFieldDefinition,
    UnasParameterDefinition,
)
from app.unas_schema import excluded_from_reference, parse_parameter, registry
from app.unas_views import EmagParameter, convert, propose, template_plan
from conftest import login
from test_access_migration import load
from test_category02a_migration import seed
from unas_export_headers import UNAS_HEADERS

BACKEND = Path(__file__).resolve().parents[1]
SCHEMA = "unas_export/teszt-unas-hu/20261117-084322"
H = {h: i for i, h in enumerate(UNAS_HEADERS)}


@pytest.fixture(autouse=True)
def no_knowledge_broker(monkeypatch):
    """KNOWLEDGE-01 schedules a rebuild after an import; tests have no Celery broker."""
    from app import knowledge

    monkeypatch.setattr(knowledge, "schedule", lambda **kw: None)


def row(**values):
    cells = [None] * len(UNAS_HEADERS)
    for header, value in values.items():
        cells[H[header]] = value
    return cells


def product(sku, name, *eans, brand="Enger", **extra):
    values = {"Cikkszám": sku, "Termék Név": name, "Státusz": 1, "Nettó Ár": 920.4729,
              "Bruttó Ár": 1169, "Kategória": "Non Food I|Háztartás", "Raktárkészlet": 68,
              "Kép link": f"https://shop.example/{sku}.jpg", "Azonosító": 1000 + len(sku),
              "Ár: Csoport B": 959, "Ár típus: Csoport B": "amount",
              "Vásárló csoport láthatja": "Csoport A",
              "Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1": brand}
    for i, ean in enumerate(eans):
        values["Paraméter: EAN||text|1|0|0|0|0|0|||0|1|1" if i == 0
               else f"Paraméter: EAN {i + 1}||text|1|0|0|0|0|0|||0|1|1"] = ean
    values.update(extra)
    return row(**values)


def export(tmp_path, rows, name="UnasShop_teszt-unas-hu_20261117-084322.xlsx"):
    book = Workbook(write_only=True)
    sheet = book.create_sheet("UnasShop Database - 1")
    sheet.append(UNAS_HEADERS)
    for r in rows:
        sheet.append(r)
    path = tmp_path / name
    book.save(path)
    return path


ROWS = [
    product("00123", "Légyirtó 300ML", "5201137061819", "5904517345546", "5201137061819"),
    product("1025829", "Szúnyogirtó", "0590451734554",
            **{"Paraméter: Terméktípus||text|1|0|1|0|0|0|||0|1|1": "Pelenka",
               "Paraméter: Terméktípus|Marketplacek|enummore|1|0|1|0|0|0|||0|1|1": "Konzerv",
               "Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1": "1.5"}),
    product("A-77", "Hibás EAN", "8,71999E+12"),
]


@pytest.fixture
def db(environment):
    _, target, _, _ = environment
    with Session(target) as session:
        yield session


# 1. every column identified --------------------------------------------------------------


def test_all_135_columns_are_identified_and_classified():
    entries = registry(UNAS_HEADERS)
    assert len(entries) == 135 and [e["position"] for e in entries] == list(range(135))
    assert not [e for e in entries if e["scope"] == "unknown"]
    assert sum(e["scope"] == "standard" for e in entries) == 97
    assert sum(e["scope"] == "store_specific" for e in entries) == 38
    assert len({e["field_key"] for e in entries}) == 135
    required = [e["header"] for e in entries if e["requirement"] == "required"]
    assert required == ["Cikkszám", "Termék Név", "Státusz", "Nettó Ár", "Bruttó Ár", "Kategória"]
    assert all(e["requirement_source"] == "unas_help_excerpt"
               for e in entries if e["requirement"] == "required")
    by_header = {e["header"]: e for e in entries}
    assert by_header["Létrehozás"]["importable"] is False  # system generated
    assert by_header["Azonosító"]["importable"] is None  # unknown, not guessed
    assert by_header["Nettó Ár"]["validation"]["time_dependent"] is True


# 2. parameter headers --------------------------------------------------------------------


def test_parameter_headers_are_parsed_losslessly():
    brand = parse_parameter("Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1")
    assert (brand["name"], brand["group_name"], brand["param_type"], brand["unit"]) == (
        "Márka", "", "enum", None)
    width = parse_parameter("Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1")
    assert (width["param_type"], width["unit"], width["unit_source"]) == ("num", "cm",
                                                                           "export_sample")
    for header in [h for h in UNAS_HEADERS if h.startswith("Paraméter: ")]:
        p = parse_parameter(header)
        rebuilt = "Paraméter: " + "|".join([p["name"], p["group_name"], p["param_type"]]
                                            + p["settings"])
        assert rebuilt == header and p["known_type"]
    assert {parse_parameter(h)["param_type"] for h in UNAS_HEADERS
            if h.startswith("Paraméter: ")} == {"text", "num", "enum", "enummore", "link_text"}
    assert parse_parameter("Paraméter: Új||mystery|9|9") ["known_type"] is False
    assert parse_parameter("Cikkszám") is None


# 3. store-specific vs global ---------------------------------------------------------------


def test_store_specific_columns_are_never_global_requirements():
    entries = {e["header"]: e for e in registry(UNAS_HEADERS)}
    for header in ("Ár: Csoport B", "Ár típus: Csoport B", "Vásárló csoport láthatja",
                   "Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1"):
        assert entries[header]["scope"] == "store_specific"
        assert entries[header]["requirement"] == "optional"
    assert excluded_from_reference("Ár: |Csoport E") and excluded_from_reference(
        "Vásárló csoport vásárolhatja")
    assert not excluded_from_reference("Nettó Ár")


# 4-6, 8, 10, 11: import, identifiers, same-name parameters, repeat, isolation ---------------


def test_import_keeps_identifiers_textual_multiple_eans_and_excludes_group_data(db, tmp_path):
    path = export(tmp_path, ROWS + [[None] * 135, product("", "Nincs cikkszám", "1")])
    eMAG_before = db.scalar(select(func.count()).select_from(CatalogParameter))
    sources_before = db.scalar(select(func.count()).select_from(ReferenceSource))
    run = import_export(db, path)
    assert run.state == "partial"
    assert {k: run.counters[k] for k in ("rows", "created", "empty", "errors")} == {
        "rows": 5, "created": 3, "empty": 1, "errors": 1}
    assert run.errors == [{"line": 6, "code": "missing_sku"}]  # row error, rest imported
    first = db.scalar(select(ReferenceProduct).where(ReferenceProduct.source_sku == "00123"))
    assert first.source_sku == "00123" and first.brand == "Enger"  # leading zeros kept
    gtins = list(db.scalars(select(ReferenceProductIdentifier.value).where(
        ReferenceProductIdentifier.product_id == first.id,
        ReferenceProductIdentifier.kind == "gtin").order_by(ReferenceProductIdentifier.position)))
    assert gtins == ["5201137061819", "5904517345546"]  # 3 columns, duplicate EAN once
    second = db.scalar(select(ReferenceProduct).where(ReferenceProduct.source_sku == "1025829"))
    lead = db.scalar(select(ReferenceProductIdentifier).where(
        ReferenceProductIdentifier.product_id == second.id,
        ReferenceProductIdentifier.kind == "gtin"))
    assert lead.value == "0590451734554"  # text, leading zero kept
    broken = db.scalar(select(ReferenceProductIdentifier).join(ReferenceProduct).where(
        ReferenceProduct.source_sku == "A-77", ReferenceProductIdentifier.kind == "gtin"))
    assert broken.value == "8,71999E+12" and not broken.valid and broken.issues == ["non_digit"]
    # Same name, different group: two definitions, two attributes, nothing merged.
    types = list(db.scalars(select(UnasParameterDefinition).where(
        UnasParameterDefinition.name == "Terméktípus")))
    assert sorted(p.group_name for p in types) == ["", "Marketplacek"]
    values = {(a.group_name, a.value_text) for a in db.scalars(
        select(ReferenceProductAttribute).where(ReferenceProductAttribute.product_id == second.id,
                                                ReferenceProductAttribute.name == "Terméktípus"))}
    assert values == {("", "Pelenka"), ("Marketplacek", "Konzerv")}
    # Customer-group data never reaches the reference store; source data is otherwise raw.
    assert not any(k.startswith(("Ár: ", "Ár típus: ", "Vásárló csoport")) for k in first.raw)
    assert first.raw["Nettó Ár"] == 920.4729 and first.raw["Cikkszám"] == "00123"
    from app.unas_models import ReferenceProductSource

    source = db.get(ReferenceProductSource, first.source_id)
    # Owner decision (RC-03): an imported reference export is an active source by default.
    assert (source.usage_status, source.enrichment_enabled, source.usage_basis) == (
        "approved_enrichment", True, "owner_policy:2026-11-17")
    assert first.verification == "unverified"
    assert "Ár: Csoport B" in source.excluded_columns and len(source.excluded_columns) == 12
    # Isolation: no eMAG/catalog or existing reference-source rows written.
    assert db.scalar(select(func.count()).select_from(CatalogParameter)) == eMAG_before
    assert db.scalar(select(func.count()).select_from(ReferenceSource)) == sources_before
    # Repeat: no duplicates, unchanged rows are not rewritten.
    again = import_export(db, path)
    assert (again.counters["created"], again.counters["unchanged"]) == (0, 3)
    assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 3
    assert db.scalar(select(func.count()).select_from(UnasFieldDefinition)) == 135
    assert db.scalar(select(func.count()).select_from(UnasParameterDefinition)) == 26
    changed = ROWS[:]
    changed[1] = product("1025829", "Szúnyogirtó új név", "0590451734554")
    third = import_export(db, export(tmp_path, changed))
    assert (third.counters["updated"], third.counters["unchanged"]) == (1, 2)
    assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 3


def test_gtin_check_digit_validation():
    assert gtin_issues("5201137061819") == [] and gtin_issues("5201137061818") == ["check_digit"]
    assert gtin_issues("12345") == ["invalid_length"] and gtin_issues("8,7E+12") == ["non_digit"]


def test_larger_export_is_streamed(db, tmp_path):
    rows = [product(f"S{i:06d}", f"Termék {i}", None) for i in range(4000)]
    start = time.perf_counter()
    run = import_export(db, export(tmp_path, rows))
    assert run.state == "completed" and run.counters["created"] == 4000
    assert time.perf_counter() - start < 120


def test_sources_active_by_default_admin_restrict_revoke_and_shareable_only(environment,
                                                                          tmp_path):
    client, target, _, _ = environment
    path = export(tmp_path, ROWS)
    with Session(target) as db:
        import_export(db, path)
        source_id = db.scalar(select(ReferenceProduct.source_id).limit(1))
        found = lookup(db, gtin="5904517345546")  # active by default (owner policy)
        assert [f["match"] for f in found] == ["gtin"] and found[0]["confidence"] == 0.95
        assert found[0]["verification"] == "unverified"
        assert "raw" not in found[0] and found[0]["overwrites_supplier_data"] is False
        names = {a["name"] for a in found[0]["attributes"]}
        assert "Márka" in names and not names & {"CONNESTIC_ID", "Forrás"}
        assert lookup(db, brand="ENGER", name="légyirtó 300ml")[0]["match"] == "brand_name"
    login(client)  # superadmin: reference.manage
    r = client.put(f"/api/v1/unas/reference-sources/{source_id}/usage",
                   json={"usage_status": "internal_only", "enrichment_enabled": True,
                         "usage_note": "teszt"})
    assert r.status_code == 422
    r = client.put(f"/api/v1/unas/reference-sources/{source_id}/usage",
                   json={"usage_status": "restricted", "usage_note": "Felhasználás felfüggesztve."})
    assert r.status_code == 200 and r.json()["usage_basis"] == "administrator_decision"
    with Session(target) as db:
        assert lookup(db, gtin="5904517345546") == []  # not permitted: excluded
        assert db.scalar(select(Audit).where(Audit.action == "unas.reference_usage"))
        import_export(db, path)  # a re-import never re-enables a restricted source
        assert lookup(db, gtin="5904517345546") == []
    client.put(f"/api/v1/unas/reference-sources/{source_id}/usage",
               json={"usage_status": "revoked", "usage_note": "visszavonva"})
    with Session(target) as db:
        assert lookup(db, gtin="5904517345546") == []
    login(client, "admin@example.hu")  # tenant admin: no reference.manage
    assert client.get("/api/v1/unas/reference-sources").status_code == 403


def test_shareable_classification_keeps_store_specific_data_out():
    entries = {e["header"]: e for e in registry(UNAS_HEADERS)}
    for header in ("Termék Név", "Rövid Leírás", "Tulajdonságok", "Kép link", "Tömeg",
                   "Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1",
                   "Paraméter: EAN||text|1|0|0|0|0|0|||0|1|1"):
        assert entries[header]["shareable"], header
    for header in ("Cikkszám", "Nettó Ár", "Raktárkészlet", "Ár: Csoport B",
                   "Vásárló csoport láthatja", "Azonosító", "Létrehozás", "SEO Title",
                   "Paraméter: CONNESTIC_ID|Connestic|text|0|0|0|0|0|0|||0|1|0",
                   "Paraméter: Forrás|Connestic|text|0|0|0|0|0|0|||0|1|0"):
        assert not entries[header]["shareable"], header


# 7. eMAG-UNAS mappings ----------------------------------------------------------------------


def test_emag_unas_mapping_proposals_approval_and_units(environment, tmp_path):
    client, target, _, _ = environment
    with Session(target) as db:
        import_export(db, export(tmp_path, ROWS))
        created = propose(db, SCHEMA, [
            {"category_id": 10, "parameter_id": 1, "name": "Brand"},
            {"category_id": 10, "parameter_id": 2, "name": "Width", "unit": "mm"},
            {"category_id": 10, "parameter_id": 3, "name": "Terméktípus"},  # ambiguous
            {"category_id": 10, "parameter_id": 4, "name": "Color"},  # unknown
        ])
        db.commit()
        got = {m.emag_parameter_name: m for m in created}
        assert set(got) == {"Brand", "Width"}
        assert all(m.status == "proposed" and m.origin == "automatic" for m in created)
        assert got["Width"].unit_factor == Decimal("0.1") and convert("15", got["Width"]) == "1.5"
        assert propose(db, SCHEMA, [{"category_id": 10, "parameter_id": 1, "name": "Brand"}]) == []
        brand_id = got["Brand"].id
        field_id = db.scalar(select(UnasFieldDefinition.id).where(
            UnasFieldDefinition.header == "Tömeg"))
    login(client, "reviewer@example.hu")
    assert client.post(f"/api/v1/unas/parameter-mappings/{brand_id}/approve",
                       json={}).status_code == 403
    login(client)
    r = client.post(f"/api/v1/unas/parameter-mappings/{brand_id}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/v1/unas/parameter-mappings/{brand_id}/reject",
                       json={}).status_code == 409
    manual = client.post("/api/v1/unas/parameter-mappings", json={
        "emag_parameter_id": 5, "emag_parameter_name": "Weight", "unas_field_id": field_id,
        "unit_from": "g", "unit_to": "kg"})
    assert manual.status_code == 200 and manual.json()["origin"] == "manual"
    assert manual.json()["status"] == "proposed" and manual.json()["unit_factor"] == "0.0010000000"
    assert client.post("/api/v1/unas/parameter-mappings", json={
        "emag_parameter_id": 6, "emag_parameter_name": "X", "unas_field_id": field_id,
        "unas_parameter_id": 1}).status_code == 422
    assert client.get("/api/v1/unas/parameter-mappings?status=approved").json()[0]["id"] == brand_id


# 12. template generator compatibility -------------------------------------------------------


def test_template_plan_order_without_duplicates(environment, tmp_path):
    client, target, _, _ = environment
    with Session(target) as db:
        import_export(db, export(tmp_path, ROWS))
        brand = propose(db, SCHEMA, [{"category_id": 10, "parameter_id": 1, "name": "Brand"}])[0]
        brand.status = "approved"
        db.commit()
        columns = template_plan(db, SCHEMA, ["SKU", "NAME", "Saját oszlop"], [
            EmagParameter(category_id=10, parameter_id=1, name="Brand"),
            EmagParameter(category_id=10, parameter_id=9, name="Szín"),
        ])
    sources = [c["source"] for c in columns]
    assert sources == sorted(sources, key=["supplier", "unas", "emag"].index)
    headers = [c["header"] for c in columns]
    assert headers[:3] == ["SKU", "NAME", "Saját oszlop"]  # supplier columns unchanged, first
    assert "Cikkszám" not in headers and "Termék Név" not in headers  # covered by SKU / NAME
    assert {"Nettó Ár", "Bruttó Ár", "Kategória", "Státusz"} <= set(headers)
    assert not any(h.startswith(("Ár: ", "Vásárló csoport")) for h in headers)
    assert "Paraméter: Márka||enum|0|0|0|0|0|0|||0|1|1" in headers  # approved mapping
    assert "eMAG: Szín" in headers and len(headers) == len(set(headers))
    login(client)
    r = client.post("/api/v1/unas/template-plan", json={
        "schema_source": SCHEMA, "supplier_headers": ["Cikkszám"], "emag_parameters": []})
    assert r.status_code == 200 and [c["header"] for c in r.json()["columns"]].count(
        "Cikkszám") == 1
    assert client.get(f"/api/v1/unas/fields?schema_source={SCHEMA}&requirement=required"
                      ).status_code == 200


# migration -----------------------------------------------------------------------------------


def test_single_alembic_head_and_0013_chain():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    # The complete graph is validated only after Claude's real 0014 is integrated.
    # Missing 0014 remains an actual failure; no placeholder or skipped CI check.
    assert len(script.get_heads()) == 1
    assert script.get_revision("0015").down_revision == "0014"
    assert script.get_revision("0014").down_revision == "0013"
    assert script.get_revision("0013").down_revision == "0012"


def test_0013_is_additive_and_downgrade_is_guarded():
    new = {"unas_field_definitions", "unas_parameter_definitions", "parameter_mappings",
           "reference_product_sources", "reference_import_runs", "reference_products",
           "reference_product_identifiers", "reference_product_attributes"}
    e = create_engine("sqlite://")
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted((BACKEND / "migrations/versions").glob("00*.py")):
                if p.name < "0013":
                    load(p).upgrade()
            seed(c)
            before = set(inspect(c).get_table_names())
            products = c.scalar(text("SELECT COUNT(*) FROM supplier_products"))
            migration = load(next((BACKEND / "migrations/versions").glob("0013*.py")))
            migration.upgrade()
            assert set(inspect(c).get_table_names()) - before == new
            assert c.scalar(text("SELECT COUNT(*) FROM supplier_products")) == products
            migration.downgrade()
            assert set(inspect(c).get_table_names()) == before
            migration.upgrade()
            c.execute(text("INSERT INTO reference_product_sources(id,key,name,kind,usage_status,"
                           "enrichment_enabled,excluded_columns,usage_decided_by,created_at) "
                           "VALUES (1,'k','n','unas_export','approved_enrichment',1,'[]',1,"
                           "CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="backup"):
                migration.downgrade()
