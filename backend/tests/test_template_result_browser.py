"""Integrated browser coverage against the UNAS result API and actual import worker."""

import csv
from http.server import BaseHTTPRequestHandler, HTTPServer
import mimetypes
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest
from celery.app.task import Task
from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import import_api, import_engine
from app.import_models import SupplierProduct
from app.product_models import ProductJob
from app.template_models import ImportTemplate
from conftest import login

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
PREFIX = "/api/v1/imports"


@pytest.fixture
def result_site(environment, monkeypatch):
    client, engine, _, _ = environment
    login(client, "admin@example.hu")
    supplier_id = client.post(PREFIX + "/suppliers", json={"name": "UNAS teszt"}).json()["id"]

    dispatched = []
    monkeypatch.setattr(Task, "apply_async", lambda task, *_, **__: dispatched.append(task.name))
    monkeypatch.setattr(import_engine, "engine", lambda: engine)
    monkeypatch.setattr(import_api, "enqueue", import_engine.process_import)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def handle_request(self):
            path = urlparse(self.path).path
            headers = {}
            if path.startswith("/api/"):
                if self.command != "GET":
                    assert self.headers["X-CSRF-Token"] == client.headers["X-CSRF-Token"]
                response = client.request(
                    self.command, self.path,
                    content=self.rfile.read(int(self.headers.get("Content-Length", "0"))),
                    headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
                )
                body, status = response.content, response.status_code
                for name in ("content-type", "content-disposition"):
                    if name in response.headers:
                        headers[name] = response.headers[name]
            else:
                file = (DIST / (path.lstrip("/") or "index.html")).resolve()
                assert file.is_relative_to(DIST)
                if not file.is_file():
                    self.send_error(404)
                    return
                body, status = file.read_bytes(), 200
                headers["Content-Type"] = mimetypes.guess_type(file.name)[0] or "text/plain"
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = handle_request

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/", supplier_id, client, engine, dispatched
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("width", [390, 1440])
def test_unas_result_after_save_paging_download_and_revision(result_site, width, tmp_path):
    url, supplier, client, engine, dispatched = result_site
    main = "https://example.invalid/main.png"
    second = "https://example.invalid/second.png"
    third = "https://example.invalid/third.png"
    long_value = "Fekete termék részletes műszaki adatokkal " * 20 + "vége."
    fields = client.get(PREFIX + "/template-targets?engine=unas").json()["targets"]
    expanded = any(field.get("added_in") == "template-fix-02" for field in fields)
    color_header = "Paraméter: Szín" if expanded else "Color"
    source = f"SKU;NAME;CATEGORY;Nettó ár;PHOTO;EAN;{color_header};Image3;Image2\n"
    source += f"0001;Első termék;Kertek;1000;{main};0012345678905;{long_value};{third};{second}\n"
    source += f"0002;Üres képhely;Kertek;1000;{main};;;{third};\n"
    source += f"0003;Hibás második kép;Kertek;1000;{main};;;;nem-kep-url\n"
    source += "".join(
        f"{i:04d};Termék {i};Kertek;1000;https://example.invalid/{i}.png;;;;\n"
        for i in range(4, 52)
    )
    source += ";Hiányos termék;Kertek;1000;;;;;\n"
    if expanded:
        header, *rows = source.splitlines()
        source = (
            header + ";SupplierMeta;SupplierFlag\n"
            + rows[0] + ";Keresőcím;1\n"
            + "\n".join(f"{row};;" for row in rows[1:]) + "\n"
        )
    with sync_playwright() as p:
        chromium = Path("/usr/bin/chromium")
        with p.chromium.launch(executable_path=str(chromium) if chromium.exists() else None,
                               args=["--no-sandbox"]) as browser:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.get_by_role("navigation").get_by_role("button", name="Import", exact=True).click()
            page.get_by_label("Webshopmotor").select_option("unas")
            page.get_by_label("Beszállító", exact=True).select_option(str(supplier))
            expect(page.get_by_role("region", name="UNAS-célmezők")).to_have_count(0)
            page.get_by_label("CSV, XLS, XLSX vagy XML fájl").set_input_files(
                {"name": "nagy.csv", "mimeType": "text/csv", "buffer": source.encode()}
            )
            expect(page.get_by_text(f"52 termék · {11 if expanded else 9} oszlop")).to_be_visible()
            displayed_keys = page.locator(".prep-targets [data-target]").evaluate_all(
                "nodes => nodes.map(node => node.dataset.target)"
            )
            assert set(displayed_keys) == {field["key"] for field in fields}
            if expanded:
                titles = page.locator(".prep-targets .prep-field-title strong")
                for label in ("SEO Title", "CrossSale1", "CrossSale3", "UpSale2", "További lapfül címe 3"):
                    expect(titles.get_by_text(label, exact=True)).to_have_count(1)
                page.get_by_label("Célmező: 10. SupplierMeta", exact=True).select_option(label="SEO Title")
                page.get_by_label("Célmező: 11. SupplierFlag", exact=True).select_option(label="UpSale2")
            page.get_by_label("Célmező: 4. Nettó ár", exact=True).select_option(label="Nettó ár")
            image_labels = ("5. PHOTO", "9. Image2", "8. Image3")
            for label in image_labels:
                remove = page.get_by_role("button", name=f"{label} hozzárendelés törlése")
                if remove.count():
                    remove.click()
            for label in image_labels:
                page.get_by_label(f"Célmező: {label}", exact=True).select_option(label="Kép")
            if expanded:
                expect(page.get_by_role("list", name="Paraméter: Szín hozzárendelései")).to_be_visible()
                expect(page.get_by_role("dialog")).to_have_count(0)
            else:
                page.get_by_role("button", name="Javaslat átvétele: Paraméter: Szín").click()
                page.get_by_role("dialog").get_by_role("button", name="Paraméter elfogadása").click()
            expect(page.get_by_role("list", name="Kép hozzárendelései").locator("samp")).to_have_text(
                [main, second, third]
            )
            page.get_by_label("Sablon neve").fill("UNAS minta")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            result = page.get_by_role("region", name="UNAS eredmény", exact=True)
            table = result.get_by_role("table")
            expect(result.get_by_text("52 sor · 51 letölthető · 1 kizárt", exact=False)).to_be_visible()
            expect(page.get_by_label("CSV, XLS, XLSX vagy XML fájl")).to_be_hidden()
            expect(page.get_by_role("heading", name="Előkészítés / Sablonkészítés")).to_have_count(0)
            expect(table.get_by_role("columnheader", name="Paraméter: Szín", exact=True)).to_be_visible()
            value = table.get_by_role("button", name=long_value, exact=True)
            expect(value).to_be_visible()
            assert value.evaluate("node => node.scrollWidth > node.clientWidth && getComputedStyle(node).textOverflow === 'ellipsis'")
            assert table.get_by_role("row").nth(1).evaluate("node => node.offsetHeight === node.nextElementSibling.offsetHeight")
            value.click()
            dialog = page.get_by_role("dialog", name="Paraméter: Szín")
            expect(dialog).to_contain_text(long_value)
            dialog.get_by_role("button", name="Bezárás").click()
            expect(dialog).to_have_count(0)
            expect(table.get_by_role("columnheader", name="Bruttó Ár", exact=True)).to_be_visible()
            expect(table.get_by_role("row").nth(1)).to_contain_text("1270")
            expect(table.get_by_role("cell", name=f"{main}|{second}|{third}")).to_be_visible()
            expect(table.get_by_role("button", name="Hiba: Kép link, 2. sor")).to_have_count(0)
            expect(table.get_by_role("cell", name=f"{main}|{third}", exact=False)).to_be_visible()
            gap_warning = table.get_by_role("button", name="Figyelmeztetés: Kép link, 3. sor")
            gap_warning.focus()
            expect(page.get_by_role("tooltip")).to_contain_text("üres képhelyek kimaradnak")
            gap_warning.blur()
            image_error = table.get_by_role("button", name="Hiba: Kép link, 4. sor")
            if width == 1440:
                image_error.hover()
            else:
                image_error.focus()
            expect(page.get_by_role("tooltip")).to_contain_text("érvényes HTTP vagy HTTPS")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            result.get_by_role("button", name="Következő oldal").click()
            expect(table.get_by_role("cell", name="0051", exact=True)).to_be_visible()
            expect(table.get_by_role("button", name="53. sor hibái és figyelmeztetései")).to_be_visible()
            result.get_by_role("button", name="Újragenerálás").click()
            expect(table.get_by_role("cell", name="0001", exact=True)).to_be_visible()
            expect(result.get_by_role("button", name="Dúsítás indítása", exact=False)).to_be_disabled()
            for format in ("csv", "xlsx"):
                with page.expect_download() as download:
                    result.get_by_role("link", name=f"UNAS {format.upper()} letöltése").click()
                file = tmp_path / f"unas.{format}"
                download.value.save_as(file)
                if format == "csv":
                    with file.open(encoding="utf-8-sig", newline="") as stream:
                        rows = list(csv.reader(stream, delimiter=";"))
                else:
                    book = load_workbook(file, read_only=True)
                    rows = list(book.active.values)
                    book.close()
                assert len(rows) == 52 and rows[0][0] == "Cikkszám" and rows[1][0] == "0001"
                first = dict(zip(rows[0], rows[1]))
                assert first["Nettó Ár"] == "1000" and first["Bruttó Ár"] == "1270"
                assert first["Státusz"] == "1" and first["Kép link"] == f"{main}|{second}|{third}"
                assert next(value for header, value in first.items() if header.startswith("Paraméter: EAN|")) == "0012345678905"
                assert next(value for header, value in first.items() if header.startswith("Paraméter: Szín|")) == long_value
                if expanded:
                    assert first["SEO Title"] == "Keresőcím"
                    assert first["UpSale2"] == "1"
                image_col = rows[0].index("Kép link")
                assert rows[2][image_col] == f"{main}|{third}"
                assert rows[3][image_col] == f"{main}|nem-kep-url"
                assert rows[4][image_col] == "https://example.invalid/4.png"

            result.get_by_role("button", name="Vissza a megfeleltetéshez").click()
            expect(page.get_by_label("Sablon neve")).to_have_value("UNAS minta")
            expect(page.get_by_label("CSV, XLS, XLSX vagy XML fájl")).to_be_hidden()
            for label in image_labels:
                page.get_by_role("button", name=f"{label} hozzárendelés törlése").click()
                expect(page.get_by_label(f"Célmező: {label}", exact=True)).to_be_visible()
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(result.get_by_text("Sablon mentve: UNAS minta · v2")).to_be_visible()
            expect(table.get_by_role("columnheader", name="Cikkszám", exact=True)).to_be_visible()
            expect(table.get_by_role("columnheader", name="Kép link", exact=True)).to_have_count(0)
            run = client.get(PREFIX + "/runs").json()[0]
            assert run["analysis_only"] and run["state"] == "awaiting_approval"
            assert dispatched == []
            with Session(engine) as db:
                for model in (SupplierProduct, ProductJob, ImportTemplate):
                    assert db.scalar(select(func.count()).select_from(model)) == 0
            assert not errors
