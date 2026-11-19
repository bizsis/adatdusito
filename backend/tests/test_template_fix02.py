"""TEMPLATE-FIX-02: name-only parameters, "Paraméter:" prefix once, the full documented UNAS
target list, occupied targets, export/read-back. Synthetic data only; read-only exports."""

import csv
import io

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import template_prep as tp
from app import unas_schema as us
from app.import_mapping import parameter_header
from app.import_models import ImportProfile, SupplierProduct
from conftest import login
from test_supplier_import import imports, work  # noqa: F401
from test_template_prep import BASE, columns_of, mapped, save, upload_for_template

SOURCE = ("SKU;Name;Category;Paraméter: Szín;Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1;"
          "Anyag;SEO Title;Tartalmi elemek 2\n"
          "A-1;Mosógép;Gépek;Fekete;60;acél;Mosógép olcsón;<p>Tartalom</p>\n"
          "A-2;Porszívó;Gépek;;;műanyag;;\n").encode()
FULL_WIDTH = "Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1"


def prepare(c, t, s, content=SOURCE):
    run_id = upload_for_template(c, s, content)
    work(t, run_id)
    view = c.get(f"{BASE}/runs/{run_id}/template-preparation").json()
    return run_id, view


def by_header(view):
    return {col["header"]: col for col in view["columns"]}


def test_prefixed_source_columns_are_parameters_without_double_prefix(imports):
    c, t, s = imports
    run_id, view = prepare(c, t, s)
    cols = by_header(view)
    color = cols["Paraméter: Szín"]
    assert color["assignment"] == {"state": "mapped", "target": {
        "key": "parameter", "parameter": {"name": "Szín", "param_type": "text",
                                          "group_name": "", "unit": None}}}
    assert color["suggestion"]["method"] == "source_parameter"
    assert color["suggestion"]["label"] == "Paraméter: Szín"  # display name, never doubled
    width = cols[FULL_WIDTH]
    assert width["assignment"]["target"]["header"] == FULL_WIDTH  # documented header kept
    assert width["suggestion"]["label"] == "Paraméter: Szélesség"
    # Declared by the source itself: savable without a separate approval.
    body = {"engine": "unas", "currency": "HUF", "columns": columns_of(view)}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert r["valid"], r["errors"]
    labels = {x["label"] for x in r["resolved"]}
    assert {"Paraméter: Szín", "Paraméter: Szélesség"} <= labels
    assert not any("Paraméter: Paraméter" in x for x in labels)
    saved = save(c, run_id, body)
    assert saved.status_code == 200, saved.text
    result = c.get(f"{BASE}/import-templates/{saved.json()['id']}/result").json()
    heads = {col["label"]: col["header"] for col in result["columns"]}
    assert heads["Paraméter: Szín"] == parameter_header("Szín")  # documented export header
    assert heads["Paraméter: Szélesség"] == FULL_WIDTH
    row = dict(zip([col["header"] for col in result["columns"]], result["rows"][0]["values"]))
    assert row[parameter_header("Szín")] == "Fekete" and row[FULL_WIDTH] == "60"  # unchanged


def test_new_parameter_needs_only_a_name_and_prefix_is_not_doubled(imports):
    c, t, s = imports
    run_id, view = prepare(c, t, s)
    body = {"engine": "unas", "currency": "HUF",
            "columns": columns_of(view, {5: {"state": "mapped", "target": {
                "key": "parameter", "parameter": {"name": "Paraméter: Anyag"}}}}),
            "new_parameters": [{"name": "Paraméter: Anyag", "approved": True}]}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert r["valid"], r["errors"]
    anyag = next(x for x in r["resolved"] if x["index"] == 5)
    assert anyag["label"] == "Paraméter: Anyag"
    assert anyag["unas_header"] == parameter_header("Anyag")
    assert r["parameters_to_create"] == [{"name": "Anyag", "header": parameter_header("Anyag")}]
    # Without approval it is still refused (operator approval stays mandatory).
    body["new_parameters"] = [{"name": "Anyag"}]
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert any(e["code"] == "parameter_not_approved" for e in r["errors"])


def test_old_templates_with_technical_parameter_settings_still_work(imports):
    """A template saved with an explicit type/unit keeps exporting its header."""
    c, t, s = imports
    run_id, view = prepare(c, t, s)
    old = {"name": "Mélység", "param_type": "num", "group_name": "", "unit": "cm"}
    body = {"engine": "unas", "currency": "HUF",
            "columns": columns_of(view, {5: {"state": "mapped", "target": {
                "key": "parameter", "parameter": old}}}),
            "new_parameters": [{**old, "approved": True}]}
    saved = save(c, run_id, body).json()
    result = c.get(f"{BASE}/import-templates/{saved['id']}/result").json()
    heads = {col["label"]: col["header"] for col in result["columns"]}
    assert heads["Paraméter: Mélység"] == parameter_header("Mélység", "num", unit="cm")


def test_full_documented_unas_target_list():
    payload = tp.targets_payload()
    targets = payload["targets"]
    headers = {t["unas_header"] for t in targets}
    expected = {h for h in us.STANDARD if h not in us.SYSTEM_GENERATED and h != "Azonosító"}
    assert expected <= headers
    assert not headers & (us.SYSTEM_GENERATED | {"Azonosító"})
    assert len({t["key"] for t in targets}) == len(targets) == 84
    numbered = {t["key"]: (t["unas_header"], t["min_instance"], t["max_instance"])
                for t in targets if t.get("added_in") and t["multiple"] == "instances"}
    assert numbered == {
        "tartalmi_elemek": ("Tartalmi elemek {n}", 1, 3), "adat": ("Adat {n}", 1, 3),
        "statusz_n": ("Státusz {n}", 1, 3), "crosssale": ("CrossSale{n}", 1, 3),
        "upsale": ("UpSale{n}", 1, 2),
        "valaszthato_tulajdonsag": ("Választható Tulajdonság {n}", 1, 3),
        "tovabbi_lapful_cime": ("További lapfül címe {n}", 1, 3)}
    # Every exported header is documented (standard column, numbered family or parameter).
    for t in targets:
        if t["key"] in ("parameter", "afa"):
            continue
        low = t.get("min_instance", 1)
        header = tp.unas_header(t, low if t["key"] != "raktarkeszlet" else 0)
        assert us.classify(header)["scope"] == "standard" or us.parse_parameter(header), header


def test_new_targets_map_export_and_read_back(imports, tmp_path):
    from app.reference_products import import_export
    from app.unas_models import ReferenceProduct

    c, t, s = imports
    run_id, view = prepare(c, t, s)
    cols = by_header(view)
    assert cols["SEO Title"]["assignment"]["target"] == {"key": "seo_title"}
    assert cols["Tartalmi elemek 2"]["assignment"]["target"] == {"key": "tartalmi_elemek",
                                                                 "instance": 2}
    body = {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
        5: {"state": "unused", "target": None}})}
    saved = save(c, run_id, body).json()
    r = c.get(f"{BASE}/import-templates/{saved['id']}/result.xlsx")
    path = tmp_path / "UnasShop_fix02-unas-hu_20261119-120000.xlsx"
    path.write_bytes(r.content)
    rows = list(load_workbook(path).active.iter_rows(values_only=True))
    first = dict(zip(rows[0], rows[1]))
    assert first["SEO Title"] == "Mosógép olcsón"
    assert first["Tartalmi elemek 2"] == "<p>Tartalom</p>"
    assert first[parameter_header("Szín")] == "Fekete"
    assert not any(str(h).startswith("Paraméter: Paraméter") for h in rows[0])
    table = list(csv.reader(io.StringIO(c.get(
        f"{BASE}/import-templates/{saved['id']}/result.csv").content.decode("utf-8-sig")),
        delimiter=";"))
    assert table[0] == list(rows[0])
    with Session(t) as db:
        import_export(db, path, store_key="fix02-unas-hu", version="20261119-120000")
        product = db.scalar(select(ReferenceProduct).where(
            ReferenceProduct.source_sku == "A-1"))
        assert product.raw["SEO Title"] == "Mosógép olcsón"
        assert product.raw[parameter_header("Szín")] == "Fekete"


def test_occupied_targets_freed_after_clearing(imports):
    c, t, s = imports
    run_id, view = prepare(c, t, s)
    assert {o["slot"] for o in view["occupied"]} >= {"cikkszam", "seo_title",
                                                       "tartalmi_elemek#2",
                                                       "parameter:Szín"}
    body = {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
        5: mapped("seo_title")})}
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    seo = next(o for o in r["occupied"] if o["slot"] == "seo_title")
    assert seo["columns"] == [5, 6] and seo["multiple"] is None
    assert {"code": "duplicate_target", "columns": [5, 6], "target": "seo_title"} in r["errors"]
    body["columns"][6] |= {"state": None, "target": None}  # clearing frees the target
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert next(o for o in r["occupied"] if o["slot"] == "seo_title")["columns"] == [5]
    assert not any(e["code"] == "duplicate_target" for e in r["errors"])
    # Out-of-range instances of a numbered family are refused (no undocumented header).
    body["columns"][7] |= mapped("tartalmi_elemek", instance=7)
    r = c.post(f"{BASE}/runs/{run_id}/template-preparation/validate", json=body).json()
    assert {"code": "unknown_target", "columns": [7], "target": "tartalmi_elemek"} \
        in r["errors"]


def test_read_only_and_tenant_isolation(imports):
    c, t, s = imports
    run_id, view = prepare(c, t, s)
    saved = save(c, run_id, {"engine": "unas", "currency": "HUF",
                             "columns": columns_of(view)}).json()
    c.get(f"{BASE}/import-templates/{saved['id']}/result.xlsx")
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 0
        assert db.scalar(select(func.count()).select_from(ImportProfile)) == 1
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/runs/{run_id}/template-preparation").status_code in (403, 404)
    assert c.get(f"{BASE}/import-templates/{saved['id']}/result").status_code in (403, 404)
