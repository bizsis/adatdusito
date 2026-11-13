"""Production UI against the real FastAPI test app and synthetic read-only DB."""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import sync_playwright, expect
from conftest import login
from test_unified_categories import (
    extra_reference_categories as tv_categories,
    extra_reference_parameters as tv_parameters,
    extra_reference_values as tv_values,
)
from test_fixed_category_catalog import (
    extra_reference_categories as desktop_categories,
    extra_reference_parameters as desktop_parameters,
    extra_reference_values as desktop_values,
)


@pytest.fixture
def extra_reference_categories():
    return tv_categories.__wrapped__() + desktop_categories.__wrapped__()


@pytest.fixture
def extra_reference_parameters():
    return tv_parameters.__wrapped__() + desktop_parameters.__wrapped__()


@pytest.fixture
def extra_reference_values():
    return tv_values.__wrapped__() + desktop_values.__wrapped__()


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_unified_category_ui_parameters_values_and_simple_review(
    environment, width, height, owned, monkeypatch
):
    client, target, source, _ = environment
    if owned:
        from app.catalog_import import (
            SourceReader,
            import_catalog,
            rebuild_catalog,
            activate,
        )
        from app import reference, web_navigation, reference_sources
        from contextlib import contextmanager

        version = import_catalog(target, SourceReader(source), pause_ms=0)
        version = rebuild_catalog(target, version)
        activate(target, version)

        @contextmanager
        def forbidden():
            raise AssertionError("Owned UI contacted source database")
            yield

        for module in (reference, web_navigation, reference_sources):
            monkeypatch.setattr(module, "reference_database", forbidden)
    login(client)
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    assert (dist / "index.html").exists(), "Build frontend before browser tests"
    requests = []

    def handle(route):
        u = urlparse(route.request.url)
        if u.path.startswith("/api/"):
            requests.append((route.request.method, u.path, u.query))
            response = client.request(
                route.request.method,
                u.path + ("?" + u.query if u.query else ""),
                content=route.request.post_data or None,
                headers={"Content-Type": "application/json"},
            )
            route.fulfill(
                status=response.status_code,
                body=response.content,
                content_type="application/json",
            )
        else:
            file = (dist / (u.path.lstrip("/") or "index.html")).resolve()
            assert file.is_relative_to(dist.resolve())
            route.fulfill(
                body=file.read_bytes(),
                content_type=mimetypes.guess_type(file.name)[0] or "text/plain",
            )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://unified.test/**", handle)
        page.goto("http://unified.test/")
        page.get_by_role("navigation").get_by_role("button", name="Kategóriák").click()
        expect(page.locator(".tree > ul > li")).to_have_count(13)
        assert not any("parent_id=" in query for _, _, query in requests)
        missing = client.get("/api/v1/reference/navigation?scope=unavailable").json()
        page.get_by_role(
            "button",
            name="Paraméterforrás még nem érhető el – lista megnyitása",
            exact=True,
        ).click()
        expect(page.get_by_label("Nézet", exact=True)).to_have_value("unavailable")
        expect(page.locator(".tree > ul > li")).to_have_count(min(50, missing["total"]))
        expect(page.locator(".tree-path").first).to_be_visible()
        page.locator("button.tree-name").filter(
            has_text=missing["items"][0]["name"]
        ).first.click()
        expect(
            page.get_by_role("heading", name=missing["items"][0]["name"], exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "Paraméter-hozzárendelés szerkesztése (adminisztrátor)", exact=True
            )
        ).to_be_visible()
        assert page.get_by_label("Szülőkategória keresése", exact=True).count() == 0
        page.get_by_label("Nézet", exact=True).select_option("tree")
        expect(page.locator(".tree > ul > li")).to_have_count(13)
        page.get_by_role(
            "button", name="Számítástechnika alkategóriái", exact=True
        ).click()
        page.locator("button.tree-name").filter(
            has_text="Asztali PC és monitorok"
        ).click()
        expect(
            page.get_by_role("heading", name="Asztali PC és monitorok", exact=True)
        ).to_be_visible()
        assert (
            page.get_by_text(
                "Paraméter-hozzárendelés szerkesztése (adminisztrátor)", exact=True
            ).count()
            == 0
        )
        assert page.get_by_text("Összerendelésre vár", exact=True).count() == 0
        page.get_by_role(
            "button", name="Asztali PC és monitorok alkategóriái", exact=True
        ).click()
        page.locator("button.tree-name").filter(has_text="Asztali számítógépek").click()
        expect(page.get_by_text("70 paraméter", exact=True)).to_be_visible()
        expect(
            page.get_by_text("Termékbesorolásra választható", exact=True)
        ).to_be_visible()
        expect(page.locator(".category-full-path")).to_contain_text(
            "Számítástechnika / Asztali PC és monitorok / Asztali számítógépek"
        )
        if owned:
            # The declared filter-derived node is lazy, structural and retained.
            assert (
                page.locator("button.tree-name")
                .filter(has_text="Elöltöltős mosógépek")
                .count()
                == 0
            )
            page.get_by_role(
                "button", name="Háztartási gépek és klíma alkategóriái", exact=True
            ).click()
            page.get_by_role(
                "button", name="Mosógépek és szárítógépek alkategóriái", exact=True
            ).click()
            page.locator("button.tree-name").filter(
                has_text="Elöltöltős mosógépek"
            ).click()
            expect(page.locator(".category-full-path")).to_contain_text(
                "Háztartási gépek és klíma / Mosógépek és szárítógépek / Elöltöltős mosógépek"
            )
            expect(
                page.get_by_text(
                    "Strukturális / termékbesorolásra nem választható", exact=True
                )
            ).to_be_visible()
        page.get_by_role(
            "button", name="TV és szórakozás alkategóriái", exact=True
        ).click()
        page.locator("button.tree-name").filter(has_text="Televíziók").first.click()
        expect(
            page.get_by_role("heading", name="Kategóriaparaméterek", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("46 paraméter", exact=True)).to_be_visible()
        expect(page.get_by_text("Kötelező: 15", exact=True)).to_be_visible()
        expect(page.get_by_text("Opcionális: 31", exact=True)).to_be_visible()
        assert page.get_by_text("Bizonyíték SHA-256 hash-e", exact=True).count() == 0
        if owned:
            page.get_by_text(
                "Paraméter-hozzárendelés szerkesztése (adminisztrátor)", exact=True
            ).click()
            selection = page.get_by_label("Paraméterforrás kiválasztása", exact=True)
            assert int(selection.input_value()) >= 1_000_000_000
            page.get_by_role(
                "button", name="Paraméterforrás mentése", exact=True
            ).click()
            expect(page.get_by_text("46 paraméter", exact=True)).to_be_visible()
        page.get_by_role("button", name="Megnyitás →", exact=True).first.click()
        expect(page.locator(".value-list li")).to_have_count(50)
        page.get_by_label("Keresés az értékekben", exact=True).fill("123")
        expect(page.locator(".value-list li")).to_have_count(1)
        expect(page.locator(".value-list")).to_contain_text("TV érték 123")
        page.get_by_label("Paraméter neve vagy eMAG-azonosítója", exact=True).fill(
            "5001"
        )
        expect(page.get_by_text("1 paraméter", exact=True)).to_be_visible()
        # Source-only categories do not expand the approved taxonomy.
        page.get_by_label("Kategóriakeresés", exact=True).fill("Menüben nem szereplő")
        expect(
            page.locator("button.tree-name").filter(has_text="Menüben nem szereplő")
        ).to_have_count(0)
        assert page.get_by_label("Elhelyezés a közös fában", exact=True).count() == 0
        assert page.get_by_label("Szülőkategória keresése", exact=True).count() == 0
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert not errors
        browser.close()
