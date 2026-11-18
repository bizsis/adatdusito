"""TEMPLATE-PREP-01: template preparation (Import -> Előkészítés -> Sablonkészítés).
Synthetic data only; no AI, no eMAG lookup, no export, no pinfo_db."""

from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import template_prep as tp
from app.import_mapping import parameter_header
from app.import_models import ImportChunk, ImportProfile, ImportRun, SupplierProduct
from app.models import Audit
from conftest import login
from test_supplier_import import approve, imports, upload, work  # noqa: F401

BASE = "/api/v1/imports"
FIXTURES = Path(__file__).parent / "fixtures"
CSV = ("SKU;Megnevezés;Kategória;EAN;Color;Unknown_01;Kép 1;Kép 2;Raktár A;Raktár B;"
       "Nettó ár;LastInitialCost;Státusz\n"
       "A-1;Mosógép;Gépek;5901234123457;Fekete;x;https://k.hu/1.jpg;https://k.hu/2.jpg;5;0;"
       "1000;700;\n"
       "A-2;Porszívó;Gépek;0012345678905;;;https://k.hu/3.jpg;;0;2;;400;0\n"
       "A-3;Vasaló;;4006381333931;;;;;1;1;3000;;1\n").encode()


def prepared(c, t, s, content=CSV, filename="data.csv", **params):
    run_id = upload(c, s, content, filename)
    work(t, run_id)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = c.get(f"{BASE}/runs/{run_id}/template-preparation?{query}")
    assert r.status_code == 200, r.text
    return run_id, r.json()


def columns_of(view, override=None):
    """Every column with its current assignment (template/auto), plus overrides."""
    out = []
    for col in view["columns"]:
        a = col["assignment"]
        item = {"index": col["index"], "state": a["state"] if a else None,
                "target": a["target"] if a else None}
        item.update((override or {}).get(col["index"], {}))
        out.append(item)
    return out


def mapped(key, **extra):
    return {"state": "mapped", "target": {"key": key, **extra}}


COLOR = {"state": "mapped", "target": {"key": "parameter", "parameter": {
    "name": "Szín", "param_type": "text", "group_name": "", "unit": None}}}


def full_body(view, **extra):
    cols = columns_of(view, {
        4: COLOR, 5: {"state": "unused", "target": None}, 6: mapped("kep"), 7: mapped("kep"),
        8: mapped("raktarkeszlet"), 9: mapped("raktarkeszlet"), 10: mapped("netto_ar"),
        11: {"state": "unused", "target": None}, 12: mapped("statusz")})
    return {"engine": "unas", "currency": "HUF", "columns": cols,
            "new_parameters": [{"name": "Szín", "param_type": "text", "approved": True}],
            **extra}


def save(c, run_id, body, name="Alap", **extra):
    return c.post(f"{BASE}/import-templates", json={**body, "run_id": run_id, "name": name,
                                                     **extra})


def test_target_list_is_exactly_the_operator_list():
    labels = [t["label"] for t in tp.targets_payload()["targets"]]
    assert labels == [
        "Cikkszám", "Termék megnevezés", "Kategória", "Alternatív kategória", "Gyártó",
        "Raktárkészlet #0", "Nettó ár", "Bruttó ár", "Nettó akciós ár", "Bruttó akciós ár",
        "Akció kezdete", "Akció vége", "ÁFA", "EAN", "Gyártói cikkszám", "Részletes leírás",
        "Rövid leírás", "Mennyiségi egység", "Másodlagos egység", "Másodlagos mennyiség",
        "Min. rendelhető mennyiség", "Lépésköz", "Státusz", "Tömeg",
        "Termék összevonás alapja", "Export tiltás", "Kép", "További lapfül 1",
        "További lapfül 2", "További lapfül 3", "Kiegészítő termékek", "Hasonló termékek",
        "Paraméter"]
    payload = tp.targets_payload()
    assert payload["default_currency"] == "HUF" and payload["defaults"] == {
        "statusz": "1", "afa": "27"}
    assert payload["currencies"] == ["HUF", "EUR", "USD", "GBP", "CHF", "CZK", "PLN",
                                     "RON", "BGN", "RSD", "UAH"]
    targets = {t["key"]: t for t in payload["targets"]}
    assert [k for k, t in targets.items() if t["required"]] == ["cikkszam"]
    assert targets["termek_megnevezes"]["unas_header"] == "Termék Név"
    assert {k: t["multiple"] for k, t in targets.items() if t["multiple"]} == {
        "alternativ_kategoria": "instances", "raktarkeszlet": "instances", "kep": "ordered",
        "parameter": "instances"}


def test_full_column_list_one_sample_and_recognition(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    assert [col["header"] for col in view["columns"]][:4] == ["SKU", "Megnevezés",
                                                              "Kategória", "EAN"]
    assert len(view["columns"]) == 13 and view["file"]["data_rows"] == 3
    by = {col["header"]: col for col in view["columns"]}
    assert by["SKU"]["sample"] == "A-1" and by["Státusz"]["sample"] == "0"  # first non-empty
    assert by["EAN"]["sample"] == "5901234123457"
    assert by["SKU"]["assignment"] == {"state": "mapped", "target": {"key": "cikkszam"}}
    assert by["Kép 1"]["assignment"]["target"] == {"key": "kep"}
    assert by["Kép 2"]["assignment"]["target"] == {"key": "kep"}
    # Prices are only suggested; a purchase price is never proposed as a sale price.
    assert by["Nettó ár"]["assignment"] is None
    assert by["Nettó ár"]["suggestion"]["target"] == {"key": "netto_ar"}
    assert by["LastInitialCost"]["suggestion"] is None
    # The program never marks a column "unused"; unknown columns stay undecided.
    assert all((col["assignment"] or {}).get("state") != "unused" for col in view["columns"])
    assert by["Unknown_01"]["assignment"] is None and by["Unknown_01"]["suggestion"] is None
    assert by["Color"]["suggestion"]["target"]["parameter"]["name"] == "Szín"
    assert by["Color"]["assignment"] is None  # a new parameter needs the operator


def test_new_parameter_requires_operator_approval(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    body = full_body(view)
    body["new_parameters"] = [{"name": "Szín", "approved": False}]
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert any(e["code"] == "parameter_not_approved" for e in r["errors"])
    body["new_parameters"] = [{"name": "Szín", "approved": True}]
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert r["valid"], r["errors"]
    assert r["parameters_to_create"] == [{"name": "Szín", "header": parameter_header("Szín")}]
    saved = save(c, run_id, body)
    assert saved.status_code == 200, saved.text
    # The approved parameter is reused later without a new approval.
    run2, view2 = prepared(c, t, s)
    assert {"name": "Szín", "header": parameter_header("Szín")} in view2["approved_parameters"]
    with Session(t) as db:
        actions = list(db.scalars(select(Audit.action)))
        assert actions.count("import.parameter_approved") == 1


def test_multi_targets_and_image_order(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    body = full_body(view)
    body["columns"][6] |= mapped("kep", order=2)
    body["columns"][7] |= mapped("kep", order=1)
    body["columns"][2] |= mapped("alternativ_kategoria")
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert r["valid"], r["errors"]
    resolved = {x["index"]: x for x in r["resolved"]}
    assert resolved[6]["target"]["order"] == 2 and resolved[7]["target"]["order"] == 1
    assert resolved[8]["unas_header"] == "Raktárkészlet"
    assert resolved[9]["unas_header"] == "Raktárkészlet #1"
    assert resolved[2]["unas_header"] == "Alternatív Kategória 1"
    saved = save(c, run_id, body).json()
    with Session(t) as db:
        profile = db.get(ImportProfile, saved["id"])
        # The first image (order 1) feeds the internal images field.
        assert profile.config["mapping"]["7"] == "images"
        assert "6" not in profile.config["mapping"]
    # Non-multiple targets may not take two columns; the same image order is a duplicate.
    body["columns"][1] |= mapped("cikkszam")
    body["columns"][6] |= mapped("kep", order=1)
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    codes = [(e["code"], e["target"]) for e in r["errors"]]
    assert ("duplicate_target", "cikkszam") in codes and ("duplicate_target", "kep") in codes


def test_status_vat_defaults_and_price_rules(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    body = full_body(view)
    body["columns"][12] |= {"state": "unused", "target": None}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    fields = {f["key"]: f for f in r["fields"]}
    assert fields["statusz"] == {"key": "statusz", "status": "default", "value": "1"}
    assert fields["afa"] == {"key": "afa", "status": "default", "value": "27"}
    assert fields["brutto_ar"] == {"key": "brutto_ar", "status": "computed",
                                   "rule": "gross_from_net_vat"}
    assert fields["netto_akcios_ar"]["status"] == "empty"
    assert fields["akcio_kezdete"]["status"] == "empty"
    assert {"code": "price_rows_missing", "count": 1} in r["warnings"]
    assert not r["price_missing"]
    # No sale price at all: the template is still savable and flags the gap.
    body["columns"][10] |= {"state": None, "target": None}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert r["valid"] and r["price_missing"]
    assert {"key": "netto_ar", "status": "missing"} in r["fields"]
    saved = save(c, run_id, body).json()
    assert saved["price_missing"] is True
    # A purchase price mapped by the operator as sale price is warned about.
    body["columns"][11] |= mapped("netto_ar")
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert any(w["code"] == "purchase_price_as_sale_price" for w in r["warnings"])
    body["defaults"] = {"statusz": "2", "afa": "27"}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert {"code": "invalid_default"} in r["errors"]


def test_currency_choice_and_mismatch_warning(imports):
    c, t, s = imports
    content = b"SKU;Price;Currency\nA;10;EUR\nB;20;EUR\n"
    run_id, view = prepared(c, t, s, content, currency="HUF")
    assert {"code": "currency_mismatch", "columns": [2], "values": ["EUR"]} in view["warnings"]
    _, view = prepared(c, t, s, content, currency="EUR")
    assert view["warnings"] == []
    r = c.get(f"{BASE}/runs/{run_id}/template-preparation?currency=XYZ")
    assert r.status_code == 422 and r.json()["error"]["reason"] == "unsupported_currency"


def test_several_templates_per_supplier_recognition_and_versions(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    first = save(c, run_id, full_body(view), name="Alap").json()
    assert first["version"] == 1
    other = upload(c, s, b"Code;Title;Gross\nX;Y;10\n")
    work(t, other)
    v_other = c.get(f"{BASE}/runs/{other}/template-preparation").json()
    assert v_other["template"] is None  # different structure
    body = {"engine": "unas", "currency": "EUR", "columns": columns_of(
        v_other, {0: mapped("cikkszam"), 1: mapped("termek_megnevezes"),
                  2: mapped("brutto_ar")})}
    assert save(c, other, body, name="Alap").status_code == 409  # name taken
    second = save(c, other, body, name="Akciós").json()
    listed = c.get(f"{BASE}/suppliers/{s}/import-templates").json()
    assert {x["name"] for x in listed["templates"]} == {"Alap", "Akciós"}
    # A new upload with the first structure loads the best match automatically.
    run3, view3 = prepared(c, t, s)
    assert view3["template"]["id"] == first["id"] and view3["template"]["score"] == 1.0
    assert all(col["status"] == "from_template" for col in view3["columns"])
    assert view3["columns"][4]["assignment"]["target"]["key"] == "parameter"
    # A new version keeps the old one.
    body3 = full_body(view3)
    body3["columns"][5] |= mapped("rovid_leiras")
    v2 = save(c, run3, body3, name="Alap", template_id=first["id"]).json()
    assert v2["version"] == 2 and v2["template_key"] == first["template_key"]
    versions = c.get(f"{BASE}/import-templates/{v2['id']}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert c.get(f"{BASE}/import-templates/{first['id']}").json()["version"] == 1
    assert second["template_key"] != first["template_key"]


def test_changed_structure_keeps_mapping_and_marks_only_changes(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    tpl = save(c, run_id, full_body(view)).json()
    changed = CSV.decode().replace("Unknown_01", "Garancia").replace(";Státusz\n", ";Áfa\n")
    run2, view2 = prepared(c, t, s, changed.encode())
    assert view2["template"]["id"] == tpl["id"]
    assert view2["template"]["missing_headers"] == ["Státusz", "Unknown_01"]
    assert view2["template"]["new_headers"] == ["Garancia", "Áfa"]
    status = {col["header"]: col["status"] for col in view2["columns"]}
    assert status["SKU"] == "from_template" and status["Garancia"] == "new"
    assert status["Áfa"] == "new"
    by = {col["header"]: col for col in view2["columns"]}
    assert by["SKU"]["assignment"]["target"] == {"key": "cikkszam"}
    assert by["Áfa"]["assignment"]["target"] == {"key": "afa"}  # new column, recognized


def test_template_save_never_processes_products(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    assert save(c, run_id, full_body(view)).status_code == 200
    with Session(t) as db:
        run = db.get(ImportRun, run_id)
        assert run.state == "awaiting_approval" and run.approved_by is None
        assert not db.scalar(select(func.count()).select_from(SupplierProduct))
        profile = db.scalars(select(ImportProfile)).one()
        assert profile.config["automatic"] is False
    # A later upload with the same structure is still not processed automatically.
    run2 = upload(c, s, CSV)
    work(t, run2)
    assert c.get(f"{BASE}/runs/{run2}").json()["state"] == "awaiting_approval"


def test_xlsx_xls_xml_intake_and_ean_text(imports, tmp_path):
    c, t, s = imports
    book = Workbook()
    book.active.title = "Üres"
    sheet = book.create_sheet("Termékek")
    sheet.append(["Cikkszám", "EAN"])
    sheet.append(["A-1", 5901234123457])
    path = tmp_path / "t.xlsx"
    book.save(path)
    _, view = prepared(c, t, s, path.read_bytes(), "t.xlsx")
    assert view["file"]["sheet"] == "Termékek"  # first sheet with data
    assert view["columns"][1]["sample"] == "5901234123457"
    _, view = prepared(c, t, s, (FIXTURES / "template_prep.xls").read_bytes(), "t.xls")
    by = {col["header"]: col for col in view["columns"]}
    assert view["file"]["format"] == "xls" and view["file"]["sheet"] == "Termékek"
    assert by["EAN"]["sample"] == "5901234123457"
    assert "scientific_notation_identifier" in by["EAN"]["warnings"]
    assert "uncertain_excel_number" in by["EAN"]["warnings"]  # 17-digit number cell
    xml = ('<?xml version="1.0"?><feed><products>'
           '<product id="1"><sku>A-1</sku><ean>0012345678905</ean><image>a.jpg</image>'
           '<image>b.jpg</image></product>'
           '<product id="2"><sku>A-2</sku><ean>4006381333931</ean><color>Fekete</color>'
           '</product></products></feed>').encode()
    _, view = prepared(c, t, s, xml, "t.xml")
    assert view["file"]["record_path"] == "feed/products/product"
    assert [col["header"] for col in view["columns"]] == ["@id", "sku", "ean", "image",
                                                          "image #2", "color"]
    assert view["columns"][2]["sample"] == "0012345678905"  # leading zero kept
    unsafe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "a">]><x><p><s>&a;</s></p></x>'
    run_id = upload(c, s, unsafe, "bad.xml")
    with pytest.raises(ValueError, match="DOCTYPE"):
        work(t, run_id)  # the engine marks the run failed, then re-raises
    state = c.get(f"{BASE}/runs/{run_id}").json()
    assert state["state"] == "failed" and "DOCTYPE" in state["error"]


def test_old_import_columns_recoverable_and_existing_data_intact(imports):
    c, t, s = imports
    run_id = upload(c, s, CSV)
    work(t, run_id)
    approve(c, run_id, mapping={"0": "sku", "1": "name"})
    work(t, run_id)
    with Session(t) as db:
        before = [(p.id, dict(p.data), dict(p.source_attributes or {}), p.revision)
                  for p in db.scalars(select(SupplierProduct).order_by(SupplierProduct.id))]
        legacy = db.scalars(select(ImportProfile)).one().id
        db.execute(delete(ImportChunk).where(ImportChunk.run_id == run_id))  # file expired
        db.commit()
    view = c.get(f"{BASE}/runs/{run_id}/template-preparation").json()
    assert len(view["columns"]) == 13 and view["file"]["source_available"] is False
    assert view["columns"][0]["sample"] == "A-1"
    assert view["columns"][0]["sample_source"] == "analysis"
    body = full_body(view)
    assert save(c, run_id, body).status_code == 200
    listed = c.get(f"{BASE}/suppliers/{s}/import-templates").json()
    assert listed["legacy"] == [{"id": legacy, "name": "Terméktörzs", "version": 1,
                                 "kind": "import_profile"}]
    with Session(t) as db:
        after = [(p.id, dict(p.data), dict(p.source_attributes or {}), p.revision)
                 for p in db.scalars(select(SupplierProduct).order_by(SupplierProduct.id))]
        assert after == before  # no product was touched by template work


def test_permissions_tenant_isolation_and_required_sku(imports):
    c, t, s = imports
    run_id, view = prepared(c, t, s)
    body = full_body(view)
    body["columns"][0] |= {"state": None, "target": None}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert {"code": "cikkszam_required"} in r["errors"]
    bad = save(c, run_id, body)
    assert bad.status_code == 422 and isinstance(bad.json()["error"]["message"], str)
    tpl = save(c, run_id, full_body(view)).json()
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/runs/{run_id}/template-preparation").status_code in (403, 404)
    assert c.get(f"{BASE}/import-templates/{tpl['id']}").status_code in (403, 404)
    assert c.get(f"{BASE}/suppliers/{s}/import-templates").status_code in (403, 404)


# --- analysis-only upload (template preparation) ----------------------------------------------


def upload_for_template(c, s, content, filename="data.csv"):
    r = c.post(f"{BASE}/runs", data={"supplier_id": str(s), "purpose": "template"},
               files={"file": (filename, content)})
    assert r.status_code == 200, r.text
    assert r.json()["analysis_only"] is True
    return r.json()["id"]


def automatic_profile(c, t, s):
    """A legacy automatic import profile for the CSV structure."""
    run_id = upload(c, s, CSV)
    work(t, run_id)
    approve(c, run_id, mapping={"0": "sku", "1": "name"}, automatic=True)
    work(t, run_id)
    assert c.get(f"{BASE}/runs/{run_id}").json()["state"] == "completed"
    with Session(t) as db:
        return db.scalar(select(func.count()).select_from(SupplierProduct))


def test_analysis_only_upload_never_imports_even_with_an_automatic_profile(imports):
    """Regression: a template upload used to be auto-processed by a matching automatic
    profile, so template preparation could import products."""
    c, t, s = imports
    products = automatic_profile(c, t, s)
    run_id = upload_for_template(c, s, CSV)
    work(t, run_id)
    run = c.get(f"{BASE}/runs/{run_id}").json()
    assert run["state"] == "awaiting_approval" and run["analysis_only"] is True
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == products
        assert db.get(ImportRun, run_id).approved_by is None
    # Every column and sample is available for the template.
    view = c.get(f"{BASE}/runs/{run_id}/template-preparation").json()
    assert len(view["columns"]) == 13 and view["columns"][0]["sample"] == "A-1"
    # No product import can be started from it: approval and re-analysis stay blocked.
    r = c.post(f"{BASE}/runs/{run_id}/approve", json={
        "name": "x", "mapping": {"0": "sku", "1": "name"}, "identity_field": "sku"})
    assert r.status_code == 409
    r = c.put(f"{BASE}/runs/{run_id}/settings", json={"header_line": 1})
    assert r.status_code == 200
    work(t, run_id)
    run = c.get(f"{BASE}/runs/{run_id}").json()
    assert run["state"] == "awaiting_approval" and run["analysis_only"] is True
    # Saving a template from it creates no product either.
    assert save(c, run_id, full_body(view)).status_code == 200
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == products
        assert db.scalar(select(func.count()).select_from(ImportRun).where(
            ImportRun.state == "processing")) == 0


def test_regular_upload_keeps_legacy_automatic_processing(imports):
    """The old behaviour for ordinary imports is unchanged."""
    c, t, s = imports
    automatic_profile(c, t, s)
    run_id = upload(c, s, CSV)
    work(t, run_id)
    run = c.get(f"{BASE}/runs/{run_id}").json()
    assert run["state"] == "completed" and run["analysis_only"] is False
    r = c.post(f"{BASE}/runs", data={"supplier_id": str(s), "purpose": "other"},
               files={"file": ("data.csv", CSV)})
    assert r.status_code == 422
    # analysis_only cannot be set or cleared through the file settings field.
    r = c.post(f"{BASE}/runs", data={"supplier_id": str(s),
                                     "settings": '{"analysis_only": true}'},
               files={"file": ("data.csv", CSV)})
    assert r.status_code == 422
