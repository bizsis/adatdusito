"""Template generation and both downloads in the real UI at desktop and 390 px."""

import csv
import re
import io
from pathlib import Path
import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from app import template_engine as te
from test_import_ux_browser import no_page_overflow
from app import import_api
from app.import_engine import advance
from conftest import login
from urllib.parse import urlparse
import mimetypes
from test_product_parameters import install_catalog, WASHER


@pytest.fixture
def ui(environment, monkeypatch):
    client, target, _, _ = environment

    def imported(id):
        with Session(target) as db:
            advance(db, id)

    monkeypatch.setattr(import_api, "enqueue", imported)
    login(client, "admin@example.hu")
    supplier = client.post(
        "/api/v1/imports/suppliers", json={"name": "Sablon teszt"}
    ).json()["id"]
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    # Real loopback HTTP: Chromium cancels intercepted download navigations.
    # API requests still exercise the real FastAPI app and tenant-scoped DB.
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                result = client.request(
                    self.command,
                    self.path,
                    content=body or None,
                    headers={
                        "Content-Type": self.headers.get(
                            "Content-Type", "application/json"
                        )
                    },
                )
                data, status = result.content, result.status_code
                headers = {
                    k: v
                    for k, v in result.headers.items()
                    if k in {"content-type", "content-disposition", "cache-control"}
                }
            else:
                file = (dist / (url.path.lstrip("/") or "index.html")).resolve()
                assert file.is_relative_to(dist.resolve())
                data, status = file.read_bytes(), 200
                headers = {
                    "Content-Type": mimetypes.guess_type(file.name)[0] or "text/plain"
                }
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = handle_request

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def open_page(p, width, height):
        browser = p.chromium.launch(
            executable_path=(
                "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None
            ),
            args=["--no-sandbox"],
        )
        page = browser.new_page(
            viewport={"width": width, "height": height}, accept_downloads=True
        )
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/")
        page.get_by_role("navigation").get_by_role(
            "button", name="Beszállítói import", exact=True
        ).click()
        page.locator("label", has_text=re.compile(r"^\s*Beszállító")).locator(
            "select"
        ).first.select_option(str(supplier))
        return browser, page

    try:
        yield client, target, open_page, None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_template_before_enrichment_both_downloads_and_category(
    ui, monkeypatch, width, height, tmp_path
):
    _, target, open_page, _ = ui
    install_catalog(target)

    def execute(id):
        with Session(target) as db:
            te.build(db, id)

    monkeypatch.setattr(te, "enqueue", execute)
    with sync_playwright() as p:
        browser, page = open_page(p, width, height)
        page.get_by_label("CSV/XLSX fájl").set_input_files(
            {
                "name": "template.csv",
                "mimeType": "text/csv",
                "buffer": "SKU;NAME;EAN\n001;Gép;000123\n002;Másik;000456\n003;Harmadik;000789\n".encode(),
            }
        )
        panel = page.get_by_role("region", name="Adatdúsítási munkasablon")
        expect(panel).to_be_visible()
        panel.get_by_text("Oszlopok és kategóriák beállítása", exact=True).click()
        panel.get_by_label("Sablon kategóriája", exact=True).select_option(WASHER)
        panel.get_by_role("button", name="Sablon elkészítése", exact=True).click()
        expect(panel.get_by_role("status")).to_contain_text("ready_for_enrichment")
        expect(
            panel.get_by_role("button", name="Adatdúsítás indítása", exact=True)
        ).to_be_disabled()
        for format in ["xlsx", "csv"]:
            with page.expect_download() as info:
                panel.get_by_role(
                    "link", name=f"Sablon letöltése – {format.upper()}", exact=True
                ).click()
            path = tmp_path / f"template.{format}"
            info.value.save_as(path)
            if format == "xlsx":
                sheet = load_workbook(path).active
                assert sheet.max_row == 4 and sheet.cell(2, 1).value == "001"
                assert sheet.cell(2, 3).value == "000123"
                headers = [c.value for c in sheet[1]]
            else:
                data = list(
                    csv.reader(
                        io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"
                    )
                )
                assert len(data) == 4 and data[1][:3] == ["001", "Gép", "000123"]
                headers = data[0]
            assert "Teljesítmény (W) [eMAG 385/6506]" in headers
        panel.get_by_text("Sablon előnézete és paraméteroszlopai", exact=True).click()
        expect(panel.locator("thead th").filter(has_text="kötelező")).to_have_count(3)
        assert no_page_overflow(page)
        assert not page.errors
        browser.close()
