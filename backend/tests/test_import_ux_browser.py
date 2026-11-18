"""Import preparation of legacy and new files against FastAPI on desktop and mobile."""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from app import import_api
from app.import_engine import advance
from conftest import login
from test_import_ux import besz_minta

DIST = Path(__file__).resolve().parents[2] / "frontend/dist"


def no_page_overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


@pytest.fixture
def ui(environment, monkeypatch):
    client, target, _, _ = environment

    def execute(id):
        with Session(target) as db:
            advance(db, id)

    monkeypatch.setattr(import_api, "enqueue", execute)
    login(client, "admin@example.hu")
    supplier = client.post("/api/v1/imports/suppliers", json={"name": "Minta Kft."}).json()["id"]

    def handle(route):
        u = urlparse(route.request.url)
        if u.path.startswith("/api/"):
            response = client.request(
                route.request.method,
                u.path + ("?" + u.query if u.query else ""),
                content=route.request.post_data_buffer,
                headers={"Content-Type": route.request.headers.get("content-type", "application/json")},
            )
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get("content-type", "application/json"))
        else:
            f = (DIST / (u.path.lstrip("/") or "index.html")).resolve()
            assert f.is_relative_to(DIST.resolve())
            route.fulfill(body=f.read_bytes(),
                          content_type=mimetypes.guess_type(f.name)[0] or "text/plain")

    def open_page(p, width, height):
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.route("http://import.test/**", handle)
        page.goto("http://import.test/")
        page.get_by_role("navigation").get_by_role("button", name="Import", exact=True).click()
        page.get_by_label("Webshopmotor").select_option("unas")
        page.get_by_label("Beszállító", exact=True).select_option(str(supplier))
        return browser, page

    def seed(content, name):
        r = client.post("/api/v1/imports/runs", data={"supplier_id": str(supplier)},
                        files={"file": (name, content)})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return client, target, open_page, seed


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_besz_minta_keeps_all_columns_and_does_not_map_purchase_to_sale(ui, width, height):
    client, _, open_page, _ = ui
    with sync_playwright() as p:
        browser, page = open_page(p, width, height)
        page.get_by_label("CSV, XLS, XLSX vagy XML fájl").set_input_files(
            {"name": "besz_minta.csv", "mimeType": "text/csv", "buffer": besz_minta()}
        )
        expect(page.get_by_text("3 termék · 27 oszlop")).to_be_visible(timeout=15000)
        rows = page.get_by_role("list", name="Forrásoszlopok").locator(":scope > li")
        expect(rows.or_(page.locator(".prep-bindings li"))).to_have_count(27)
        targets = page.get_by_role("region", name="UNAS-célmezők")
        expect(targets.get_by_role("list", name="Nettó ár hozzárendelései")).to_have_count(0)
        expect(targets.get_by_role("list", name="Bruttó ár hozzárendelései")).to_have_count(0)
        run = client.get("/api/v1/imports/runs").json()[0]
        assert run["analysis_only"] is True
        assert no_page_overflow(page)
        assert not page.errors
        browser.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_previous_files_remain_usable_including_a_processed_import(ui, width, height):
    client, _, open_page, seed = ui
    long_name = "nagyon_hosszu_beszallitoi_arlista_" + "x" * 180 + ".csv"
    ids = [seed(f"SKU;NAME\n{i:03d};Termék {i}\n".encode(), "besz_minta.csv") for i in range(25)]
    long_id = seed(b"SKU;NAME\n999;Hosszu\n", long_name)
    processed = ids[0]
    response = client.post(f"/api/v1/imports/runs/{processed}/approve",
                           json={"name": "P", "mapping": {"0": "sku", "1": "name"}, "identity_field": "sku"})
    assert response.status_code == 200
    with sync_playwright() as p:
        browser, page = open_page(p, width, height)
        page.get_by_text("Korábban feltöltött fájlok", exact=True).click()
        history = page.locator(".prep-history li")
        expect(history).to_have_count(25)
        page.get_by_role("button", name=f"#{long_id} · {long_name}", exact=True).click()
        expect(page.get_by_role("link", name="Eredeti fájl")).to_have_attribute(
            "href", f"/api/v1/imports/runs/{long_id}/file"
        )
        assert no_page_overflow(page)
        page.get_by_role("button", name="Korábbi fájlok betöltése").click()
        expect(history).to_have_count(26)
        page.get_by_role("button", name=f"#{processed} · besz_minta.csv", exact=True).click()
        expect(page.get_by_role("link", name="Eredeti fájl")).to_have_attribute(
            "href", f"/api/v1/imports/runs/{processed}/file"
        )
        expect(page.get_by_role("list", name="Cikkszám hozzárendelései").locator("samp")).to_have_text("000")
        expect(page.get_by_text("Feldolgozott sorok", exact=True)).to_have_count(0)
        assert client.get(f"/api/v1/imports/runs/{processed}").json()["state"] == "completed"
        assert not page.errors
        browser.close()
