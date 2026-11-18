"""The #58 presentation flow uses a standalone, test-only mock adapter."""

import mimetypes
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture(scope="module")
def mapping_browser(tmp_path_factory):
    output = tmp_path_factory.mktemp("mapping-wizard")
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """import { build } from 'vite';
            await build({build: {outDir: process.argv[1],
                rollupOptions: {input: 'tests/issue58.html'}}});""",
            str(output),
        ],
        cwd=FRONTEND,
        check=True,
    )
    with sync_playwright() as p:
        chromium = Path("/usr/bin/chromium")
        browser = p.chromium.launch(
            executable_path=str(chromium) if chromium.exists() else None,
            args=["--no-sandbox"],
        )
        yield browser, output
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_all_columns_explicit_approval_and_missing_parameter_selection(
    mapping_browser, width
):
    browser, output = mapping_browser
    with browser.new_context(viewport={"width": width, "height": 900}) as context:
        page = context.new_page()
        errors, api_requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            """window.reviews = []; window.selections = [];
            addEventListener('mapping-approved', e => reviews.push(e.detail));
            addEventListener('mapping-parameters', e => selections.push(e.detail));"""
        )

        def serve(route):
            path = urlparse(route.request.url).path
            if path.startswith("/api/"):
                api_requests.append(path)
                return route.abort()
            file = (output / path.lstrip("/")).resolve()
            assert file.is_relative_to(output)
            route.fulfill(
                body=file.read_bytes(),
                content_type=mimetypes.guess_type(file)[0] or "application/octet-stream",
            )

        page.route("http://mapping.test/**", serve)
        page.goto("http://mapping.test/tests/issue58.html")
        expect(page.get_by_text("3 termék", exact=False)).to_be_visible()
        expect(page.get_by_label("Webshopmotor")).to_have_value("unas")
        columns = page.get_by_role("list", name="Forrásoszlopok").locator(":scope > li")
        expect(columns).to_have_count(8)
        expect(columns.nth(0)).to_contain_text("0001")
        expect(columns.nth(2)).to_contain_text("Saját / Kijelzők")
        expect(columns.nth(5)).to_contain_text("0052011370618")
        expect(columns.nth(5)).to_contain_text("8,71999E+12")
        expect(columns.nth(5)).to_contain_text("ellenőrizd a teljes azonosítót")
        expect(columns.nth(7)).to_contain_text("Unknown_01")
        expect(columns.nth(7)).to_contain_text("Megőrzött adat")
        expect(page.get_by_text("Státusz: alapértelmezett érték: 1")).to_be_visible()

        approve = page.get_by_role("button", name="Megfeleltetés jóváhagyása")
        expect(page.get_by_text("Hiányzó kötelező mezők: Bruttó Ár.")).to_be_visible()
        expect(approve).to_be_disabled()
        columns.nth(4).get_by_role("button", name="Javaslat átvétele").click()
        expect(approve).to_be_enabled()
        expect(columns.nth(6)).to_contain_text("Paraméter: Szín")
        expect(columns.nth(6).get_by_role("textbox", name="Paraméternév")).to_have_count(0)
        columns.nth(6).get_by_role("button", name="Javaslat átvétele").click()
        expect(columns.nth(6).get_by_role("textbox", name="Paraméternév")).to_have_value("Szín")
        unknown = columns.nth(7).get_by_role("combobox")
        unknown.select_option("field:sku")
        expect(page.get_by_role("alert")).to_contain_text("csak egyszer szerepelhet")
        expect(approve).to_be_disabled()
        unknown.select_option("newParameter")
        expect(approve).to_be_disabled()
        columns.nth(7).get_by_role("textbox", name="Paraméternév").fill("Forrásjegyzet")
        expect(approve).to_be_enabled()
        unknown.select_option("keep")
        assert page.evaluate("reviews.length") == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        approve.click()
        expect(page.get_by_role("heading", name="Hiányzó eMAG-paraméterek")).to_be_focused()
        expect(page.get_by_text("eMAG-donor: Televíziók")).to_be_visible()
        expect(page.get_by_text("A beszállítói kategória", exact=False)).to_be_visible()
        review = page.evaluate("reviews[0]")
        assert len(review["columns"]) == 8
        assert review["columns"][2]["choice"] == {"kind": "field", "key": "category"}
        assert review["columns"][6]["choice"] == {"kind": "newParameter", "name": "Szín"}
        assert review["columns"][7]["choice"] == {"kind": "keep"}

        page.get_by_role("button", name="Vissza a megfeleltetéshez").click()
        expect(columns.nth(6).get_by_role("textbox", name="Paraméternév")).to_have_value("Szín")
        approve.click()
        expect(page.get_by_role("checkbox")).to_have_count(3)
        expect(page.get_by_role("status")).to_have_text("0 / 3 kijelölve")
        page.get_by_role("button", name="Összes kijelölése").click()
        expect(page.get_by_role("status")).to_have_text("3 / 3 kijelölve")
        expect(page.locator('input[type="checkbox"]:checked')).to_have_count(3)
        page.get_by_role("button", name="Kijelölés törlése").click()
        expect(page.get_by_role("status")).to_have_text("0 / 3 kijelölve")
        page.get_by_role("checkbox", name="Felbontás").check()
        expect(page.get_by_role("status")).to_have_text("1 / 3 kijelölve")
        assert page.evaluate("selections.length") == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        page.get_by_role("button", name="Kijelölés mentése").click()
        expect(page.get_by_role("heading", name="Az előkészítés kész")).to_be_visible()
        assert page.evaluate("selections") == [["tv:resolution"]]
        assert not api_requests
        assert not errors
