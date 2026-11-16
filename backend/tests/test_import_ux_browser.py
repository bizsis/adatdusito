"""IMPORT-UX-01/02 (#41, #42) in the real UI against FastAPI: desktop and 390 px."""

import mimetypes
import re
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
        page.get_by_role("navigation").get_by_role("button", name="Beszállítói import", exact=True).click()
        page.locator("label", has_text=re.compile(r"^\s*Beszállító")).locator("select").first.select_option(str(supplier))
        return browser, page

    def seed(content, name):
        r = client.post("/api/v1/imports/runs", data={"supplier_id": str(supplier)},
                        files={"file": (name, content)})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return client, target, open_page, seed


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_besz_minta_preview_is_compact_and_approval_reachable(ui, width, height):
    client, _, open_page, _ = ui
    with sync_playwright() as p:
        browser, page = open_page(p, width, height)
        page.get_by_label("CSV/XLSX fájl").set_input_files(
            {"name": "besz_minta.csv", "mimeType": "text/csv", "buffer": besz_minta()}
        )
        expect(page.get_by_role("heading", name="#1 – Jóváhagyásra vár")).to_be_visible(timeout=15000)
        expect(page.get_by_text(re.compile(r"Összes sor:\s*4\s?948.*nem üres.*3.*üres sor:\s*4\s?945"))).to_be_visible()
        # Only the 3 content rows, in a compact table (default 10 per page).
        preview = page.locator("#import-preview ~ .preview-table").first
        expect(preview.locator("tbody tr")).to_have_count(3)
        expect(page.locator("#import-preview ~ .table-wrap pre")).to_have_count(0)
        # Monetary headers: a decision, not a preselected "Ár".
        expect(page.get_by_label("Megfeleltetés: LASTINITIALCOST")).to_have_value("")
        expect(page.get_by_label("Megfeleltetés: LISTPRICE")).to_have_value("")
        expect(page.get_by_text("lehetséges jelentés: Beszerzési ár", exact=False)).to_be_visible()
        expect(page.get_by_text("Tudományos jelölésű azonosítók", exact=False)).to_be_visible()
        expect(page.get_by_text("Negatív értékek:", exact=False)).to_be_visible()
        expect(preview.get_by_text("tudományos jelölés", exact=False).first).to_be_visible()
        # Technical details stay collapsed until asked for.
        expect(page.locator(".tech-json").first).to_be_hidden()
        # Awaiting approval offers the real cancel action.
        expect(page.get_by_role("button", name="Megszakítás")).to_be_visible()
        page.get_by_role("link", name="Jóváhagyás").click()
        expect(page.get_by_role("button", name="Megfeleltetés jóváhagyása és feldolgozás")).to_be_in_viewport()
        assert no_page_overflow(page)
        assert not page.errors
        browser.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_history_delete_long_names_paging_and_no_return(ui, width, height):
    client, _, open_page, seed = ui
    long_name = "nagyon_hosszu_beszallitoi_arlista_" + "x" * 180 + ".csv"
    ids = [seed(f"SKU;NAME\n{i:03d};Termék {i}\n".encode(), "besz_minta.csv") for i in range(25)]
    long_id = seed(b"SKU;NAME\n999;Hosszu\n", long_name)
    processed = ids[0]
    client.post(f"/api/v1/imports/runs/{processed}/approve",
                json={"name": "P", "mapping": {"0": "sku", "1": "name"}, "identity_field": "sku"})
    with sync_playwright() as p:
        browser, page = open_page(p, width, height)
        history = page.locator("table.import-history tbody tr")
        expect(history).to_have_count(25)
        expect(page.get_by_text("1–25")).to_be_visible()
        long_cell = page.locator(".import-history .file-name").first
        expect(long_cell).to_have_attribute("title", long_name)
        box = long_cell.bounding_box()
        assert box["x"] + box["width"] <= width + 1
        assert long_cell.evaluate("e => e.scrollWidth > e.clientWidth")  # ellipsis
        assert no_page_overflow(page)
        page.get_by_role("button", name="További importok").click()
        expect(history).to_have_count(1)
        # The processed import is not offered for deletion.
        expect(page.get_by_role("button", name=f"#{processed} besz_minta.csv törlése")).to_have_count(0)
        page.get_by_role("button", name="Korábbi oldal").click()
        target = ids[3]
        page.get_by_role("button", name=f"#{target} besz_minta.csv törlése").click()
        dialog = page.get_by_role("alertdialog")
        expect(dialog).to_contain_text("Véglegesen törlődik")
        expect(dialog).to_contain_text("Megmarad")
        dialog.get_by_role("button", name="Végleges törlés").click()
        expect(page.get_by_role("status").filter(has_text=f"#{target} import")).to_contain_text("törölve")
        expect(page.get_by_role("button", name=f"#{target} besz_minta.csv megnyitása")).to_have_count(0)
        # The reported regression: after a new upload the deleted import must not return.
        page.get_by_label("CSV/XLSX fájl").set_input_files(
            {"name": "uj.csv", "mimeType": "text/csv", "buffer": b"SKU;NAME\n777;Uj\n"}
        )
        expect(page.get_by_role("heading", name=re.compile(r"Jóváhagyásra vár"))).to_be_visible(timeout=15000)
        expect(page.get_by_role("button", name=re.compile(r"uj\.csv megnyitása"))).to_be_visible()
        expect(page.get_by_role("button", name=f"#{target} besz_minta.csv megnyitása")).to_have_count(0)
        assert target not in [r["id"] for r in client.get("/api/v1/imports/runs").json()]
        assert client.get(f"/api/v1/imports/runs/{long_id}").status_code == 200
        assert not page.errors
        browser.close()


def test_refused_delete_shows_server_reason(ui):
    """The dialog shows the server's dry-run refusal instead of a delete button."""
    from datetime import timedelta

    from app.import_models import ImportRun
    from app.models import now

    client, target, open_page, seed = ui
    id = seed(b"SKU;NAME\n001;TV\n", "fut.csv")
    with Session(target) as db:
        db.get(ImportRun, id).lease_until = now() + timedelta(minutes=5)  # analysis running
        db.commit()
    with sync_playwright() as p:
        browser, page = open_page(p, 1440, 1000)
        page.get_by_role("button", name=f"#{id} fut.csv törlése").click()
        dialog = page.get_by_role("alertdialog")
        expect(dialog).to_contain_text("Nem törölhető")
        expect(dialog).to_contain_text("éppen fut")
        expect(dialog.get_by_role("button", name="Végleges törlés")).to_have_count(0)
        assert client.get(f"/api/v1/imports/runs/{id}").status_code == 200
        assert not page.errors
        browser.close()
