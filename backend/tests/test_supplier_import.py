"""Supplier file semantics, tenant boundaries and durable import execution."""

import io
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from openpyxl import Workbook
from app.import_parser import analyze, rows, normalize, AISuggestionProvider
from app.import_engine import advance
from app.import_models import SupplierProduct, ImportChange
from app import import_api
from conftest import login


@pytest.fixture
def imports(environment, monkeypatch):
    client, target, _, _ = environment
    monkeypatch.setattr(import_api, "enqueue", lambda id: None)
    login(client, "admin@example.hu")
    supplier = client.post(
        "/api/v1/imports/suppliers", json={"name": "Teszt beszállító"}
    ).json()["id"]
    return client, target, supplier


def upload(client, supplier, content, filename="data.csv"):
    r = client.post(
        "/api/v1/imports/runs",
        data={"supplier_id": str(supplier)},
        files={"file": (filename, content)},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def work(target, id):
    with Session(target) as db:
        advance(db, id)


def approve(client, id, mapping=None, **extra):
    r = client.post(
        f"/api/v1/imports/runs/{id}/approve",
        json={
            "name": "Terméktörzs",
            "mapping": mapping or {"0": "sku", "1": "name", "2": "stock"},
            "identity_field": "sku",
            **extra,
        },
    )
    assert r.status_code == 200, r.text


def test_csv_original_numeric_empty_duplicate_and_idempotence(imports):
    c, t, s = imports
    data = "\ufeffSKU;NAME;QUANTITY\n00012;Termék;-2,5\n00012;Termék;-2,5\n00012;Másik;3\n;;\n;Hiányos;\n".encode()
    id = upload(c, s, data)
    work(t, id)
    a = c.get(f"/api/v1/imports/runs/{id}").json()
    assert a["config"]["delimiter"] == ";" and a["config"]["encoding"] == "utf-8-sig"
    assert a["analysis"]["columns"][0]["field"] == "sku"
    approve(c, id)
    work(t, id)
    work(t, id)
    result = c.get(f"/api/v1/imports/runs/{id}").json()
    assert result["state"] == "partial"
    assert result["counters"] == {"ready": 2, "duplicate": 1, "conflict": 1, "empty": 1}
    rs = c.get(f"/api/v1/imports/runs/{id}/rows").json()["items"]
    assert rs[0]["raw"] == ["00012", "Termék", "-2,5"]
    assert rs[0]["normalized"]["fields"] == {
        "sku": "00012",
        "name": "Termék",
        "stock": "-2.5",
    }
    assert rs[0]["normalized"]["provenance"]["sku"]["column"] == 0
    assert c.get(f"/api/v1/imports/runs/{id}/file").content == data
    assert (
        "conflicting_duplicate_key"
        in c.get(f"/api/v1/imports/runs/{id}/errors.csv").text
    )
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 2
        assert db.scalar(select(func.count()).select_from(ImportChange)) == 2


@pytest.mark.parametrize(
    "raw,field,value,issues",
    [
        ("001234", "sku", "001234", []),
        (
            "1,23E+12",
            "gtin",
            "1,23E+12",
            ["scientific_identifier_requires_review", "invalid_gtin"],
        ),
        ("", "gtin", None, []),
        ("-12,50", "stock", "-12.50", []),
        ("1.234,56", "price", "1234.56", []),
        ("1,234.56", "price", "1234.56", []),
        ("NaN", "price", None, ["invalid_number"]),
    ],
)
def test_numeric_and_identifier_semantics(raw, field, value, issues):
    assert normalize(field, raw) == (value, issues)


def test_xlsx_sheets_and_formula_original(tmp_path):
    w = Workbook()
    w.active.title = "Üres"
    s = w.create_sheet("Termékek")
    s.append(["SKU", "NAME", "QUANTITY"])
    s.append(["0001", "Gép", -4])
    s.append(["0002", "=1+2", 0])
    p = tmp_path / "a.xlsx"
    w.save(p)
    conf, a = analyze(p, "a.xlsx", {"sheet": "Termékek"})
    assert conf["sheets"] == ["Üres", "Termékek"] and a["headers"] == [
        "SKU",
        "NAME",
        "QUANTITY",
    ]
    assert list(rows(p, conf))[1:] == [
        (2, ["0001", "Gép", "-4"]),
        (3, ["0002", "=1+2", "0"]),
    ]


def test_financial_requires_approval_profile_reuse_and_content_drift(imports):
    c, t, s = imports
    data = b"SKU;NAME;LISTPRICE;CURRENCYCODE\n001;TV;123,50;HUF\n"
    id = upload(c, s, data)
    work(t, id)
    mapping = {"0": "sku", "1": "name", "2": "price", "3": "currency"}
    assert (
        c.post(
            f"/api/v1/imports/runs/{id}/approve",
            json={"name": "Ar", "mapping": mapping, "identity_field": "sku"},
        ).status_code
        == 422
    )
    approve(c, id, mapping, financial_approved=True, automatic=True)
    work(t, id)
    second = upload(c, s, b"NAME;SKU;CURRENCYCODE;LISTPRICE\nTV;001;HUF;124,50\n")
    work(t, second)
    r = c.get(f"/api/v1/imports/runs/{second}").json()
    assert r["state"] == "completed" and r["profile_id"] is not None
    third = upload(c, s, data.replace(b"HUF", b"EUR"))
    work(t, third)
    r = c.get(f"/api/v1/imports/runs/{third}").json()
    assert (
        r["state"] == "awaiting_approval"
        and "financial_context_changed" in r["analysis"]["drift"]
    )


def test_tenant_and_role_isolation(imports):
    c, t, s = imports
    id = upload(c, s, b"SKU;NAME\n1;Secret\n")
    login(c, "other@example.hu")
    for path in ["", "/rows", "/file", "/errors.csv"]:
        assert c.get(f"/api/v1/imports/runs/{id}" + path).status_code == 404
    assert c.get("/api/v1/imports/products?supplier_id=" + str(s)).json() == []
    assert (
        c.put(
            "/api/v1/imports/engines/unas", json={"name": "Attack", "fields": []}
        ).status_code
        == 403
    )
    login(c, "reviewer@example.hu")
    assert c.post("/api/v1/imports/suppliers", json={"name": "No"}).status_code == 403


def test_pause_resume_retry_and_exact_cross_file_join(imports):
    c, t, s = imports
    id = upload(c, s, b"SKU;NAME;QUANTITY\n001;TV;5\n")
    work(t, id)
    approve(c, id)
    assert (
        c.post(f"/api/v1/imports/runs/{id}/actions/pause").json()["state"] == "paused"
    )
    work(t, id)
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 0
    assert (
        c.post(f"/api/v1/imports/runs/{id}/actions/resume").json()["state"]
        == "processing"
    )
    work(t, id)
    second = upload(c, s, b"ITEM_CODE;QUANTITY\n001;-2\n")
    work(t, second)
    assert (
        c.get(f"/api/v1/imports/runs/{second}/join-suggestions").json()[0][
            "exact_sample_matches"
        ]
        == 1
    )
    approve(c, second, {"0": "sku", "1": "stock"}, feed_type="stock")
    work(t, second)
    ps = c.get(f"/api/v1/imports/products?supplier_id={s}").json()
    assert len(ps) == 1 and ps[0]["fields"] == {
        "sku": "001",
        "name": "TV",
        "stock": "-2",
    }
    assert (
        c.post(f"/api/v1/imports/runs/{second}/actions/retry-errors").status_code == 200
    )
    work(t, second)
    assert len(c.get(f"/api/v1/imports/products?supplier_id={s}").json()) == 1


def test_export_fields_crud_central_requirements_and_no_ai(imports):
    c, t, s = imports
    login(c)
    payload = {
        "name": "UNAS",
        "fields": [
            {
                "key": "sku",
                "label": "Cikkszám",
                "type": "text",
                "required": True,
                "internal_field": "sku",
            }
        ],
    }
    assert c.put("/api/v1/imports/engines/unas", json=payload).json()["version"] == 1
    assert c.get("/api/v1/imports/engines").json()[0]["fields"][0]["required"] is True
    login(c, "admin@example.hu")
    assert (
        c.post(
            "/api/v1/imports/export-profiles",
            json={"engine_key": "unas", "name": "Sajat", "fields": []},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/imports/export-profiles", json={"engine_key": "unas", **payload}
        ).status_code
        == 200
    )
    login(c)
    assert c.delete("/api/v1/imports/engines/unas/fields/sku").status_code == 200
    assert c.get("/api/v1/imports/engines").json()[0]["fields"] == []
    with pytest.raises(ValueError, match="kredit"):
        AISuggestionProvider().suggest([], authorized_credits=0)


def test_reference_shape_27_columns_4948_rows_only_three_products(imports):
    c, t, s = imports
    headers = ["SKU", "NAME", "QUANTITY"] + [f"Extra{i}" for i in range(24)]
    out = io.StringIO()
    import csv

    w = csv.writer(out, delimiter=";")
    w.writerow(headers)
    for i in range(3):
        w.writerow([f"000{i}", "Termék " + str(i), "-2,5"] + [""] * 24)
    for _ in range(4945):
        w.writerow([""] * 27)
    id = upload(c, s, ("\ufeff" + out.getvalue()).encode())
    work(t, id)
    approve(c, id)
    work(t, id)
    r = c.get(f"/api/v1/imports/runs/{id}").json()
    assert r["counters"] == {"ready": 3, "empty": 4945}
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 3


def test_header_drift_name_only_and_no_ean_required(imports):
    c, t, s = imports
    id = upload(c, s, b"Title\nOnly name\n")
    work(t, id)
    approve(c, id, {"0": "name"}, identity_field=None)
    work(t, id)
    row = c.get(f"/api/v1/imports/runs/{id}/rows").json()["items"][0]
    assert row["normalized"]["fields"] == {"name": "Only name"}
    assert "gtin" in row["normalized"]["missing_fields"]
    nextid = upload(c, s, b"Renamed\nOnly name\n")
    work(t, nextid)
    assert (
        c.get(f"/api/v1/imports/runs/{nextid}").json()["state"] == "awaiting_approval"
    )


def test_resource_limits_and_real_sql_error_visibility(imports, monkeypatch):
    c, t, s = imports
    monkeypatch.setenv("IMPORT_MAX_BYTES", "4")
    assert (
        c.post(
            "/api/v1/imports/runs",
            data={"supplier_id": s},
            files={"file": ("x.csv", b"12345")},
        ).status_code
        == 413
    )
    monkeypatch.delenv("IMPORT_MAX_BYTES")
    id = upload(c, s, b"SKU;NAME;QUANTITY\n001;TV;1\n002;TV2;2\n")
    work(t, id)
    approve(c, id)
    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "1")
    with pytest.raises(ValueError, match="termékszámkorlát"):
        work(t, id)
    r = c.get(f"/api/v1/imports/runs/{id}").json()
    assert r["state"] == "failed" and "ValueError" in r["error"]
    monkeypatch.delenv("IMPORT_MAX_PRODUCTS")
    assert c.post(f"/api/v1/imports/runs/{id}/actions/resume").status_code == 200
    work(t, id)
    assert len(c.get(f"/api/v1/imports/products?supplier_id={s}").json()) == 2


def test_large_csv_sampling_is_bounded(tmp_path):
    import tracemalloc

    p = tmp_path / "large.csv"
    with p.open("w") as f:
        f.write("SKU;NAME;QUANTITY\n")
        for i in range(50000):
            f.write(f"{i:08};Termek;2,5\n")
    tracemalloc.start()
    conf, a = analyze(p, "large.csv", {})
    assert len(a["preview"]) == 10
    count = sum(1 for _ in rows(p, conf))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert count == 50001 and peak < 8_000_000


def test_export_reference_115_optional_columns(imports):
    c, _, _ = imports
    login(c)
    w = Workbook()
    w.active.append([f"Áruházi mező {i}" for i in range(115)])
    out = io.BytesIO()
    w.save(out)
    r = c.post(
        "/api/v1/imports/engines/unas/reference",
        files={"file": ("unas.xlsx", out.getvalue())},
    )
    assert r.status_code == 200
    assert len(r.json()["fields"]) == 115 and not any(
        f["required"] for f in r.json()["fields"]
    )


def test_dates_duplicate_mapping_and_export_validation(imports):
    assert normalize("sale_end", "2026.11.14")[0] == "2026-11-14T00:00:00"
    assert normalize("sale_end", "unknown")[1] == ["uncertain_date"]
    c, t, s = imports
    id = upload(c, s, b"SKU;NAME\n001;TV\n")
    work(t, id)
    assert (
        c.post(
            f"/api/v1/imports/runs/{id}/approve",
            json={"name": "No", "mapping": {"0": "sku", "1": "sku"}},
        ).status_code
        == 422
    )
    login(c)
    assert (
        c.put(
            "/api/v1/imports/engines/unas",
            json={
                "name": "UNAS",
                "fields": [
                    {
                        "key": "bad field",
                        "label": "Hibas",
                        "type": "text",
                        "required": False,
                    }
                ],
            },
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/api/v1/imports/engines/unas",
            json={
                "name": "UNAS",
                "fields": [
                    {
                        "key": "price",
                        "label": "Ár",
                        "type": "number",
                        "required": True,
                        "validation": "nonnegative",
                    }
                ],
            },
        ).status_code
        == 200
    )
    login(c, "admin@example.hu")
    assert (
        c.post(
            "/api/v1/imports/export-profiles",
            json={
                "engine_key": "unas",
                "name": "Bypass",
                "fields": [
                    {"key": "price", "label": "Ár", "type": "text", "required": True}
                ],
            },
        ).status_code
        == 422
    )


def test_excel_identifier_number_format_and_precision(tmp_path):
    w = Workbook()
    s = w.active
    s.append(["SKU", "BARCODE", "NAME"])
    s.append([12, 1.2345e12, "TV"])
    s["A2"].number_format = "00000"
    s["B2"].number_format = "0.00E+00"
    p = tmp_path / "identifiers.xlsx"
    w.save(p)
    config, _ = analyze(p, "identifiers.xlsx", {})
    _, r = list(rows(p, config))[1]
    assert r[0] == "00012"
    assert normalize("sku", r[0]) == ("00012", [])
    assert "excel_identifier_precision_requires_review" in normalize("gtin", r[1])[1]


def test_paged_interpreted_preview_without_writing_products(imports):
    c, t, s = imports
    id = upload(c, s, b"SKU;NAME;QUANTITY\n001;TV;-2,5\n002;TV2;3\n")
    work(t, id)
    response = c.post(
        f"/api/v1/imports/runs/{id}/preview",
        json={"mapping": {"0": "sku", "2": "stock"}, "offset": 1},
    )
    assert response.status_code == 200
    r = response.json()["items"][0]
    assert r["line"] == 3 and r["raw"] == ["002", "TV2", "3"]
    assert (
        r["interpreted"]["sku"]["value"] == "002"
        and r["interpreted"]["stock"]["value"] == "3"
    )
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 0


def test_reused_profile_keeps_new_file_format_and_header_positions(imports):
    c, t, s = imports
    first = upload(c, s, b"SKU;NAME;QUANTITY\n001;TV;2\n")
    work(t, first)
    approve(c, first, automatic=True)
    work(t, first)
    second = upload(c, s, b"NAME,QUANTITY,SKU\nTV,2,001\n")
    work(t, second)
    r = c.get(f"/api/v1/imports/runs/{second}").json()
    assert r["state"] == "completed" and r["config"]["delimiter"] == ","
    assert r["config"]["mapping"] == {"2": "sku", "0": "name", "1": "stock"}
    assert {x["field"]: x["column"] for x in r["config"]["approved_columns"]} == {
        "sku": 2,
        "name": 0,
        "stock": 1,
    }
    assert len(c.get(f"/api/v1/imports/products?supplier_id={s}").json()) == 1
