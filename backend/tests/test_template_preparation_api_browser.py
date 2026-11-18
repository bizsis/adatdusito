import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
PREFIX = "/api/v1/imports"


@pytest.mark.parametrize("width", [390, 1440])
def test_save_and_reuse_with_real_template_api(environment, monkeypatch, width):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app import import_api
    from app.import_engine import advance
    from app.import_models import SupplierProduct
    from conftest import login

    client, engine, _, _ = environment
    login(client, "admin@example.hu")
    csrf = client.headers["X-CSRF-Token"]
    supplier = client.post(PREFIX + "/suppliers", json={"name": "Sablon teszt"}).json()

    def analyse(run_id):
        with Session(engine) as db:
            advance(db, run_id)

    monkeypatch.setattr(import_api, "enqueue", analyse)
    data = (
        "SKU;NAME;CATEGORY;Color;EAN;Image1;Image2;Unknown_01\n"
        "0001;Első;Eredeti|Alkategória;Fekete;5201137061819;https://example.invalid/a.jpg;https://example.invalid/b.jpg;ABC\n"
        "0002;Második;Eredeti|Alkategória;Fehér;8,71999E+12;;;DEF\n"
        "0003;Harmadik;Eredeti|Alkategória;Fehér;5904517345546;;;GHI\n"
    )
    # Seed a matching legacy automatic profile using the public import API.
    seed = client.post(
        PREFIX + "/runs", data={"supplier_id": supplier["id"]},
        files={"file": ("legacy.csv", data.replace("0001;", "OLD1;").encode())},
    )
    assert seed.status_code == 200, seed.text
    seed_id = seed.json()["id"]
    assert client.post(f"{PREFIX}/runs/{seed_id}/approve", json={
        "name": "Régi automatikus profil", "mapping": {"0": "sku", "1": "name"},
        "identity_field": "sku", "automatic": True,
    }).status_code == 200
    assert client.get(f"{PREFIX}/runs/{seed_id}").json()["state"] == "completed"
    with Session(engine) as db:
        seeded_products = db.execute(
            select(SupplierProduct).order_by(SupplierProduct.id)
        ).scalars().all()
        snapshot = [
            (product.id, product.revision, product.last_run_id, product.data)
            for product in seeded_products
        ]
        assert len(snapshot) == 3
    requests = []

    def forward(route):
        request = route.request
        url = urlparse(request.url)
        if not url.path.startswith("/api/"):
            file = (DIST / (url.path.lstrip("/") or "index.html")).resolve()
            assert file.is_relative_to(DIST.resolve())
            route.fulfill(
                body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0]
            )
            return
        requests.append((request.method, url.path))
        headers = {
            "Content-Type": request.headers.get("content-type", "application/json")
        }
        if request.method != "GET":
            assert request.headers.get("x-csrf-token") == csrf
            headers["X-CSRF-Token"] = csrf
        response = client.request(
            request.method,
            url.path + (f"?{url.query}" if url.query else ""),
            content=request.post_data_buffer,
            headers=headers,
        )
        route.fulfill(
            status=response.status_code,
            body=response.content,
            content_type=response.headers.get("content-type", "application/json"),
        )

    with sync_playwright() as p:
        chromium = Path("/usr/bin/chromium")
        with p.chromium.launch(
            executable_path=str(chromium) if chromium.exists() else None,
            args=["--no-sandbox"],
        ) as browser:
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://template-api.test/**", forward)
            page.goto("http://template-api.test/")
            page.get_by_role("navigation").get_by_role(
                "button", name="Import", exact=True
            ).click()
            page.get_by_label("Webshopmotor").select_option("unas")
            page.get_by_label("Beszállító", exact=True).select_option(
                str(supplier["id"])
            )
            upload = page.get_by_label("CSV, XLS, XLSX vagy XML fájl")
            upload.set_input_files(
                {"name": "forras.csv", "mimeType": "text/csv", "buffer": data.encode()}
            )
            expect(page.get_by_text("3 termék · 8 oszlop")).to_be_visible(timeout=15000)
            expect(
                page.get_by_role("list", name="Cikkszám hozzárendelései")
            ).to_contain_text("SKU")
            rows = page.get_by_role("list", name="Forrásoszlopok").locator(
                ":scope > li"
            )
            expect(rows).to_have_count(8)
            page.get_by_role("button", name="1. SKU hozzárendelés törlése").click()
            source_select = rows.nth(0).get_by_role("combobox")
            expect(source_select).to_have_value("")
            if width == 1440:
                rows.nth(0).locator(".prep-source-handle").drag_to(
                    page.locator('[data-target="cikkszam"]')
                )
            else:
                source_select.select_option(label="Cikkszám")
            expect(page.get_by_role("list", name="Cikkszám hozzárendelései")).to_contain_text("SKU")
            expect(rows.nth(4).locator("samp")).to_have_text("5201137061819")
            expect(rows.nth(4)).to_contain_text("Tudományos jelölésű")
            rows.nth(3).get_by_role(
                "button", name="Javaslat átvétele: Paraméter: Szín", exact=False
            ).click()
            page.get_by_role("dialog").get_by_role(
                "button", name="Paraméter elfogadása"
            ).click()
            rows.nth(5).get_by_role("combobox").select_option(label="Kép")
            rows.nth(6).get_by_role("combobox").select_option(label="Kép")
            page.get_by_role("button", name="7. Image2 előrébb").click()
            page.get_by_label("ÁFA alapértéke").select_option("5")
            page.get_by_label("Sablon neve").fill("Valódi próbasablon")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(
                page.get_by_text("Sablon mentve: Valódi próbasablon · v1")
            ).to_be_visible()
            expect(
                page.get_by_text("Hiányzik az eladási ár.", exact=False)
            ).to_be_visible()
            templates = client.get(
                f"{PREFIX}/suppliers/{supplier['id']}/import-templates"
            ).json()["templates"]
            assert len(templates) == 1
            first_id = templates[0]["id"]
            template = client.get(f"{PREFIX}/import-templates/{first_id}").json()
            assert template["defaults"] == {"statusz": "1", "afa": "5"}
            assert template["columns"][2]["sample"] == "Eredeti|Alkategória"
            assert template["columns"][5]["target"]["order"] == 2
            assert template["columns"][6]["target"]["order"] == 1
            assert [param["name"] for param in template["parameters"]] == ["Szín"]
            run = client.get(f"{PREFIX}/runs/{template['source']['run_id']}").json()
            assert run["analysis_only"] is True
            assert run["state"] == "awaiting_approval"

            upload.set_input_files(
                {
                    "name": "forras2.csv",
                    "mimeType": "text/csv",
                    "buffer": data.replace("Unknown_01", "Unknown_02").encode(),
                }
            )
            expect(
                page.get_by_text("Felismert vagy betöltött sablon:", exact=False)
            ).to_contain_text("Valódi próbasablon · v1")
            expect(page.get_by_text("Új oszlopok: Unknown_02")).to_be_visible()
            expect(page.get_by_label("ÁFA alapértéke")).to_have_value("5")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(
                page.get_by_text("Sablon mentve: Valódi próbasablon · v2")
            ).to_be_visible()
            versions = client.get(
                f"{PREFIX}/import-templates/{first_id}/versions"
            ).json()
            assert {version["version"] for version in versions} == {1, 2}
            page.get_by_text("Mentett sablonok és verziók", exact=True).click()
            page.get_by_role("button", name="Verziók", exact=True).click()
            version_list = page.get_by_role("list", name="Valódi próbasablon verziói")
            expect(version_list.get_by_role("button")).to_have_count(2)
            version_list.get_by_role("button", name="Valódi próbasablon · v1 betöltése").click()
            expect(page.get_by_text("Felismert vagy betöltött sablon:", exact=False)).to_contain_text(
                "Valódi próbasablon · v1"
            )
            with Session(engine) as db:
                products = db.scalars(select(SupplierProduct).order_by(SupplierProduct.id))
                assert [(p.id, p.revision, p.last_run_id, p.data) for p in products] == snapshot
            assert not any(
                "approve" in path or "donor-" in path or "enrich" in path
                for _, path in requests
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
