"""CATEGORY-02B presentation tests, NOT CATEGORY-02A API integration tests.

All /__category02_test__/ paths and response fields belong to the test adapter.
Production has no such routes, adapter or mock success.
"""

from copy import deepcopy
import json
import mimetypes
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def presentation_build(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("category02-presentation")
    subprocess.run(
        ["node", "node_modules/vite/bin/vite.js", "build", "--config", "tests/classification/vite.config.mjs"],
        cwd=root / "frontend", env={**os.environ, "CATEGORY02_TEST_DIST": str(output)},
        check=True, capture_output=True, text=True,
    )
    return output


@pytest.fixture
def presentation_page(presentation_build):
    def choice(key, title, path=None, selectable=True, children=False):
        return {"key": key, "title": title, "path": path or [title],
                "selectable": selectable, "hasChildren": children}

    tv = choice("ui-tv", "Televíziók", ["TV és szórakozás", "Televíziók"])
    monitor = choice("ui-monitor", "Monitorok", ["Számítástechnika", "Monitorok"])
    group = choice("ui-root", "TV és szórakozás", selectable=False, children=True)
    products = [
        {"key": "product-a", "title": "TV Alpha", "identifier": "00001", "source": "Beszállító A",
         "originalCategory": "Forrás / 0008", "ownCategory": "Webshop / Kijelzők",
         "internalCategory": tv, "group": "assigned", "explanation": "Jóváhagyott saját kategóriatérkép.",
         "confidencePercent": 99, "alternatives": [], "origin": "Automatikus kategóriatérkép",
         "protectedEdit": False, "auditText": "Teszt Admin – korábbi import", "donorText": "Ellenőrzött donorprofil",
         "editContext": {"testRevision": 1}},
        {"key": "product-b", "title": "Készülék Beta", "identifier": "00002", "source": "Beszállító B",
         "originalCategory": "Forrás / vegyes", "ownCategory": "Webshop / Készülékek",
         "internalCategory": None, "group": "review", "explanation": "Több belső kategória lehetséges.",
         "confidencePercent": 0, "alternatives": [tv, monitor, choice("ui-projector", "Projektorok"), choice("ui-speaker", "Hangfalak")],
         "origin": "Ellenőrzendő javaslat", "protectedEdit": False, "auditText": "", "donorText": "",
         "editContext": {"testRevision": 1}},
    ]
    products.append({**deepcopy(products[0]), "key": "product-c", "title": "TV Gamma", "identifier": "00003", "protectedEdit": True})
    mapping = {"key": "mapping-a", "title": "Saját TV-profil", "originalCategory": "Webshop / Kijelzők",
               "internalCategory": None, "profileText": "Ügyfél saját paraméterprofilja", "approved": False,
               "protectedEdit": False, "affectedProducts": 20, "auditText": "Teszt Admin – importprofil", "editContext": {"testRevision": 1}}
    state = {"products": products, "mapping": mapping, "requests": [], "previews": {}, "writes": [],
             "conflict": False, "preview_conflicts": 0, "deny": False, "fail_list": False, "hold": False, "pending": [], "threshold": 98}

    def route_request(route):
        url = urlparse(route.request.url)
        if not url.path.startswith("/__category02_test__/"):
            file = presentation_build / (url.path.lstrip("/") or "tests/classification/index.html")
            route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "text/plain")
            return
        _, _, workspace, operation = url.path.split("/")
        body = json.loads(route.request.post_data)
        state["requests"].append((workspace, operation, body))
        if operation == "products":
            if state["fail_list"]:
                route.fulfill(status=503, json={})
                return
            if state["hold"] and workspace == "one":
                state["pending"].append((route, body))
                return
            rows = deepcopy(state["products"])
            if workspace == "two":
                rows = [{**rows[0], "key": "other-product", "title": "Másik ügyfél terméke", "ownCategory": "Másik ügyfél / Saját kategória"}]
            filters = body["filters"]
            if filters["search"]:
                rows = [r for r in rows if filters["search"].casefold() in (r["title"] + r["identifier"]).casefold()]
            if filters["group"] != "all":
                rows = [r for r in rows if r["group"] == filters["group"]]
            if filters["category"]:
                rows = [r for r in rows if (r["internalCategory"] or {}).get("key") == filters["category"]]
            if filters["source"]:
                rows = [r for r in rows if r["source"] == filters["source"]]
            offset = 2 if body["cursor"] == "page-two" else 0
            result = {"items": rows[offset:offset + 2], "next": "page-two" if len(rows) > offset + 2 else None,
                      "total": 125000 if all(filters[k] == v for k, v in {"search": "", "group": "all", "category": "", "source": ""}.items()) else len(rows),
                      "categories": [{"key": tv["key"], "title": "Televíziók"}],
                      "sources": [{"key": "Beszállító A", "title": "Beszállító A"}, {"key": "Beszállító B", "title": "Beszállító B"}]}
        elif operation == "mappings":
            result = {"items": [state["mapping"]] if body["search"].casefold() in state["mapping"]["title"].casefold() else [], "next": None, "total": 1}
        elif operation == "choices":
            options = [tv, monitor] if body["parent"] else [group, tv, monitor]
            options = [c for c in options if body["search"].casefold() in c["title"].casefold()]
            result = {"items": options, "next": None, "total": 412}
        elif operation == "selection":
            result = {"handle": "test-filter-snapshot", "count": 125000}
        elif operation == "preview":
            if state["deny"]:
                route.fulfill(status=403, json={})
                return
            handle = "test-preview-" + str(len(state["previews"]) + 1)
            state["previews"][handle] = deepcopy(body)
            large = body["target"]["kind"] == "bulk" and body["target"]["selection"]["kind"] == "matching"
            result = {"handle": handle, "summary": "A kijelölés több, legfeljebb 50 000 termékes futásra bontandó." if large else "A saját kategóriák és értékek változatlanok.",
                      "affected": 125000 if large else 20 if body["target"]["kind"] == "mapping" and body["target"]["inherit"] else 1,
                      "locked": 3 if body["target"]["kind"] == "mapping" and body["target"]["inherit"] else 0,
                      "conflicts": state["preview_conflicts"], "canApply": not large,
                      "changes": [{"label": "Belső besorolás", "before": "Korábbi besorolás", "after": body["category"]["path"][-1]}]}
        elif operation == "apply":
            if state["conflict"]:
                state["conflict"] = False
                route.fulfill(status=409, json={})
                return
            intent = state["previews"][body["handle"]]
            state["writes"].append(deepcopy(intent))
            target = intent["target"]
            if target["kind"] == "mapping":
                state["mapping"].update(approved=True, protectedEdit=True, internalCategory=intent["category"], auditText="UI Teszt – kézi jóváhagyás")
            else:
                keys = [target["key"]] if target["kind"] == "product" else target["selection"]["keys"]
                for product in state["products"]:
                    if product["key"] in keys:
                        product.update(internalCategory=intent["category"], group="assigned", protectedEdit=True,
                                       origin="Kézzel jóváhagyva", auditText="UI Teszt – kézi jóváhagyás, revízió 2", editContext={"testRevision": 2})
            route.fulfill(status=204)
            return
        elif operation == "threshold-read":
            result = state["threshold"]
        elif operation == "threshold-save":
            state["threshold"] = body["percent"]
            result = state["threshold"]
        else:
            raise AssertionError(operation)
        route.fulfill(json=result)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None, args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://classification.test/**", route_request)
        yield page, state
        assert not errors
        browser.close()


def open_editor(page, name="TV Alpha"):
    page.get_by_role("button", name=f"{name} besorolásának módosítása", exact=True).click()
    page.get_by_role("button", name="Kiválasztás: Monitorok", exact=True).click()
    page.get_by_label("Módosítás indoka", exact=True).fill("Ellenőrzött kézi javítás")
    page.get_by_role("button", name="Módosítások előnézete", exact=True).click()
    expect(page.get_by_role("region", name="Módosítás előnézete", exact=True)).to_be_visible()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_two_statuses_own_category_and_three_alternatives(presentation_page, width, height):
    page, state = presentation_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://classification.test/")
    table = page.locator("table")
    expect(table.get_by_text("Automatikusan besorolt", exact=True)).to_be_visible()
    expect(table.get_by_text("Ellenőrzést igényel", exact=True)).to_be_visible()
    expect(table.get_by_text("Webshop / Kijelzők", exact=True)).to_be_visible()
    expect(page.get_by_text("Szűrt találatok: 125\u00a0000", exact=True)).to_be_visible()
    assert table.locator("tbody tr").count() == 2
    page.get_by_role("button", name="Készülék Beta részletei", exact=True).click()
    expect(page.get_by_text("Megbízhatósági érték: 0%", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Besorolási alternatívák").locator("li")).to_have_count(3)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=f"/tmp/category02b-presentation-{width}.png", full_page=True)
    assert not state["writes"]


def test_server_filters_and_pagination_do_not_fetch_all_products(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    page.get_by_role("button", name="Következő termékek", exact=True).click()
    expect(page.locator("table").get_by_text("TV Gamma", exact=True)).to_be_visible()
    page.get_by_role("button", name="Előző termékek", exact=True).click()
    expect(page.locator("table").get_by_text("TV Alpha", exact=True)).to_be_visible()
    page.get_by_label("Besorolási státusz", exact=True).select_option("review")
    expect(page.locator("tbody tr")).to_have_count(1)
    expect(page.locator("table").get_by_text("Készülék Beta", exact=True)).to_be_visible()
    page.get_by_label("Forrás szerinti szűrés", exact=True).select_option("Beszállító B")
    with page.expect_response(lambda r: r.url.endswith("/products") and r.request.post_data_json["filters"]["search"] == "00002"):
        page.get_by_label("Termék keresése", exact=True).fill("00002")
    last = [r[2] for r in state["requests"] if r[1] == "products"][-1]
    assert last["filters"] == {"search": "00002", "group": "review", "category": "", "source": "Beszállító B"}
    assert last["cursor"] is None
    page.get_by_label("Kategória szerinti szűrés", exact=True).select_option("ui-tv")
    expect(page.get_by_text("Nincs a szűrésnek megfelelő termék.", exact=True)).to_be_visible()
    assert [r[2] for r in state["requests"] if r[1] == "products"][-1]["filters"]["category"] == "ui-tv"


def test_automatic_category_is_editable_save_has_preview_lock_and_audit(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    original = state["products"][0]["ownCategory"]
    open_editor(page)
    assert not state["writes"]
    page.get_by_role("button", name="Módosítás mentése", exact=True).click()
    expect(page.get_by_text("A módosítás mentve.", exact=False)).to_be_visible()
    expect(page.locator("table").get_by_text("Kézi javítás védett", exact=True)).to_be_visible()
    assert state["products"][0]["ownCategory"] == original
    assert state["products"][0]["originalCategory"] == "Forrás / 0008"
    page.get_by_role("button", name="TV Alpha részletei", exact=True).click()
    expect(page.get_by_text("UI Teszt – kézi jóváhagyás, revízió 2", exact=True)).to_be_visible()
    expect(page.get_by_text("Kézzel jóváhagyva", exact=True)).to_be_visible()
    assert state["writes"][0]["target"]["context"] == {"testRevision": 1}


def test_revision_409_never_reports_saved_and_requires_fresh_data(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    open_editor(page)
    state["conflict"] = True
    page.get_by_role("button", name="Módosítás mentése", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("409")
    expect(page.get_by_role("button", name="Módosítás mentése", exact=True)).to_have_count(0)
    expect(page.get_by_text("A módosítás mentve.", exact=False)).to_have_count(0)
    assert not state["writes"]
    page.get_by_role("button", name="Friss adatok betöltése", exact=True).click()
    expect(page.get_by_role("button", name="TV Alpha besorolásának módosítása", exact=True)).to_be_visible()


def test_mapping_approval_inheritance_and_own_category_protection(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    page.get_by_role("tab", name="Saját kategóriatérkép és profilok", exact=True).click()
    page.get_by_role("button", name="Saját TV-profil kategóriatérképének szerkesztése", exact=True).click()
    page.get_by_role("button", name="Kiválasztás: Televíziók", exact=True).click()
    page.get_by_label("Módosítás indoka", exact=True).fill("Saját kategória ellenőrzött megfeleltetése")
    page.get_by_label("Alkalmazás a saját kategória termékeire", exact=True).check()
    page.get_by_role("button", name="Módosítások előnézete", exact=True).click()
    expect(page.get_by_text("A védett kézi javítások megmaradnak; a szerver ezeket kihagyja.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Kategóriatérkép jóváhagyása", exact=True).click()
    expect(page.get_by_text("Jóváhagyott kategóriatérkép", exact=False)).to_be_visible()
    assert state["mapping"]["originalCategory"] == "Webshop / Kijelzők"
    assert state["writes"][0]["target"]["inherit"] is True


@pytest.mark.parametrize("params", ["?readonly=1", "?missing-writes=1"])
def test_no_edit_or_bulk_controls_without_rights_or_real_callbacks(presentation_page, params):
    page, state = presentation_page
    page.goto("http://classification.test/" + params)
    expect(page.locator("tbody tr")).to_have_count(2)
    expect(page.get_by_role("button", name="TV Alpha besorolásának módosítása", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Összes szűrt találat kijelölése", exact=True)).to_have_count(0)
    page.get_by_role("tab", name="Saját kategóriatérkép és profilok", exact=True).click()
    expect(page.get_by_text("Saját TV-profil", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Saját TV-profil kategóriatérképének szerkesztése", exact=True)).to_have_count(0)
    assert not state["writes"]


def test_bulk_snapshot_large_total_is_not_a_tenant_cap(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    page.get_by_role("button", name="Összes szűrt találat kijelölése", exact=True).click()
    expect(page.get_by_text("Kijelölve: 125\u00a0000", exact=True)).to_be_visible()
    page.get_by_role("button", name="Tömeges besorolás előnézete", exact=True).click()
    page.get_by_role("button", name="Kiválasztás: Televíziók", exact=True).click()
    page.get_by_label("Módosítás indoka", exact=True).fill("Csoportos besorolás előnézete")
    page.get_by_role("button", name="Módosítások előnézete", exact=True).click()
    expect(page.get_by_text("A kijelölés több, legfeljebb 50 000 termékes futásra bontandó.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Módosítás mentése", exact=True)).to_be_disabled()
    intent = list(state["previews"].values())[-1]
    assert intent["target"]["selection"] == {"kind": "matching", "handle": "test-filter-snapshot", "count": 125000}
    assert not state["writes"]


def test_threshold_98_comes_from_adapter_without_local_classification(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    threshold = page.get_by_label("Kategória-besorolási admin küszöb (%)", exact=True)
    expect(threshold).to_have_value("98")
    threshold.fill("75")
    page.get_by_role("button", name="Besorolási küszöb mentése", exact=True).click()
    expect(page.get_by_text("A besorolási küszöb mentve.", exact=True)).to_be_visible()
    assert state["threshold"] == 75
    expect(page.locator("table").get_by_text("Ellenőrzést igényel", exact=True)).to_be_visible()


def test_tenant_switch_discards_late_response_and_selection(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/?ignore-abort=1")
    page.get_by_role("button", name="Aktuális oldal kijelölése", exact=True).click()
    expect(page.get_by_text("Kijelölve: 2", exact=True)).to_be_visible()
    state["hold"] = True
    with page.expect_request(lambda r: r.url.endswith("/products") and r.post_data_json["filters"]["search"] == "Alpha"):
        page.get_by_label("Termék keresése", exact=True).fill("Alpha")
    page.get_by_role("button", name="Teszt: munkaterület váltása", exact=True).click()
    expect(page.locator("table").get_by_text("Másik ügyfél terméke", exact=True)).to_be_visible()
    assert len(state["pending"]) == 1
    route, _ = state["pending"].pop()
    route.fulfill(json={"items": state["products"], "next": None, "total": 3, "categories": [], "sources": []})
    expect(page.locator("table").get_by_text("TV Alpha", exact=True)).to_have_count(0)
    expect(page.get_by_text("Kijelölve: 2", exact=True)).to_have_count(0)


def test_navigation_groups_and_403_do_not_create_a_save(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    page.get_by_role("button", name="TV Alpha besorolásának módosítása", exact=True).click()
    expect(page.get_by_text("Navigációs csoport", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Kiválasztás: TV és szórakozás", exact=True)).to_have_count(0)
    page.get_by_role("button", name="TV és szórakozás alkategóriái", exact=True).click()
    page.get_by_role("button", name="Kiválasztás: Televíziók", exact=True).click()
    page.get_by_label("Módosítás indoka", exact=True).fill("Jogvesztés teszt")
    state["deny"] = True
    page.get_by_role("button", name="Módosítások előnézete", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Nincs jogosultság")
    expect(page.get_by_role("button", name="Módosítás mentése", exact=True)).to_have_count(0)
    assert not state["writes"]


def test_production_bundle_contains_no_test_adapter_or_fake_endpoints():
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    scripts = list(dist.glob("assets/*.js"))
    assert scripts, "Build production frontend first"
    assert not (dist / "tests/classification/index.html").exists()
    assert all("/__category02_test__/" not in script.read_text() for script in scripts)


def test_preview_conflicts_block_apply_even_with_callback(presentation_page):
    page, state = presentation_page
    state["preview_conflicts"] = 2
    page.goto("http://classification.test/")
    open_editor(page)
    expect(page.get_by_role("alert")).to_contain_text("Az ütközéseket előbb rendezni kell")
    expect(page.get_by_role("button", name="Módosítás mentése", exact=True)).to_be_disabled()
    assert not state["writes"]


def test_alternative_can_be_selected_without_saving_automatically(presentation_page):
    page, state = presentation_page
    page.goto("http://classification.test/")
    page.get_by_role("button", name="Készülék Beta részletei", exact=True).click()
    page.get_by_role("button", name="Javaslat kiválasztása: Televíziók", exact=True).click()
    expect(page.get_by_text("Kiválasztott belső kategória: TV és szórakozás / Televíziók", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Módosítások előnézete", exact=True)).to_be_disabled()
    assert not state["writes"]
    assert not state["previews"]


def test_failed_read_is_not_rendered_as_an_empty_success(presentation_page):
    page, state = presentation_page
    state["fail_list"] = True
    page.goto("http://classification.test/")
    expect(page.get_by_role("alert")).to_contain_text("A tesztválasz hibás")
    expect(page.get_by_text("Nincs a szűrésnek megfelelő termék.", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Módosítás mentése", exact=True)).to_have_count(0)
