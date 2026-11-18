"""Integrated browser coverage, enabled when the TEMPLATE-RESULT-01 backend is present."""

import csv
from http.server import BaseHTTPRequestHandler, HTTPServer
import mimetypes
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from app import import_api, import_engine
from conftest import login

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
PREFIX = "/api/v1/imports"


@pytest.fixture
def result_site(environment, monkeypatch):
    client, engine, _, _ = environment
    login(client, "admin@example.hu")
    supplier_id = client.post(PREFIX + "/suppliers", json={"name": "UNAS teszt"}).json()["id"]

    def analyse(run_id):
        with Session(engine) as db:
            import_engine.advance(db, run_id)

    monkeypatch.setattr(import_api, "enqueue", analyse)

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
            yield f"http://127.0.0.1:{server.server_port}/", supplier_id, client
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("width", [390, 1440])
def test_unas_result_after_save_paging_download_and_revision(request, width, tmp_path):
    pytest.importorskip("app.template_result_views", reason="Requires the TEMPLATE-RESULT-01 backend")
    url, supplier, client = request.getfixturevalue("result_site")
    source = "SKU;NAME;CATEGORY;Nettó ár;PHOTO\n"
    source += "0001;Első termék;Kertek;1000;nem-kep-url\n"
    source += "".join(
        f"{i:04d};Termék {i};Kertek;1000;https://example.invalid/{i}.png\n"
        for i in range(2, 52)
    )
    source += ";Hiányos termék;Kertek;1000;\n"
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
            expect(page.get_by_text("52 termék · 5 oszlop")).to_be_visible()
            page.get_by_label("Célmező: 4. Nettó ár", exact=True).select_option(label="Nettó ár")
            page.get_by_role("button", name="5. PHOTO hozzárendelés törlése").click()
            page.get_by_label("Célmező: 5. PHOTO", exact=True).select_option(label="Kép")
            expect(page.get_by_role("list", name="Kép hozzárendelései").locator("samp")).to_have_text("nem-kep-url")
            page.get_by_label("Sablon neve").fill("UNAS minta")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            result = page.get_by_role("region", name="UNAS eredmény", exact=True)
            table = result.get_by_role("table")
            expect(result.get_by_text("52 sor · 51 letölthető · 1 kizárt", exact=False)).to_be_visible()
            expect(table.get_by_role("columnheader", name="Bruttó Ár", exact=True)).to_be_visible()
            expect(table.get_by_role("row").nth(1)).to_contain_text("1270")
            image_error = table.get_by_role("button", name="Hiba: Kép link, 2. sor")
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

            result.get_by_role("button", name="Vissza a megfeleltetéshez").click()
            expect(page.get_by_label("Sablon neve")).to_have_value("UNAS minta")
            page.get_by_role("button", name="5. PHOTO hozzárendelés törlése").click()
            expect(page.get_by_label("Célmező: 5. PHOTO")).to_be_visible()
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(result.get_by_text("Sablon mentve: UNAS minta · v2")).to_be_visible()
            expect(table.get_by_role("columnheader", name="Cikkszám", exact=True)).to_be_visible()
            expect(table.get_by_role("columnheader", name="Kép link", exact=True)).to_have_count(0)
            assert client.get(PREFIX + "/runs").json()[0]["analysis_only"]
            assert not errors
