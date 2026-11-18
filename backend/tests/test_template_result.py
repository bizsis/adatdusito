"""TEMPLATE-RESULT-01: the UNAS product data file built from a saved template version.
Synthetic data only; read only (no product import, no AI, no eMAG, no pinfo_db)."""

import csv
import io
import time
from pathlib import Path

from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import template_result as tr
from app import unas_schema as us
from app.import_mapping import parameter_header
from app.import_models import ImportChunk, ImportProfile, ImportRun, SupplierProduct
from app.models import Audit
from conftest import login
from test_supplier_import import imports, upload, work  # noqa: F401
from test_template_prep import (
    BASE,
    CSV,
    columns_of,
    full_body,
    mapped,
    save,
    upload_for_template,
)

FIXTURES = Path(__file__).parent / "fixtures"
EAN = parameter_header("EAN").replace("|1|0|1|0|0|0|", "|1|0|0|0|0|0|")


def template_for(c, t, s, content=CSV, filename="data.csv", body=None, name="Alap"):
    run_id = upload_for_template(c, s, content, filename)
    work(t, run_id)
    view = c.get(f"{BASE}/runs/{run_id}/template-preparation").json()
    saved = save(c, run_id, body(view) if body else full_body(view), name=name)
    assert saved.status_code == 200, saved.text
    return run_id, saved.json()


def result(c, template_id, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = c.get(f"{BASE}/import-templates/{template_id}/result?{query}")
    assert r.status_code == 200, r.text
    return r.json()


def codes(items):
    return [i["code"] for i in items]


def test_identifier_rules_never_invent_digits():
    assert tr.identifier("0012345678905") == ("0012345678905", [])
    assert tr.identifier("5901234123457.0") == ("5901234123457", [])
    assert tr.identifier("5,901234123457E+12") == ("5901234123457", ["ean_reconstructed"])
    # Regression: 8,71999E+12 has lost 7 digits; nothing is reconstructed.
    assert tr.identifier("8,71999E+12") == ("", ["ean_unrecoverable"])
    assert tr.identifier("5.90123412345E+12") == ("", ["ean_unrecoverable"])
    assert tr.identifier("5901234123458") == ("5901234123458", ["invalid_gtin"])
    assert tr.identifier("ABC-12", gtin=False) == ("ABC-12", [])


def test_three_products_columns_values_defaults_and_warnings(imports):
    c, t, s = imports
    run_id, tpl = template_for(c, t, s)
    r = result(c, tpl["id"])
    headers = [col["header"] for col in r["columns"]]
    assert headers == ["Cikkszám", "Termék Név", "Kategória", "Raktárkészlet", "Nettó Ár",
                       "Bruttó Ár", EAN, "Státusz", "Kép link", parameter_header("Szín")]
    assert all(us.classify(h)["scope"] == "standard" or us.parse_parameter(h) for h in headers)
    # The unverified second warehouse header is not exported (documented columns only).
    assert r["excluded_columns"] == [{"header": "Raktárkészlet #1", "source_columns": [9],
                                      "code": "undocumented_header_excluded"}]
    rows = {row["values"][0]: dict(zip(headers, row["values"])) | {"_row": row}
            for row in r["rows"]}
    a1 = rows["A-1"]
    assert (a1["Nettó Ár"], a1["Bruttó Ár"], a1["Státusz"]) == ("1000", "1270", "1")
    assert a1[EAN] == "5901234123457" and a1["Kép link"] == "https://k.hu/1.jpg"
    assert a1[parameter_header("Szín")] == "Fekete" and a1["Raktárkészlet"] == "5"
    assert "additional_images_not_exported" in codes(a1["_row"]["warnings"])
    a2 = rows["A-2"]
    assert a2[EAN] == "0012345678905"  # leading zeros kept
    assert a2["Státusz"] == "0" and a2["Nettó Ár"] == a2["Bruttó Ár"] == ""
    assert "missing_price" in codes(a2["_row"]["warnings"])  # no fictitious price
    a3 = rows["A-3"]
    assert a3["Kategória"] == "" and a3["Bruttó Ár"] == "3810"
    assert {"code": "missing_required", "target": "kategoria"} in a3["_row"]["warnings"]
    assert r["summary"]["rows"] == r["summary"]["exportable"] == 3
    assert r["template"]["version"] == 1 and r["template"]["currency"] == "HUF"


def test_vat_prices_sale_prices_dates_and_purchase_price(imports):
    c, t, s = imports
    content = ("SKU;Name;Category;Gross;VAT;Sale net;Sale start;Sale end;Cost\n"
               "A;Egy;K|L;1270;27;800;2026-12-01;01.01.2027;700\n"
               "B;Kettő;K;105;5%;;;;50\n"
               "C;Három;K;100;13;;rossz;;\n").encode()

    def body(view):
        return {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
            3: mapped("brutto_ar"), 4: mapped("afa"), 5: mapped("netto_akcios_ar"),
            6: mapped("akcio_kezdete"), 7: mapped("akcio_vege"),
            8: {"state": "unused", "target": None}})}

    _, tpl = template_for(c, t, s, content, body=body)
    r = result(c, tpl["id"])
    headers = [col["header"] for col in r["columns"]]
    assert "Nettó Ár" in headers and "Akciós Bruttó Ár" in headers
    rows = {row["values"][0]: dict(zip(headers, row["values"])) | {"_row": row}
            for row in r["rows"]}
    assert rows["A"]["Nettó Ár"] == "1000" and rows["A"]["Akciós Bruttó Ár"] == "1016"
    assert rows["A"]["Kategória"] == "K|L"  # source category verbatim
    assert (rows["A"]["Akció Kezdet"], rows["A"]["Akció Lejárat"]) == ("2026.12.01",
                                                                       "2027.01.01")
    assert rows["B"]["Nettó Ár"] == "100"  # 105 / 1.05 with the row's own VAT
    # Invalid VAT: nothing is computed; an invalid date stays empty.
    assert rows["C"]["Nettó Ár"] == "" and "invalid_vat" in codes(rows["C"]["_row"]["warnings"])
    assert rows["C"]["Akció Kezdet"] == ""
    assert {"code": "invalid_date", "target": "akcio_kezdete"} in rows["C"]["_row"]["warnings"]
    # The purchase price (Cost) never becomes a sale price.
    assert "700" not in rows["A"]["_row"]["values"]


def test_price_vat_mismatch_is_flagged_not_changed(imports):
    c, t, s = imports
    content = b"SKU;Name;Category;Net;Gross\nA;X;K;100;130\nB;Y;K;100;127\n"

    def body(view):
        return {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
            3: mapped("netto_ar"), 4: mapped("brutto_ar")})}

    _, tpl = template_for(c, t, s, content, body=body)
    r = result(c, tpl["id"])
    rows = {row["values"][0]: row for row in r["rows"]}
    assert {"code": "price_vat_mismatch", "target": "brutto_ar"} in rows["A"]["warnings"]
    assert "130" in rows["A"]["values"] and not rows["B"]["warnings"]


def test_ean_from_xlsx_and_xls_text_and_scientific_notation(imports, tmp_path):
    c, t, s = imports
    book = Workbook()
    sheet = book.active
    sheet.append(["SKU", "Name", "Category", "EAN"])
    sheet.append(["A", "Egy", "K", 5901234123457])
    sheet.append(["B", "Kettő", "K", "8,71999E+12"])
    sheet.append(["C", "Három", "K", "5,901234123457E+12"])
    sheet.append(["D", "Négy", "K", "0012345678905"])
    path = tmp_path / "ean.xlsx"
    book.save(path)
    _, tpl = template_for(c, t, s, path.read_bytes(), "ean.xlsx")
    rows = {row["values"][0]: row for row in result(c, tpl["id"])["rows"]}
    ean = [col["header"] for col in result(c, tpl["id"])["columns"]].index(EAN)
    assert rows["A"]["values"][ean] == "5901234123457"
    assert rows["B"]["values"][ean] == "" and "ean_unrecoverable" in codes(rows["B"]["warnings"])
    assert rows["C"]["values"][ean] == "5901234123457"
    assert "ean_reconstructed" in codes(rows["C"]["warnings"])
    assert rows["D"]["values"][ean] == "0012345678905"
    # Legacy XLS: a 17-digit number cell is beyond Excel precision -> not reproduced.

    def xls_body(view):
        return {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
            3: mapped("netto_ar"), 4: {"state": "unused", "target": None}})}

    _, tpl = template_for(c, t, s, (FIXTURES / "template_prep.xls").read_bytes(), "t.xls",
                          body=xls_body, name="XLS")
    r = result(c, tpl["id"])
    ean = [col["header"] for col in r["columns"]].index(EAN)
    rows = {row["values"][0]: row for row in r["rows"]}
    assert rows["A-1"]["values"][ean] == "5901234123457"
    assert rows["A-2"]["values"][ean] == "" and rows["A-3"]["values"][ean] == ""
    assert "ean_unrecoverable" in codes(rows["A-3"]["warnings"])


def test_download_xlsx_and_csv_read_back_as_unas_export(imports, tmp_path):
    from app.reference_products import import_export
    from app.unas_models import ReferenceProduct, ReferenceProductAttribute
    from app.unas_models import ReferenceProductIdentifier

    c, t, s = imports
    run_id, tpl = template_for(c, t, s)
    r = c.get(f"{BASE}/import-templates/{tpl['id']}/result.xlsx")
    assert r.status_code == 200 and r.headers["x-exported-rows"] == "3"
    assert r.headers["cache-control"] == "no-store"
    assert f"UNAS_Alap_v1_{run_id}.xlsx" in r.headers["content-disposition"]
    path = tmp_path / "UnasShop_teszt-unas-hu_20261118-120000.xlsx"
    path.write_bytes(r.content)
    sheet = load_workbook(path).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "Cikkszám" and len(rows) == 4
    ean = rows[0].index(EAN)
    assert {row[ean] for row in rows[1:]} == {"5901234123457", "0012345678905",
                                             "4006381333931"}  # text cells
    # Importability: the existing UNAS export reader accepts it unchanged.
    with Session(t) as db:
        import_export(db, path, store_key="teszt-unas-hu", version="20261118-120000")
        product = db.scalar(select(ReferenceProduct).where(
            ReferenceProduct.source_sku == "A-1"))
        assert product.name == "Mosógép" and product.category_path == "Gépek"
        gtins = set(db.scalars(select(ReferenceProductIdentifier.value).where(
            ReferenceProductIdentifier.kind == "gtin")))
        assert gtins == {"5901234123457", "0012345678905", "4006381333931"}
        color = db.scalar(select(ReferenceProductAttribute.value_text).where(
            ReferenceProductAttribute.product_id == product.id,
            ReferenceProductAttribute.name == "Szín"))
        assert color == "Fekete"
    r = c.get(f"{BASE}/import-templates/{tpl['id']}/result.csv")
    assert r.status_code == 200 and r.content.startswith("﻿".encode())
    table = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert table[0] == list(rows[0]) and len(table) == 4
    assert table[2][ean] == "0012345678905"
    with Session(t) as db:
        downloads = list(db.scalars(select(Audit).where(
            Audit.action == "import.template_result_download")))
        assert len(downloads) == 2


def test_missing_sku_excluded_duplicates_and_currency(imports):
    c, t, s = imports
    content = ("SKU;Name;Category;Net;Currency\nA;X;K;10;HUF\n;Y;K;20;HUF\n"
               "A;Z;K;30;EUR\n").encode()

    def body(view):
        return {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
            3: mapped("netto_ar"), 4: {"state": "unused", "target": None}})}

    _, tpl = template_for(c, t, s, content, body=body)
    r = result(c, tpl["id"])
    assert r["summary"]["excluded"] == 1 and r["summary"]["errors"] == {"missing_sku": 1}
    assert r["summary"]["warnings"]["duplicate_sku"] == 2
    third = r["rows"][2]
    assert {"code": "currency_mismatch", "value": "EUR"} in third["warnings"]
    assert "30" in third["values"]  # no conversion
    download = c.get(f"{BASE}/import-templates/{tpl['id']}/result.xlsx")
    assert download.headers["x-excluded-rows"] == "1"
    assert download.headers["x-exported-rows"] == "2"


def test_ten_thousand_products_paging_and_download(imports):
    c, t, s = imports
    lines = ["SKU;Name;Category;EAN;Net"] + [
        f"S{i:05d};Termék {i};K;{4006381333931 if i % 2 else 5901234123457};{100 + i}"
        for i in range(10000)]

    def body(view):
        return {"engine": "unas", "currency": "HUF", "columns": columns_of(view, {
            4: mapped("netto_ar")})}

    _, tpl = template_for(c, t, s, "\n".join(lines).encode(), body=body)
    started = time.monotonic()
    r = result(c, tpl["id"], offset=9990, limit=50)
    assert r["total"] == 10000 and len(r["rows"]) == 10
    assert r["rows"][-1]["values"][0] == "S09999"
    download = c.get(f"{BASE}/import-templates/{tpl['id']}/result.xlsx")
    assert download.headers["x-exported-rows"] == "10000"
    assert time.monotonic() - started < 120


def test_new_template_version_regenerates_and_old_version_kept(imports):
    c, t, s = imports
    run_id, v1 = template_for(c, t, s)
    view = c.get(f"{BASE}/runs/{run_id}/template-preparation?template_id={v1['id']}").json()
    body = full_body(view)
    body["columns"][5] |= mapped("rovid_leiras")
    v2 = save(c, run_id, body, name="Alap", template_id=v1["id"]).json()
    assert v2["version"] == 2
    new = [col["header"] for col in result(c, v2["id"])["columns"]]
    old = [col["header"] for col in result(c, v1["id"])["columns"]]
    assert "Rövid Leírás" in new and "Rövid Leírás" not in old


def test_read_only_permissions_and_expired_source(imports):
    c, t, s = imports
    run_id, tpl = template_for(c, t, s)
    with Session(t) as db:
        before = (db.scalar(select(func.count()).select_from(SupplierProduct)),
                  db.scalar(select(func.count()).select_from(ImportProfile)),
                  db.get(ImportRun, run_id).state)
    result(c, tpl["id"])
    c.get(f"{BASE}/import-templates/{tpl['id']}/result.xlsx")
    with Session(t) as db:
        assert (db.scalar(select(func.count()).select_from(SupplierProduct)),
                db.scalar(select(func.count()).select_from(ImportProfile)),
                db.get(ImportRun, run_id).state) == before == (0, 1, "awaiting_approval")
    other = upload(c, s, b"Code;Title\nX;Y\n")  # another supplier run is fine, other tenant not
    work(t, other)
    assert c.get(f"{BASE}/import-templates/{tpl['id']}/result?run_id={other}").status_code \
        == 200
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/import-templates/{tpl['id']}/result").status_code in (403, 404)
    assert c.get(f"{BASE}/import-templates/{tpl['id']}/result.csv").status_code in (403, 404)
    login(c, "admin@example.hu")
    with Session(t) as db:
        db.execute(delete(ImportChunk).where(ImportChunk.run_id == run_id))
        db.commit()
    assert c.get(f"{BASE}/import-templates/{tpl['id']}/result").status_code == 409

