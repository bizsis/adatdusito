"""IMPORT-MAP-01 (#58): engine registry, column mapping, validation, versioned reuse and the
donor missing-parameter diff. Synthetic data only; no AI, no pinfo_db."""

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import import_mapping as im
from app import unas_schema as us
from app.import_models import ImportProfile, ImportRun, SupplierProduct
from app.models import Audit
from app.product_models import ProductSourceCategory
from conftest import login
from test_product_classification import detail, first_id, patch
from test_product_parameters import HEAD, WASHER, install_catalog
from test_supplier_import import approve, imports, upload, work  # noqa: F401

BASE = "/api/v1/imports"


def analysed(c, t, s, content, filename="data.csv"):
    run_id = upload(c, s, content, filename)
    work(t, run_id)
    assert c.get(f"{BASE}/runs/{run_id}").json()["state"] == "awaiting_approval"
    return run_id


def view(c, run_id):
    r = c.get(f"{BASE}/runs/{run_id}/column-mapping?engine=unas")
    assert r.status_code == 200, r.text
    return r.json()


def body(columns, n, **extra):
    """Every column, explicit target or null."""
    return {"engine_key": "unas", "identity_target": "cikkszam",
            "columns": [{"index": i, "target": columns.get(i)} for i in range(n)], **extra}


FIELD = lambda key: {"kind": "field", "key": key}  # noqa: E731
COLOR = im.parameter_header("Szín")
CSV = ("SKU;NAME;CATEGORY;EAN;Color;Unknown_01\n"
       "A-1;Mosógép;Háztartás|Mosógép;5201137061819;Fekete;x\n"
       "A-2;Porszívó;Háztartás|Porszívó;5904517345546;;\n"
       "A-3;Vasaló;;4006381333931;;\n").encode()


def test_registry_default_unas_list_and_admin_edit(imports):
    c, t, s = imports
    r = c.get(f"{BASE}/engines/unas/registry").json()
    assert r["source"] == "default" and r["version"] == 0
    fields = {f["header"]: f for f in r["fields"]}
    required = {h for h, f in fields.items() if f["required"]}
    assert required == {"Cikkszám", "Termék Név", "Kategória", "Nettó Ár", "Bruttó Ár",
                        "Státusz"}
    # Our requirement and UNAS' technical requirement are separate flags.
    assert all("unas_required" in f for f in r["fields"])
    ean = next(f for f in r["fields"] if f["label"] == "EAN")
    assert ean["kind"] == "parameter" and us.parse_parameter(ean["header"])["name"] == "EAN"
    login(c)
    stored = [*r["fields"], {"key": "param_garancia", "label": "Garancia",
                             "kind": "parameter", "type": "text",
                             "parameter": {"name": "Garancia", "param_type": "text"}}]
    put = c.put(f"{BASE}/engines/unas", json={"name": "UNAS", "fields": stored})
    assert put.status_code == 200, put.text
    r = c.get(f"{BASE}/engines/unas/registry").json()
    assert r["source"] == "stored" and r["version"] >= 1
    garancia = next(f for f in r["fields"] if f["label"] == "Garancia")
    assert garancia["header"] == im.parameter_header("Garancia")
    bad = [*stored, {"key": "x", "label": "X", "type": "text", "kind": "weird"}]
    assert c.put(f"{BASE}/engines/unas", json={"name": "UNAS", "fields": bad}).status_code \
        == 422
    # An old-format payload stays valid.
    assert c.put(f"{BASE}/engines/legacy", json={"name": "L", "fields": [
        {"key": "sku", "label": "SKU", "type": "text", "required": True}]}).status_code == 200
    login(c, "admin@example.hu")
    assert c.put(f"{BASE}/engines/unas", json={"name": "UNAS", "fields": []}).status_code \
        == 403


def test_parameter_header_follows_unas_schema():
    header = im.parameter_header("Szín")
    assert header == "Paraméter: Szín||text|1|0|1|0|0|0|||0|1|1"
    parsed = us.parse_parameter(im.parameter_header("Szélesség", "num", unit="cm"))
    assert (parsed["name"], parsed["param_type"], parsed["unit"]) == ("Szélesség", "num", "cm")


def test_four_line_csv_counts_three_products_and_lists_every_column(imports):
    c, t, s = imports
    run_id = analysed(c, t, s, CSV)
    v = view(c, run_id)
    # Counted below the header line: three products, no misleading total.
    assert v["rows"] == {"physical_rows": 3, "data_rows": 3, "empty_rows": 0}
    assert [col["header"] for col in v["columns"]] == ["SKU", "NAME", "CATEGORY", "EAN",
                                                        "Color", "Unknown_01"]
    by = {col["header"]: col for col in v["columns"]}
    assert by["SKU"]["suggestion"]["target"]["header"] == "Cikkszám"
    assert by["NAME"]["suggestion"]["target"]["header"] == "Termék Név"
    assert by["EAN"]["suggestion"]["target"]["kind"] == "parameter"
    assert by["Unknown_01"]["suggestion"] is None and by["Unknown_01"]["samples"] == ["x"]
    assert by["Color"]["filled"] == 1 and by["Color"]["empty"] == 2


def test_ean_digits_kept_and_scientific_notation_flagged(imports, tmp_path):
    c, t, s = imports
    book = Workbook()
    sheet = book.active
    sheet.append(["SKU", "NAME", "Barcode"])
    sheet.append(["A-1", "Termék", "5901234123457"])
    sheet.append(["A-2", "Másik", "8,71999E+12"])
    path = tmp_path / "ean.xlsx"
    book.save(path)
    run_id = analysed(c, t, s, path.read_bytes(), "ean.xlsx")
    barcode = view(c, run_id)["columns"][2]
    assert barcode["samples"] == ["5901234123457", "8,71999E+12"]  # verbatim, no invented digits
    assert "scientific_notation_identifier" in barcode["warnings"]
    report = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate", json=body(
        {0: FIELD("cikkszam"), 1: FIELD("termek_nev"),
         2: {"kind": "parameter", "header": im.parameter_header("EAN")}}, 3)).json()
    assert {"code": "scientific_identifier_rows", "count": 1} in report["warnings"]
    assert report["import_mapping"]["2"] == "gtin"


def test_color_parameter_requires_operator_approval(imports):
    c, t, s = imports
    run_id = analysed(c, t, s, CSV)
    color = view(c, run_id)["columns"][4]
    assert color["suggestion"]["target"] == {
        "kind": "new_parameter", "header": COLOR,
        "parameter": {"name": "Szín", "group_name": "", "param_type": "text", "unit": None}}
    assert color["suggestion"]["method"] == "translation"
    cols = {0: FIELD("cikkszam"), 1: FIELD("termek_nev"), 2: FIELD("kategoria"),
            4: {"kind": "parameter", "header": COLOR}}
    # The suggestion alone never creates the parameter.
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate", json=body(cols, 6)).json()
    assert {"code": "parameter_not_approved", "columns": [4], "target": COLOR} in r["errors"]
    proposal = {"name": "Szín", "param_type": "text"}
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body(cols, 6, new_parameters=[proposal])).json()
    assert not r["valid"]  # not approved yet
    with Session(t) as db:
        assert not db.scalars(select(ImportProfile)).all()
    saved = c.post(f"{BASE}/runs/{run_id}/column-mapping", json=body(
        cols, 6, name="UNAS", new_parameters=[{**proposal, "approved": True}]))
    assert saved.status_code == 200, saved.text
    assert saved.json()["validation"]["parameters_to_create"] == [
        {"name": "Szín", "header": COLOR}]
    # Unknown_01 stays a visible, unmapped column (kept as a source attribute on import).
    v = view(c, run_id)
    assert v["columns"][5]["current"] is None and v["columns"][5]["header"] == "Unknown_01"
    assert [p["header"] for p in v["approved_parameters"]] == [COLOR]
    with Session(t) as db:
        actions = set(db.scalars(select(Audit.action)))
        assert {"import.engine_mapping", "import.parameter_approved"} <= actions


def test_duplicate_targets_identity_conflict_and_financial_approval(imports):
    c, t, s = imports
    run_id = analysed(c, t, s, b"SKU;NAME;NAME2;NET\nA;X;Y;10\nA;Z;Z;10\n")
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate", json=body(
        {0: FIELD("cikkszam"), 1: FIELD("termek_nev"), 2: FIELD("termek_nev"),
         3: FIELD("netto_ar")}, 4)).json()
    codes = {e["code"] for e in r["errors"]}
    assert {"duplicate_target", "identity_conflict", "financial_approval_required"} <= codes
    conflict = next(e for e in r["errors"] if e["code"] == "identity_conflict")
    assert conflict["values"] == ["A"]
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body({0: FIELD("cikkszam")}, 3)).json()
    assert {"code": "missing_columns", "columns": [3]} in r["errors"]
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body({0: FIELD("nope")}, 4)).json()
    assert any(e["code"] == "unknown_target" for e in r["errors"])
    assert any(e["code"] == "identity_missing" for e in r["errors"])
    bad = c.post(f"{BASE}/runs/{run_id}/column-mapping",
                 json=body({0: FIELD("cikkszam")}, 4, name="x"))
    assert bad.status_code == 422 and isinstance(bad.json()["error"]["message"], str)
    assert bad.json()["error"]["validation"]["valid"] is False


def test_required_fields_fallbacks_and_missing_price(imports):
    c, t, s = imports
    content = ("SKU;NAME;CAT;NET;VAT;STOCK;AVAILABLE\n"
               "A;Egy;K;100;27;0;igen\nB;Kettő;K;200;27;5;nem\nC;Három;K;;27;1;igen\n").encode()
    run_id = analysed(c, t, s, content)
    cols = {0: FIELD("cikkszam"), 1: FIELD("termek_nev"), 2: FIELD("kategoria"),
            3: FIELD("netto_ar"), 4: FIELD("afakulcs"), 5: FIELD("raktarkeszlet")}
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body(cols, 7, financial_approved=True)).json()
    req = {x["header"]: x for x in r["required"]}
    assert req["Státusz"] == {**req["Státusz"], "status": "fallback", "rule": "default_1"}
    # Gross from net only with a known VAT rate; row C has no net price -> real gap.
    assert req["Bruttó Ár"]["status"] == "missing" and req["Bruttó Ár"]["rows_missing"] == 1
    assert req["Nettó Ár"]["status"] == "partial" and req["Nettó Ár"]["rows_missing"] == 1
    # Stock and status are unrelated (owner decision): stock 0 keeps status 1, no warning.
    assert not any("stock" in w["code"] for w in r["warnings"])
    assert r["approval_defaults"] == {"tax_basis": "nettó"}
    # Status from a mapped availability column (igen/nem -> 1/0).
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body({**cols, 6: FIELD("statusz")}, 7, financial_approved=True)).json()
    req = {x["header"]: x for x in r["required"]}
    assert req["Státusz"]["rule"] == "from_availability"
    # Without any VAT information no gross price is computed (no fictitious price).
    del cols[4]
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body(cols, 7, financial_approved=True)).json()
    req = {x["header"]: x for x in r["required"]}
    assert req["Bruttó Ár"]["rows_missing"] == 3
    # A supplier-wide known VAT rate makes it computable for the rows that have a net price.
    r = c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
               json=body(cols, 7, financial_approved=True, vat_rate=27)).json()
    req = {x["header"]: x for x in r["required"]}
    assert req["Bruttó Ár"]["rows_missing"] == 1
    assert c.post(f"{BASE}/runs/{run_id}/column-mapping/validate",
                  json=body(cols, 7, vat_rate=13)).json()["valid"] is False


def test_saved_mapping_reused_and_changed_columns_kept(imports):
    c, t, s = imports
    first = analysed(c, t, s, CSV)
    cols = {0: FIELD("cikkszam"), 1: FIELD("termek_nev"), 2: FIELD("kategoria"),
            3: {"kind": "parameter", "header": im.parameter_header("EAN")},
            4: {"kind": "parameter", "header": COLOR}}
    saved = c.post(f"{BASE}/runs/{first}/column-mapping", json=body(
        cols, 6, name="UNAS", new_parameters=[{"name": "Szín", "approved": True}])).json()
    assert saved["import_mapping"] == {"0": "sku", "1": "name", "2": "category", "3": "gtin"}
    approve(c, first, mapping=saved["import_mapping"],
            engine_mapping_profile_id=saved["profile_id"])
    work(t, first)
    with Session(t) as db:
        run = db.get(ImportRun, first)
        assert run.config["engine_mapping_profile_id"] == saved["profile_id"]
        product = db.scalars(select(SupplierProduct)).first()
        # Unmapped columns are kept verbatim as source attributes.
        assert {"Color", "Unknown_01"} <= set(product.source_attributes)
    # A new file: columns reordered, one renamed, one added.
    second = analysed(c, t, s, ("NAME;SKU;Color;EAN;CATEGORY;Unknown_02\n"
                                "Mosógép;A-1;Fekete;5201137061819;K;y\n").encode())
    v = view(c, second)
    by = {col["header"]: col for col in v["columns"]}
    assert by["SKU"]["current"]["key"] == "cikkszam"
    assert by["Color"]["current"]["header"] == COLOR
    assert by["Color"]["current_source"] == "saved_profile"
    assert by["Unknown_02"]["current"] is None
    assert v["saved_profile"]["requires_review"] is True
    assert v["saved_profile"]["missing_headers"] == ["Unknown_01"]
    assert v["saved_profile"]["new_headers"] == ["Unknown_02"]
    # The approved parameter is reusable without re-approval; versions are kept.
    cols2 = {1: FIELD("cikkszam"), 0: FIELD("termek_nev"), 4: FIELD("kategoria"),
             2: {"kind": "parameter", "header": COLOR}}
    again = c.post(f"{BASE}/runs/{second}/column-mapping", json=body(cols2, 6, name="UNAS"))
    assert again.status_code == 200 and again.json()["version"] == 2
    history = c.get(f"{BASE}/suppliers/{s}/engine-mappings?engine=unas").json()
    assert [h["version"] for h in history] == [2, 1]
    # A foreign profile cannot be linked to an approval.
    assert c.post(f"{BASE}/runs/{second}/approve", json={
        "name": "x", "mapping": {"1": "sku"}, "engine_mapping_profile_id": 999}).status_code \
        == 404


def donor_world(c, t, s):
    install_catalog(t)
    head = HEAD.replace("Garancia", "Color")
    content = (head + "001;Mosógép A;Gépek;2,1;fehér;8;52;600;Fekete\n").encode()
    run_id = analysed(c, t, s, content)
    approve(c, run_id, mapping={"0": "sku", "1": "name", "2": "category"})
    work(t, run_id)
    pid = first_id(c)
    assert patch(c, pid, expected_revision=detail(c, pid)["revision"], action="set",
                 navigation_node_id=WASHER).status_code == 200
    return run_id, pid


def test_donor_parameter_diff_lists_all_missing_and_selection_modes(imports):
    c, t, s = imports
    run_id, _ = donor_world(c, t, s)
    donors = c.get(f"{BASE}/runs/{run_id}/donor-categories").json()
    assert [d["emag_category_id"] for d in donors["donors"]] == [385]
    r = c.get(f"{BASE}/runs/{run_id}/donor-parameters?emag_category_id=385").json()
    assert r["total"] == 7 and len({p["emag_parameter_id"] for p in r["parameters"]}) == 7
    status = {p["label"]: p["status"] for p in r["parameters"]}
    # Every donor parameter is listed; those already present as columns are not "missing".
    assert status == {"Teljesítmény": "covered", "Szín": "covered", "Kapacitás": "covered",
                      "Energiaosztály": "missing", "Zajszint": "covered",
                      "Szélesség": "covered", "Programok száma": "missing"}
    assert r["missing"] == 2 and r["selected"] == 0
    url = f"{BASE}/runs/{run_id}/donor-parameters/selection"
    assert c.put(url, json={"emag_category_id": 385, "mode": "all"}).json()["selected"] == 2
    assert c.put(url, json={"emag_category_id": 385, "mode": "none"}).json()["selected"] == 0
    one = c.put(url, json={"emag_category_id": 385, "emag_parameter_ids": [6509]}).json()
    assert [p["emag_parameter_id"] for p in one["parameters"] if p["selected"]] == [6509]
    bad = c.put(url, json={"emag_category_id": 385, "emag_parameter_ids": [6507]})
    assert bad.status_code == 422 and bad.json()["error"]["reason"] == "not_selectable"
    prepared = c.get(f"{BASE}/runs/{run_id}/prepared-fields").json()
    assert prepared["donor_parameters"] == [{"emag_category_id": 385,
                                             "emag_parameter_id": 6509,
                                             "name": "Energiaosztály",
                                             "state": "selected_empty"}]
    assert c.get(f"{BASE}/runs/{run_id}/donor-parameters?emag_category_id=999").status_code \
        == 404
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/runs/{run_id}/donor-parameters?emag_category_id=385").status_code \
        in (403, 404)


def test_source_category_unchanged_by_donor_selection(imports):
    c, t, s = imports
    run_id, pid = donor_world(c, t, s)
    with Session(t) as db:
        product = db.get(SupplierProduct, pid)
        before = (product.source_category_id, product.data.get("category"),
                  dict(product.data), product.revision)
        path = db.get(ProductSourceCategory, product.source_category_id).path_text
    c.put(f"{BASE}/runs/{run_id}/donor-parameters/selection",
          json={"emag_category_id": 385, "mode": "all"})
    donors = c.get(f"{BASE}/runs/{run_id}/donor-categories").json()
    assert donors["source_categories"][0]["path"] == path == "Gépek"
    with Session(t) as db:
        product = db.get(SupplierProduct, pid)
        assert (product.source_category_id, product.data.get("category"), dict(product.data),
                product.revision) == before  # nothing written to the product


def test_mapping_requires_completed_analysis_and_permissions(imports):
    c, t, s = imports
    run_id = upload(c, s, CSV)
    assert c.get(f"{BASE}/runs/{run_id}/column-mapping").status_code == 409
    work(t, run_id)
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/runs/{run_id}/column-mapping").status_code in (403, 404)
