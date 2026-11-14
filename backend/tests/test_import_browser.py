"""The actual import UI against FastAPI and real import execution, desktop/mobile."""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from app.import_engine import advance
from app import import_api
from conftest import login


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_upload_approve_preview_and_export_admin(
    environment, monkeypatch, width, height
):
    client, target, _, _ = environment

    def execute(id):
        with Session(target) as db:
            advance(db, id)

    monkeypatch.setattr(import_api, "enqueue", execute)
    login(client, "admin@example.hu")
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"

    def handle(route):
        u = urlparse(route.request.url)
        if u.path.startswith("/api/"):
            response = client.request(
                route.request.method,
                u.path + ("?" + u.query if u.query else ""),
                content=route.request.post_data_buffer,
                headers={
                    "Content-Type": route.request.headers.get(
                        "content-type", "application/json"
                    )
                },
            )
            route.fulfill(
                status=response.status_code,
                body=response.content,
                content_type=response.headers.get("content-type", "application/json"),
            )
        else:
            f = (dist / (u.path.lstrip("/") or "index.html")).resolve()
            assert f.is_relative_to(dist.resolve())
            route.fulfill(
                body=f.read_bytes(),
                content_type=mimetypes.guess_type(f.name)[0] or "text/plain",
            )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("http://import.test/**", handle)
        page.goto("http://import.test/")
        page.get_by_role("navigation").get_by_role(
            "button", name="Beszállítói import", exact=True
        ).click()
        page.get_by_label("Új beszállító neve").fill("UI Beszállító")
        page.get_by_role("button", name="Beszállító létrehozása").click()
        expect(page.get_by_label("CSV/XLSX fájl")).to_be_enabled()
        page.get_by_label("CSV/XLSX fájl").set_input_files(
            {
                "name": "ui.csv",
                "mimeType": "text/csv",
                "buffer": "SKU;NAME;QUANTITY\n0001;Teszt televízió;-2,5\n".encode(),
            }
        )
        expect(page.get_by_role("heading", name="#1 – Jóváhagyásra vár")).to_be_visible(
            timeout=15000
        )
        expect(page.get_by_label("Megfeleltetés: SKU")).to_have_value("sku")
        page.get_by_label("Jóváhagyott összekapcsolási kulcs").select_option("sku")
        page.get_by_role(
            "button", name="Megfeleltetés jóváhagyása és feldolgozás"
        ).click()
        expect(page.get_by_role("heading", name="#1 – Befejezve")).to_be_visible(
            timeout=15000
        )
        expect(page.get_by_text('"stock": "-2.5"', exact=False)).to_be_visible()
        page.get_by_role("navigation").get_by_role(
            "button", name="Webáruházmotorok / Exportmezők", exact=True
        ).click()
        page.get_by_role("button", name="Mező hozzáadása").click()
        page.get_by_label("key 0", exact=True).fill("sku")
        page.get_by_label("label 0", exact=True).fill("Cikkszám")
        # Tenant user cannot publish global definitions; only an own profile.
        expect(
            page.get_by_role("button", name="Központi definíció mentése")
        ).to_have_count(0)
        assert not errors
        browser.close()
