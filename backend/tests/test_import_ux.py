"""IMPORT-UX-02 (#42): a truthful, compact import preview and safe field suggestions.

The CSV fixture reconstructs the shape reported for besz_minta.csv (UTF-8 BOM, ';',
27 columns, 3 product rows, 4945 rows of 27 empty fields, the cited LASTINITIALCOST /
LISTPRICE / BARCODE / QUANTITY values); it is not the customer's original file.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.import_models import SupplierProduct
from app.import_parser import blank_row
from test_supplier_import import approve, imports, upload, work  # noqa: F401

HEADERS = ["ARTICLENR", "NAME", "BARCODE", "QUANTITY", "LASTINITIALCOST", "LISTPRICE",
           "CURRENCYCODE"] + [f"COL{i:02d}" for i in range(8, 28)]
PRODUCTS = [
    ["A-1001", "Termék egy", "8,71999E+12", "-35132", "405,51", "589,7637795", "HUF"],
    ["A-1002", "Termék kettő", "8,71716E+12", "-710", "120,00", "170,10", "HUF"],
    ["A-1003", "Termék három", "5999000000017", "-16920", "77,5", "99,9", "HUF"],
]


def besz_minta(empty=4945):
    lines = [";".join(HEADERS)] + [";".join(r + [""] * 20) for r in PRODUCTS]
    lines += [";" * 26] * empty
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode()


def analysed(c, t, s, content=None, name="besz_minta.csv"):
    id = upload(c, s, content or besz_minta(), name)
    work(t, id)
    return id, c.get(f"/api/v1/imports/runs/{id}").json()


def column(run, header):
    return next(c for c in run["analysis"]["columns"] if c["header"] == header)


# --- IMPORT-UX-02 -----------------------------------------------------------------


def test_reconstructed_besz_minta_counts_and_compact_source_preview(imports):
    c, t, s = imports
    id, run = analysed(c, t, s)
    a = run["analysis"]
    assert len(a["headers"]) == 27
    assert (a["physical_rows"], a["data_rows"], a["empty_rows"]) == (4948, 3, 4945)
    page = c.post(f"/api/v1/imports/runs/{id}/preview", json={"mapping": {}, "limit": 5}).json()
    # Blank lines are skipped: one page with the 3 real rows and their physical lines.
    assert [i["line"] for i in page["items"]] == [2, 3, 4] and page["has_more"] is False
    assert (page["physical_rows"], page["data_rows"], page["empty_rows"]) == (4948, 3, 4945)
    paged = c.post(f"/api/v1/imports/runs/{id}/preview",
                   json={"mapping": {}, "limit": 2, "offset": 2}).json()
    assert [i["line"] for i in paged["items"]] == [4]
    for bad in (0, 51):
        assert c.post(f"/api/v1/imports/runs/{id}/preview",
                      json={"mapping": {}, "limit": bad}).status_code == 422


def test_monetary_headers_are_explicit_decisions_never_automatic_price(imports):
    c, t, s = imports
    _, run = analysed(c, t, s)
    cost, listprice = column(run, "LASTINITIALCOST"), column(run, "LISTPRICE")
    # Previously LASTINITIALCOST was preselected as "Ár"; now nothing is preselected.
    assert cost["field"] is None and cost["suggested_field"] == "purchase_price"
    assert listprice["field"] is None and listprice["suggested_field"] == "list_price"
    assert cost["requires_decision"] and listprice["requires_decision"] and cost["critical"]
    assert all(c["field"] != "price" for c in run["analysis"]["columns"])
    # Non-monetary headers keep their automatic suggestion.
    assert column(run, "ARTICLENR")["field"] == "sku"
    assert column(run, "CURRENCYCODE")["field"] == "currency"


def test_scientific_barcode_and_negative_quantity_are_flagged_not_trusted(imports):
    c, t, s = imports
    id, run = analysed(c, t, s)
    assert "scientific_notation_identifier" in column(run, "BARCODE")["warnings"]
    assert column(run, "QUANTITY")["warnings"] == ["negative_values"]
    mapping = {"0": "sku", "1": "name", "2": "gtin", "3": "stock"}
    page = c.post(f"/api/v1/imports/runs/{id}/preview", json={"mapping": mapping}).json()
    first, third = page["items"][0]["interpreted"], page["items"][2]["interpreted"]
    assert first["gtin"] == {
        "value": None,
        "raw": "8,71999E+12",
        "issues": ["scientific_identifier_requires_review", "invalid_gtin"],
    }
    assert third["gtin"]["value"] == "5999000000017" and third["gtin"]["issues"] == []
    assert first["stock"] == {"value": "-35132", "raw": "-35132",
                              "issues": ["negative_value_requires_rule"]}
    approve(c, id, mapping)
    work(t, id)
    done = c.get(f"/api/v1/imports/runs/{id}").json()
    assert done["counters"] == {"ready": 3, "empty": 4945}
    with Session(t) as db:
        data = {p.data["sku"]: p.data for p in db.scalars(select(SupplierProduct))}
    # The rounded exponent text is not stored as a GTIN; the valid one is.
    assert "gtin" not in data["A-1001"] and data["A-1003"]["gtin"] == "5999000000017"
    # Negative stock stays raw source data (exports clamp it), flagged for a rule.
    assert data["A-1001"]["stock"] == "-35132"
    rows = c.get(f"/api/v1/imports/runs/{id}/rows").json()
    assert rows["total"] == 3 and [r["line"] for r in rows["items"]] == [2, 3, 4]
    assert "gtin:scientific_identifier_requires_review" in rows["items"][0]["issues"]
    assert "stock:negative_value_requires_rule" in rows["items"][0]["issues"]
    assert rows["items"][0]["normalized"]["provenance"]["gtin"]["raw"] == "8,71999E+12"
    assert c.get(f"/api/v1/imports/runs/{id}/rows?include_empty=true").json()["total"] == 4948


def test_whitespace_and_invisible_characters_count_as_blank(imports):
    c, t, s = imports
    assert blank_row(["", " ", " ", "​", "﻿"])
    assert not blank_row(["", "0"])
    content = "SKU;NAME\r\n001;TV\r\n​; \r\n ; \r\n".encode()
    id, run = analysed(c, t, s, content, "blank.csv")
    a = run["analysis"]
    assert (a["physical_rows"], a["data_rows"], a["empty_rows"]) == (3, 1, 2)
    approve(c, id, {"0": "sku", "1": "name"})
    work(t, id)
    assert c.get(f"/api/v1/imports/runs/{id}").json()["counters"] == {"ready": 1, "empty": 2}


@pytest.mark.parametrize("limit", [5, 10, 25, 50])
def test_preview_page_sizes(imports, limit):
    c, t, s = imports
    rows = "".join(f"{i:04d};Termék {i}\n" for i in range(60))
    id, _ = analysed(c, t, s, ("SKU;NAME\n" + rows).encode())
    page = c.post(f"/api/v1/imports/runs/{id}/preview", json={"mapping": {}, "limit": limit}).json()
    assert len(page["items"]) == limit and page["has_more"] is True
