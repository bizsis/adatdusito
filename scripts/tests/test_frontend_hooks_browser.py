"""Synthetic API regression coverage for effect lifetimes and tenant/session state."""

from collections import Counter
from copy import deepcopy
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def workspace_page():
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    state = {
        "tenant": 1, "authenticated": True, "calls": Counter(), "writes": [],
        "hold_session": False, "pending": [], "hold_run": None, "pending_runs": [],
    }
    workspaces = [{"tenant_id": 1, "name": "Első ügyfél"},
                  {"tenant_id": 2, "name": "Második ügyfél"}]
    run = {
        "id": 1, "supplier_id": 1, "filename": "sample.csv",
        "state": "awaiting_approval", "cursor": 0, "error": None,
        "counters": {}, "config": {}, "analysis": {
            "columns": [{"index": 0, "header": "SKU", "field": "sku",
                         "confidence": 1, "method": "exact", "critical": True,
                         "samples": ["001"]}],
            "headers": ["SKU"], "suggested_mapping": {"0": "sku"},
        },
    }
    second_run = {**deepcopy(run), "id": 2, "filename": "second.csv"}
    state["runs"] = [run, second_run]

    def handle(route):
        request = route.request
        url = urlparse(request.url)
        if not url.path.startswith("/api/"):
            file = dist / (url.path.lstrip("/") or "index.html")
            route.fulfill(body=file.read_bytes(),
                          content_type=mimetypes.guess_type(file.name)[0] or "text/plain")
            return
        path = url.path.removeprefix("/api/v1")
        state["calls"][path] += 1
        if request.method != "GET":
            state["writes"].append({"path": path, "headers": request.headers,
                                    "body": request.post_data})
        if path == "/auth/me":
            if not state["authenticated"]:
                route.fulfill(status=401, json={"error": {"message": "Bejelentkezés szükséges."}})
                return
            response = {
                "user": {"id": 1, "name": "Teszt", "active": True, "superadmin": False},
                "tenant_id": state["tenant"], "system": False,
                "workspace": workspaces[state["tenant"] - 1], "workspaces": workspaces,
                "memberships": [], "role": "tenant_admin",
                "permissions": ["imports.read", "imports.create", "imports.approve", "imports.manage"],
                "csrf_token": f"csrf-{state['tenant']}",
            }
            if state["hold_session"]:
                state["pending"].append((route, deepcopy(response)))
                return
        elif path == "/auth/methods":
            response = {"password": True, "google": False, "passkey": False,
                        "registration": False, "branding": {"display_name": "Adatdúsító",
                        "system_name": "Teszt", "timezone": "Europe/Budapest"}}
        elif path == "/auth/tenant":
            state["tenant"] = json.loads(request.post_data)["tenant_id"]
            response = {}
        elif path == "/auth/logout":
            state["authenticated"] = False
            route.fulfill(status=204)
            return
        elif path == "/auth/login":
            route.fulfill(status=401, json={"error": {"message": "Hibás bejelentkezési adatok."}})
            return
        elif path == "/access/workspaces":
            q = parse_qs(url.query).get("q", [""])[0].casefold()
            response = {"items": [w for w in workspaces if q in w["name"].casefold()]}
        elif path == "/system/status":
            response = {"status": "ok", "checks": {}}
        elif path == "/imports/suppliers":
            response = [{"id": 1, "name": "Teszt beszállító"}]
        elif path == "/imports/fields":
            response = [{"key": "sku", "label": "Cikkszám"}, {"key": "name", "label": "Terméknév"}]
        elif path == "/imports/runs" and request.method == "POST":
            route.fulfill(status=413, body="<html>Request Entity Too Large</html>", content_type="text/html")
            return
        elif path == "/imports/runs":
            response = state["runs"]
        elif path in ("/imports/runs/1", "/imports/runs/2"):
            response = state["runs"][int(path.rsplit("/", 1)[1]) - 1]
            if state["hold_run"] == response["id"]:
                state["pending_runs"].append((route, deepcopy(response)))
                return
        elif path.endswith("/rows") or path.endswith("/preview"):
            response = {"items": [], "has_more": False}
        else:
            response = []
        route.fulfill(json=response)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.clock.install()
        page.route("http://hooks.test/**", handle)
        page.goto("http://hooks.test/")
        expect(page.get_by_label("Munkaterület", exact=True)).to_have_value("1")
        yield page, state
        assert not errors
        browser.close()


def test_periodic_refresh_preserves_workspace_search(workspace_page):
    page, state = workspace_page
    search = page.get_by_label("Munkaterület keresése", exact=True)
    search.fill("Második")
    with page.expect_response("**/auth/me"):
        page.clock.run_for(30001)
    expect(search).to_have_value("Második")
    assert state["calls"]["/auth/me"] == 2


def test_workspace_switch_rotates_csrf_and_clears_search(workspace_page):
    page, state = workspace_page
    page.get_by_label("Munkaterület keresése", exact=True).fill("Második")
    page.get_by_label("Munkaterület", exact=True).select_option("2")
    expect(page.get_by_label("Munkaterület", exact=True)).to_have_value("2")
    expect(page.get_by_label("Munkaterület keresése", exact=True)).to_have_value("")
    page.get_by_role("button", name="Kilépés", exact=True).click()
    expect(page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True)).to_be_visible()
    assert [(w["path"], w["headers"]["x-csrf-token"]) for w in state["writes"]] == [
        ("/auth/tenant", "csrf-1"), ("/auth/logout", "csrf-2")]


def test_session_expiry_stops_refresh_and_clears_csrf(workspace_page):
    page, state = workspace_page
    state["authenticated"] = False
    with page.expect_response("**/auth/me"):
        page.clock.run_for(30001)
    expect(page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True)).to_be_visible()
    count = state["calls"]["/auth/me"]
    page.clock.run_for(60001)
    assert state["calls"]["/auth/me"] == count
    page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True).fill("test")
    page.get_by_label("Jelszó", exact=True).fill("test-password")
    page.get_by_role("button", name="Bejelentkezés →", exact=True).click()
    expect(page.get_by_text("Hibás bejelentkezési adatok.", exact=True)).to_be_visible()
    assert state["writes"][-1]["headers"]["x-csrf-token"] == ""


def test_late_session_refresh_cannot_restore_logged_out_user(workspace_page):
    page, state = workspace_page
    state["hold_session"] = True
    with page.expect_request("**/auth/me"):
        page.clock.run_for(30001)
    page.get_by_role("button", name="Kilépés", exact=True).click()
    expect(page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True)).to_be_visible()
    assert len(state["pending"]) == 1
    route, old_session = state["pending"].pop()
    route.fulfill(json=old_session)
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True)).to_be_visible()
    expect(page.get_by_label("Munkaterület", exact=True)).to_have_count(0)


def test_import_polling_preserves_mapping_without_fetch_loops(workspace_page):
    page, state = workspace_page
    page.get_by_role("navigation").get_by_role("button", name="Beszállítói import", exact=True).click()
    page.get_by_role("button", name="#1 sample.csv · Jóváhagyásra vár", exact=True).click()
    mapping = page.get_by_label("Megfeleltetés: SKU", exact=True)
    mapping.select_option("name")
    page.get_by_label("Profil neve", exact=True).fill("Saját szerkesztés")
    for _ in range(3):
        with page.expect_response("**/imports/runs/1"):
            page.clock.run_for(2100)
    expect(mapping).to_have_value("name")
    expect(page.get_by_label("Profil neve", exact=True)).to_have_value("Saját szerkesztés")
    assert state["calls"]["/imports/fields"] == 1
    assert state["calls"]["/imports/runs/1/rows"] == 1
    assert state["calls"]["/imports/runs/1/join-suggestions"] == 1
    assert state["calls"]["/imports/runs/1/preview"] == 2


def test_upload_proxy_413_preserves_supplier_and_csrf(workspace_page):
    page, state = workspace_page
    page.get_by_role("navigation").get_by_role("button", name="Beszállítói import", exact=True).click()
    page.get_by_role("combobox", name="Beszállító", exact=False).select_option("1")
    page.get_by_label("CSV/XLSX fájl", exact=True).set_input_files({
        "name": "sample.csv", "mimeType": "text/csv", "buffer": b"SKU\n001\n"})
    expect(page.get_by_role("alert")).to_contain_text("Túl nagy fájl, legfeljebb 50 MB tölthető fel.")
    expect(page.get_by_role("combobox", name="Beszállító", exact=False)).to_have_value("1")
    expect(page.get_by_label("CSV/XLSX fájl", exact=True)).to_be_enabled()
    upload = next(w for w in state["writes"] if w["path"] == "/imports/runs")
    assert upload["headers"]["x-csrf-token"] == "csrf-1"
    assert upload["headers"]["content-type"].startswith("multipart/form-data; boundary=")


def test_late_import_poll_cannot_restore_previous_selection(workspace_page):
    page, state = workspace_page
    page.get_by_role("navigation").get_by_role("button", name="Beszállítói import", exact=True).click()
    page.get_by_role("button", name="#1 sample.csv · Jóváhagyásra vár", exact=True).click()
    expect(page.get_by_role("heading", name="#1 – Jóváhagyásra vár", exact=True)).to_be_visible()
    state["hold_run"] = 1
    with page.expect_request("**/imports/runs/1"):
        page.clock.run_for(2100)
    page.get_by_role("button", name="#2 second.csv · Jóváhagyásra vár", exact=True).click()
    expect(page.get_by_role("heading", name="#2 – Jóváhagyásra vár", exact=True)).to_be_visible()
    assert len(state["pending_runs"]) == 1
    route, old_run = state["pending_runs"].pop()
    route.fulfill(json=old_run)
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.get_by_role("heading", name="#2 – Jóváhagyásra vár", exact=True)).to_be_visible()
