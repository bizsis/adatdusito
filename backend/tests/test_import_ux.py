"""IMPORT-UX-01/02 (#41, #42): import-history deletion and a truthful, compact preview.

The CSV fixture reconstructs the shape reported for besz_minta.csv (UTF-8 BOM, ';',
27 columns, 3 product rows, 4945 rows of 27 empty fields, the cited LASTINITIALCOST /
LISTPRICE / BARCODE / QUANTITY values); it is not the customer's original file.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.import_models import ImportChunk, ImportRun, SupplierProduct
from app.import_parser import blank_row
from app.models import Audit, now
from conftest import login
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


# --- IMPORT-UX-01 -----------------------------------------------------------------


def test_delete_unapproved_import_is_real_and_does_not_come_back(imports):
    c, t, s = imports
    first, _ = analysed(c, t, s, b"SKU;NAME\n001;TV\n", "besz_minta.csv")
    second, _ = analysed(c, t, s, b"SKU;NAME\n002;Radio\n", "besz_minta.csv")
    plan = c.get(f"/api/v1/imports/runs/{first}/deletion").json()
    assert plan["deletable"] and plan["reason"] is None
    assert plan["deletes"]["source_file_chunks"] == 1 and plan["deletes"]["source_file_bytes"] > 0
    assert set(plan["keeps"]) >= {"supplier_products", "audit_log", "other_imports"}
    r = c.delete(f"/api/v1/imports/runs/{first}")
    assert r.status_code == 200 and r.json() == {"deleted": True, "run_id": first}
    # Server truth, not a hidden list item: gone from the list and from the database,
    # also after the next upload (the reported "deleted imports came back" case).
    third, _ = analysed(c, t, s, b"SKU;NAME\n003;Laptop\n", "uj.csv")
    ids = [x["id"] for x in c.get("/api/v1/imports/runs").json()]
    assert first not in ids and second in ids and third in ids
    assert c.get(f"/api/v1/imports/runs/{first}").status_code == 404
    with Session(t) as db:
        assert db.get(ImportRun, first) is None
        assert db.scalar(select(func.count()).select_from(ImportChunk)
                         .where(ImportChunk.run_id == first)) == 0
        logged = db.scalar(select(Audit).where(Audit.action == "import.delete"))
        assert logged.target == str(first) and logged.details["state"] == "awaiting_approval"
    # Documented repeat: the record no longer exists.
    assert c.delete(f"/api/v1/imports/runs/{first}").status_code == 404


def test_cancelled_before_approval_is_deletable_and_cancel_works_awaiting_approval(imports):
    c, t, s = imports
    id, run = analysed(c, t, s, b"SKU;NAME\n001;TV\n")
    assert run["state"] == "awaiting_approval"
    assert c.post(f"/api/v1/imports/runs/{id}/actions/cancel").json()["state"] == "cancelled"
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 200


def test_processed_import_and_its_products_are_never_deleted(imports):
    c, t, s = imports
    id, _ = analysed(c, t, s, b"SKU;NAME;QUANTITY\n001;TV;1\n")
    approve(c, id)
    work(t, id)
    plan = c.get(f"/api/v1/imports/runs/{id}/deletion").json()
    assert not plan["deletable"] and plan["reason"] == "approved_or_processed"
    assert plan["references"]["products_last_written_by_run"] == 1
    r = c.delete(f"/api/v1/imports/runs/{id}")
    assert r.status_code == 409 and "Jóváhagyott" in r.json()["error"]["message"]
    with Session(t) as db:
        assert db.get(ImportRun, id) is not None
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 1


def test_running_or_referenced_unapproved_import_is_refused(imports):
    c, t, s = imports
    id, _ = analysed(c, t, s, b"SKU;NAME\n001;TV\n")
    with Session(t) as db:
        db.get(ImportRun, id).lease_until = now() + timedelta(minutes=5)
        db.commit()
    r = c.delete(f"/api/v1/imports/runs/{id}")
    assert r.status_code == 409 and "fut" in r.json()["error"]["message"]
    other, _ = analysed(c, t, s, "SKU;NAME;QUANTITY\n009;Kábel;1\n".encode())
    approve(c, other)
    work(t, other)
    with Session(t) as db:
        db.get(ImportRun, id).lease_until = None
        # Defensive: a product pointing at an unapproved run must keep it.
        db.scalar(select(SupplierProduct)).last_run_id = id
        db.commit()
    plan = c.get(f"/api/v1/imports/runs/{id}/deletion").json()
    assert plan["reason"] == "referenced"
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 409


def test_delete_is_tenant_scoped_role_bound_and_csrf_origin_protected(imports):
    c, t, s = imports
    id, _ = analysed(c, t, s, b"SKU;NAME\n001;TV\n")
    login(c, "other@example.hu")  # tenant 2 administrator
    assert c.get(f"/api/v1/imports/runs/{id}/deletion").status_code == 404
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 404
    login(c, "reviewer@example.hu")  # tenant 1, imports.read only
    assert c.get(f"/api/v1/imports/runs/{id}/deletion").status_code == 403
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 403
    login(c, "admin@example.hu")
    token = c.headers.pop("X-CSRF-Token")
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 403
    c.headers["X-CSRF-Token"] = token
    assert c.delete(f"/api/v1/imports/runs/{id}",
                    headers={"Origin": "https://evil.example"}).status_code == 403
    with Session(t) as db:
        assert db.get(ImportRun, id) is not None
    c.post("/api/v1/auth/logout")
    c.headers.pop("X-CSRF-Token", None)
    assert c.delete(f"/api/v1/imports/runs/{id}").status_code == 401


@pytest.mark.parametrize("limit", [5, 10, 25, 50])
def test_preview_page_sizes(imports, limit):
    c, t, s = imports
    rows = "".join(f"{i:04d};Termék {i}\n" for i in range(60))
    id, _ = analysed(c, t, s, ("SKU;NAME\n" + rows).encode())
    page = c.post(f"/api/v1/imports/runs/{id}/preview", json={"mapping": {}, "limit": limit}).json()
    assert len(page["items"]) == limit and page["has_more"] is True
