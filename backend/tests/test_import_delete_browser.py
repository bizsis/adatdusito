"""Connect the import deletion UI to the real API and an isolated database."""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from app import import_api
from app.import_models import ImportRun
from conftest import login
from test_import_delete import BASE, two_versions
from test_template_prep import full_body, prepared, save

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
SITE = "http://import-delete.test"


def test_delete_previews_confirmation_and_refresh_with_real_api(environment, monkeypatch):
    client, engine, _, reference_queries = environment
    monkeypatch.setattr(import_api, "enqueue", lambda _run_id: None)
    login(client, "admin@example.hu")

    def supplier(name):
        response = client.post(f"{BASE}/suppliers", json={"name": name})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    selected = supplier("Törlési próba")
    other = supplier("Másik beszállító")
    first_run, matched_run, first, latest = two_versions(client, engine, selected)
    other_run, other_view = prepared(client, engine, other)
    save(client, other_run, full_body(other_view), name="Megőrzött sablon").raise_for_status()
    other_templates = f"{BASE}/suppliers/{other}/import-templates"
    snapshot = {
        path: client.get(path).content
        for path in (f"{BASE}/runs/{other_run}", f"{BASE}/runs/{other_run}/file", other_templates)
    }
    matched_file = client.get(f"{BASE}/runs/{matched_run}/file").content
    with Session(engine) as db:
        assert db.get(ImportRun, matched_run).profile_id == first["id"]
    reference_query_count = len(reference_queries)
    mutations = []

    def forward(route):
        request = route.request
        url = urlparse(request.url)
        if not url.path.startswith("/api/"):
            file = (DIST / (url.path.lstrip("/") or "index.html")).resolve()
            assert file.is_relative_to(DIST.resolve())
            route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0])
            return
        headers = {}
        if request.method == "DELETE":
            assert request.headers.get("x-csrf-token") == client.headers["X-CSRF-Token"]
            headers["X-CSRF-Token"] = request.headers["x-csrf-token"]
        response = client.request(
            request.method, url.path + (f"?{url.query}" if url.query else ""), headers=headers,
        )
        if url.path.endswith("/deletion") or request.method == "DELETE":
            mutations.append((request.method, url.path, response.status_code))
        route.fulfill(
            status=response.status_code, body=response.content,
            content_type=response.headers.get("content-type", "application/json"),
        )

    def open_import(browser, supplier_id):
        page = browser.new_page(viewport={"width": 390, "height": 900})
        page.route(f"{SITE}/**", forward)
        page.goto(SITE)
        page.get_by_role("navigation").get_by_role("button", name="Import", exact=True).click()
        page.get_by_label("Webshopmotor").select_option("unas")
        page.get_by_label("Beszállító", exact=True).select_option(str(supplier_id))
        page.get_by_text("Korábban feltöltött fájlok", exact=True).click()
        page.get_by_text("Mentett sablonok és verziók", exact=True).click()
        return page

    with sync_playwright() as p:
        chromium = Path("/usr/bin/chromium")
        with p.chromium.launch(
            executable_path=str(chromium) if chromium.exists() else None,
            args=["--no-sandbox"],
        ) as browser:
            login(client, "reviewer@example.hu")
            page = open_import(browser, selected)
            expect(page.get_by_text("Beszállítók kezelése", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Feltöltött fájl törlése:")).to_have_count(0)
            expect(page.get_by_role("button", name="Mentett sablon törlése:")).to_have_count(0)
            page.get_by_role("button", name="Verziók", exact=True).click()
            expect(page.get_by_role("list", name="Alap verziói")).to_be_visible()
            expect(page.get_by_role("button", name="Sablonverzió törlése:")).to_have_count(0)
            page.close()
            assert not mutations

            login(client, "admin@example.hu")
            page = open_import(browser, selected)
            dialog = page.get_by_role("dialog")
            confirm = dialog.get_by_role("button", name="Törlés", exact=True)

            def blocked(button, reason):
                button.click()
                expect(dialog.get_by_role("alert")).to_contain_text(reason)
                expect(confirm).to_be_disabled()
                dialog.get_by_role("button", name="Mégse").click()

            page.get_by_text("Beszállítók kezelése", exact=True).click()
            delete_supplier = page.get_by_role("button", name="Beszállító törlése: Törlési próba")
            blocked(delete_supplier, "kapcsolódó adatok")
            history = page.locator(".prep-history")
            source = history.get_by_role("listitem").filter(has_text=f"#{first_run} ·")
            delete_file = source.get_by_role("button", name="Feltöltött fájl törlése:")
            blocked(delete_file, "mentett sablon forrása")
            page.get_by_role("button", name="Verziók", exact=True).click()
            blocked(page.get_by_role("button", name="Sablonverzió törlése: Alap · v2"), "legújabb")

            version = page.get_by_role("button", name="Sablonverzió törlése: Alap · v1")
            version.click()
            expect(dialog).to_contain_text("1 jóvá nem hagyott feltöltés sablonkapcsolata megszűnik")
            assert all(method == "GET" for method, _, _ in mutations)
            confirm.click()
            expect(version).to_have_count(0)
            expect(page.get_by_role("button", name="Alap · v2 betöltése")).to_be_visible()
            with Session(engine) as db:
                detached = db.get(ImportRun, matched_run)
                assert detached.profile_id is None
                assert detached.analysis["matched_profile_id"] is None
            assert client.get(f"{BASE}/runs/{matched_run}/file").content == matched_file

            delete_template = page.get_by_role("button", name="Mentett sablon törlése: Alap")
            delete_template.click()
            expect(dialog).to_contain_text("a sablon összes verziója törlődik (1)")
            confirm.click()
            expect(delete_template).to_have_count(0)
            for run in (first_run, matched_run):
                entry = history.get_by_role("listitem").filter(has_text=f"#{run} ·")
                entry.get_by_role("button", name="Feltöltött fájl törlése:").click()
                confirm.click()
                expect(entry).to_have_count(0)

            delete_supplier.click()
            confirm.click()
            select = page.get_by_label("Beszállító", exact=True)
            expect(select).to_have_value("")
            expect(select.get_by_role("option", name="Törlési próba")).to_have_count(0)
            select.select_option(str(other))
            page.get_by_text("Mentett sablonok és verziók", exact=True).click()
            expect(page.get_by_text("Megőrzött sablon · v1")).to_be_visible()

    template_url = f"{BASE}/import-templates/{latest['id']}"
    assert [(path, status) for method, path, status in mutations if method == "DELETE"] == [
        (f"{template_url}/versions/{first['id']}", 200),
        (template_url, 200),
        (f"{BASE}/runs/{first_run}", 200),
        (f"{BASE}/runs/{matched_run}", 200),
        (f"{BASE}/suppliers/{selected}", 200),
    ]
    assert {path: client.get(path).content for path in snapshot} == snapshot
    assert len(reference_queries) == reference_query_count
