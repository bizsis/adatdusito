"""Worktable losslessness, category provenance, isolation and no AI dispatch."""

import csv
import io
from openpyxl import Workbook, load_workbook
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import pytest

from app import template_engine as te
from app.import_models import ImportRun, ImportChunk
from app.template_models import ImportTemplate, TemplateChunk
from app.models import CatalogValue
from test_supplier_import import imports, upload, work
from test_product_parameters import install_catalog, WASHER, VACUUM, WASHER_DRYER
from conftest import login


@pytest.fixture
def templates(imports, monkeypatch):
    client, target, supplier = imports
    sent = []
    monkeypatch.setattr(te, "enqueue", sent.append)
    return client, target, supplier, sent


def source(fixture, text=None, filename="source.csv"):
    client, target, supplier, _ = fixture
    text = (
        text
        if text is not None
        else "SKU;Termék Név;EAN;Nettó Ár;Saját\n0001;Gép;0012345678905;123,45; eredeti \n0002;Másik;0000000000012;;x\n0003;Harmadik;0000000000013;;y\n".encode()
    )
    id = upload(client, supplier, text, filename)
    work(target, id)
    return id


def generate(fixture, run_id, body=None):
    client, target, _, sent = fixture
    response = client.post(f"/api/v1/imports/runs/{run_id}/templates", json=body or {})
    assert response.status_code == 200, response.text
    id = response.json()["id"]
    assert id in sent
    with Session(target) as db:
        te.build(db, id)
    result = client.get(f"/api/v1/imports/runs/{run_id}/template").json()
    assert result["state"] == "ready_for_enrichment", result
    return result


def download(client, run, item, format="csv"):
    response = client.get(f"/api/v1/imports/runs/{run}/templates/{item['id']}/{format}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    return response.content


def test_three_products_lossless_no_duplicate_fields_and_both_downloads(templates):
    client, target, _, _ = templates
    run = source(templates)
    item = generate(templates, run)
    data = list(
        csv.reader(
            io.StringIO(download(client, run, item).decode("utf-8-sig")), delimiter=";"
        )
    )
    assert len(data) == 4
    assert data[0][:5] == ["SKU", "Termék Név", "EAN", "Nettó Ár", "Saját"]
    assert data[1][:5] == ["0001", "Gép", "0012345678905", "123,45", " eredeti "]
    assert data[2][:5] == ["0002", "Másik", "0000000000012", "", "x"]
    assert data[3][:5] == ["0003", "Harmadik", "0000000000013", "", "y"]
    assert "Cikkszám" not in data[0]  # SKU has its meaning; no duplicate
    assert data[0].count("Termék Név") == 1 and data[0].count("Nettó Ár") == 1
    assert "Bruttó Ár" in data[0] and data[1][data[0].index("Bruttó Ár")] == ""
    assert "Akciós Bruttó Ár" in data[0]
    workbook = load_workbook(io.BytesIO(download(client, run, item, "xlsx")))
    sheet = workbook.active
    assert sheet.max_row == 4 and sheet.cell(2, 1).value == "0001"
    assert (
        sheet.cell(2, 1).data_type == "s" and sheet.cell(2, 3).value == "0012345678905"
    )
    with Session(target) as db:
        assert db.get(ImportRun, run).state == "awaiting_approval"
        assert db.get(ImportRun, run).approved_by is None
    assert item["manifest"]["native_unas_export"] is False


def test_only_assigned_profiles_union_keeps_category_specific_ids(templates):
    client, target, _, _ = templates
    install_catalog(target)
    run = source(templates)
    with Session(target) as db:
        values_before = db.scalar(select(func.count()).select_from(CatalogValue))
    item = generate(
        templates,
        run,
        {"category": {"node_id": WASHER}, "rows": {"3": {"node_id": VACUUM}}},
    )
    params = [c for c in item["manifest"]["columns"] if c["kind"] == "parameter"]
    assert len(params) == 9
    assert {c["donor"] for c in params} == {385, 58}
    assert sum(c["mandatory"] for c in params) == 4
    assert len({c["key"] for c in params}) == len(params)
    data = list(
        csv.reader(
            io.StringIO(download(client, run, item).decode("utf-8-sig")), delimiter=";"
        )
    )
    assert all(not v for v in data[1][-9:])
    assert "Mosógépek" in data[1][data[0].index("Kategória")]
    assert item["manifest"]["catalog_version_id"] == 1
    with Session(target) as db:
        assert (
            db.scalar(select(func.count()).select_from(CatalogValue)) == values_before
        )


def test_unassigned_donors_not_added_and_pending_review_blocked(templates):
    client, target, _, _ = templates
    install_catalog(target)
    run = source(templates)
    item = generate(templates, run)
    assert not [c for c in item["manifest"]["columns"] if c["kind"] == "parameter"]
    response = client.post(
        f"/api/v1/imports/runs/{run}/templates",
        json={"category": {"node_id": WASHER_DRYER}},
    )
    assert response.status_code == 422


def test_xlsx_numeric_zero_formats_and_formula_are_literal(templates):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SKU", "NAME", "EAN", "Note"])
    sheet.append([12, "Gép", "0000000000001", "=1+2"])
    sheet.cell(2, 1).number_format = "000000"
    buffer = io.BytesIO()
    workbook.save(buffer)
    run = source(templates, buffer.getvalue(), "a.xlsx")
    item = generate(templates, run)
    sheet = load_workbook(io.BytesIO(download(templates[0], run, item, "xlsx"))).active
    assert sheet.cell(2, 1).value == "000012"
    assert sheet.cell(2, 4).value == "=1+2" and sheet.cell(2, 4).data_type == "s"
    assert item["manifest"]["warnings"]


def test_blank_rows_extra_columns_and_duplicates_preserved(templates):
    run = source(templates, b"SKU;NAME;Own;Own\n001;A;x;y;extra\n;;;;\n002;B;;z\n")
    item = generate(templates, run)
    data = list(
        csv.reader(
            io.StringIO(download(templates[0], run, item).decode("utf-8-sig")),
            delimiter=";",
        )
    )
    assert len(data) == 4 and data[0][:5] == ["SKU", "NAME", "Own", "Own", ""]
    assert data[1][:5] == ["001", "A", "x", "y", "extra"]
    assert not any(data[2])
    assert item["manifest"]["rows"] == 3 and item["manifest"]["products"] == 2


def test_explicit_mapping_does_not_overwrite_or_treat_list_purchase_as_sale(templates):
    run = source(
        templates, b"SKU;NAME;LISTPRICE;LASTINITIALCOST;My net\n001;A;100;50;80\n"
    )
    item = generate(templates, run, {"mapping": {"Nettó Ár": 4}})
    assert item["manifest"]["mapping"]["Nettó Ár"] == 4
    assert all(c["header"] != "Nettó Ár" for c in item["manifest"]["columns"])
    assert te.field_mapping(["LISTPRICE", "LASTINITIALCOST", "price"]) == {}
    assert list(
        csv.reader(
            io.StringIO(download(templates[0], run, item).decode("utf-8-sig")),
            delimiter=";",
        )
    )[1][:5] == ["001", "A", "100", "50", "80"]


def test_snapshots_repeat_download_and_survive_source_retention(templates):
    client, target, _, _ = templates
    run = source(templates)
    first = generate(templates, run)
    contents = download(client, run, first)
    second = generate(templates, run)
    assert second["id"] != first["id"]
    with Session(target) as db:
        from sqlalchemy import delete

        db.execute(delete(ImportChunk).where(ImportChunk.run_id == run))
        db.commit()
    assert download(client, run, first) == contents
    assert download(client, run, second) == contents


def test_tenant_permissions_csrf_origin_and_cascade_delete(templates):
    client, target, _, _ = templates
    run = source(templates)
    item = generate(templates, run)
    login(client, "other@example.hu")
    assert client.get(f"/api/v1/imports/runs/{run}/template").status_code == 404
    assert (
        client.get(
            f"/api/v1/imports/runs/{run}/templates/{item['id']}/xlsx"
        ).status_code
        == 404
    )
    login(client, "reviewer@example.hu")
    assert (
        client.post(f"/api/v1/imports/runs/{run}/templates", json={}).status_code == 403
    )
    login(client, "admin@example.hu")
    saved = client.headers.pop("X-CSRF-Token")
    assert (
        client.post(f"/api/v1/imports/runs/{run}/templates", json={}).status_code == 403
    )
    client.headers["X-CSRF-Token"] = saved
    assert (
        client.post(
            f"/api/v1/imports/runs/{run}/templates",
            json={},
            headers={"Origin": "https://bad.invalid"},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/imports/runs/{run}").status_code == 200
    with Session(target) as db:
        assert not db.get(ImportTemplate, item["id"])
        assert not db.scalar(
            select(TemplateChunk).where(TemplateChunk.template_id == item["id"])
        )


def test_auto_schedule_never_dispatches_ai_and_build_idempotent(templates, monkeypatch):
    _, target, _, sent = templates
    run = source(templates)
    from app.worker import celery

    monkeypatch.setattr(
        celery,
        "send_task",
        lambda *a, **k: pytest.fail("No other task, AI or credit consumption allowed"),
    )
    with Session(target) as db:
        te.auto_template(db, run)
        assert len(sent) == 1
        te.build(db, sent[0])
        item = db.get(ImportTemplate, sent[0])
        digest = item.manifest["artifacts"]
        te.build(db, sent[0])
        assert item.manifest["artifacts"] == digest


def test_missing_source_failure_isolated_from_run_and_prior_snapshot(templates):
    client, target, _, _ = templates
    run = source(templates)
    first = generate(templates, run)
    with Session(target) as db:
        from sqlalchemy import delete

        db.execute(delete(ImportChunk).where(ImportChunk.run_id == run))
        db.commit()
        item = te.create_snapshot(db, db.get(ImportRun, run))
        te.build(db, item.id)
        assert (
            item.state == "failed"
            and db.get(ImportRun, run).state == "awaiting_approval"
        )
    assert download(client, run, first)


def test_actual_import_worker_queues_template_automatically_and_retry_is_idempotent(
    templates, monkeypatch
):
    client, target, supplier, sent = templates
    from app import import_engine

    monkeypatch.setattr(import_engine, "engine", lambda: target)
    id = upload(client, supplier, b"SKU;NAME\n001;A\n002;B\n003;C\n")
    import_engine.process_import.run(id)
    assert len(sent) == 1
    import_engine.process_import.run(id)
    assert len(sent) == 1
    with Session(target) as db:
        te.build(db, sent[0])
        item = db.get(ImportTemplate, sent[0])
        assert item.manifest["products"] == 3
        assert db.get(ImportRun, id).state == "awaiting_approval"


def test_parameter_values_from_exact_source_column_only_for_assigned_donor(templates):
    _, target, _, _ = templates
    install_catalog(target)
    run = source(templates, "SKU;NAME;Szín\n001;A;Fehér\n002;B;Fekete\n".encode())
    item = generate(
        templates,
        run,
        {"category": {"node_id": WASHER}, "rows": {"3": {"node_id": VACUUM}}},
    )
    columns = item["manifest"]["columns"]
    index = next(i for i, c in enumerate(columns) if c["key"] == "emag:385:6507")
    assert item["manifest"]["preview"][0]["values"][index] == "Fehér"
    assert item["manifest"]["preview"][1]["values"][index] == ""
    assert item["manifest"]["preview"][1]["values"][2] == "Fekete"


def test_duplicate_unas_headers_require_explicit_choice_not_extra_column(templates):
    client, _, _, _ = templates
    run = source(templates, "SKU;NAME;Nettó Ár;Nettó Ár\n001;A;100;200\n".encode())
    response = client.post(f"/api/v1/imports/runs/{run}/templates", json={})
    assert response.status_code == 422
    item = generate(templates, run, {"mapping": {"Nettó Ár": 3}})
    assert sum(c["header"] == "Nettó Ár" for c in item["manifest"]["columns"]) == 2
    assert item["manifest"]["mapping"]["Nettó Ár"] == 3


def test_bad_mapping_and_missing_physical_row_fail_without_changing_import(templates):
    client, target, _, _ = templates
    run = source(templates)
    for body in [
        {"mapping": {"Bruttó Ár": 999}},
        {"mapping": {"Cikkszám": 0, "Termék Név": 0}},
        {"category": {"node_id": "not-a-node"}},
    ]:
        assert (
            client.post(f"/api/v1/imports/runs/{run}/templates", json=body).status_code
            == 422
        )
    result = client.post(
        f"/api/v1/imports/runs/{run}/templates",
        json={"rows": {"999": {"node_id": WASHER}}},
    ).json()
    with Session(target) as db:
        te.build(db, result["id"])
        assert db.get(ImportTemplate, result["id"]).state == "failed"
        assert db.get(ImportRun, run).state == "awaiting_approval"


def test_existing_accepted_product_classification_supplies_parameters(templates):
    client, target, supplier, _ = templates
    from test_product_parameters import washer
    from app.import_models import SupplierProduct

    install_catalog(target)
    product_id = washer(client, target, supplier)
    with Session(target) as db:
        run_id = db.get(SupplierProduct, product_id).last_run_id
    item = generate(templates, run_id)
    assert (
        len([c for c in item["manifest"]["columns"] if c["kind"] == "parameter"]) == 7
    )
    assert item["manifest"]["assignments"]["2"]["donor"] == 385


def test_too_many_physical_blank_rows_fail_early_without_partial_artifact(templates):
    client, target, _, _ = templates
    run = source(templates, b"SKU;NAME\n001;A\n" + b"\n" * 1048575)
    response = client.post(f"/api/v1/imports/runs/{run}/templates", json={})
    id = response.json()["id"]
    with Session(target) as db:
        te.build(db, id)
        item = db.get(ImportTemplate, id)
        assert item.state == "failed" and "sorkorlát" in item.error
        assert db.get(ImportRun, run).state == "awaiting_approval"
        assert not db.scalar(
            select(TemplateChunk).where(TemplateChunk.template_id == id)
        )
    assert (
        client.get(f"/api/v1/imports/runs/{run}/templates/{id}/xlsx").status_code == 409
    )
