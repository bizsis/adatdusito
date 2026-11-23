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
    saved_payloads = []

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
        if request.method == "POST" and url.path == PREFIX + "/import-templates":
            saved_payloads.append(request.post_data_json)
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
            def row(label):
                return rows.filter(has=page.get_by_label(f"Célmező: {label}", exact=True))

            expect(row("1. SKU")).to_have_count(0)
            page.get_by_role("button", name="1. SKU hozzárendelés törlése").click()
            source_select = row("1. SKU").get_by_role("combobox")
            expect(source_select).to_have_value("")
            if width == 1440:
                row("1. SKU").locator(".prep-source-handle").drag_to(
                    page.locator('[data-target="cikkszam"]')
                )
            else:
                source_select.select_option(label="Cikkszám")
            expect(page.get_by_role("list", name="Cikkszám hozzárendelései")).to_contain_text("SKU")
            ean = page.get_by_role("list", name="EAN hozzárendelései")
            expect(ean.locator("samp")).to_have_text("5201137061819")
            expect(ean).to_contain_text("Tudományos jelölésű")
            row("4. Color").get_by_role(
                "button", name="Javaslat átvétele: Paraméter: Szín", exact=False
            ).click()
            parameter_dialog = page.get_by_role("dialog")
            expect(parameter_dialog.locator("input, select")).to_have_count(1)
            parameter_dialog.get_by_label("Paraméter neve").fill("Paraméter: Szín")
            parameter_dialog.get_by_role("button", name="Paraméter elfogadása").click()
            for label in ("6. Image1", "7. Image2"):
                remove = page.get_by_role("button", name=f"{label} hozzárendelés törlése")
                if remove.count():
                    remove.click()
                row(label).get_by_role("combobox").select_option(label="Kép")
            page.get_by_role("button", name="7. Image2 előrébb").click()
            page.get_by_label("ÁFA alapértéke").select_option("5")
            expect(upload).to_be_hidden()
            page.get_by_role("button", name="Vissza az előkészítéshez").click()
            expect(upload).to_be_visible()
            page.get_by_role("button", name="Tovább az összerendeléshez").click()
            expect(page.get_by_label("ÁFA alapértéke")).to_have_value("5")
            page.get_by_role("button", name="Tovább mentés nélkül").click()
            expect(page.get_by_text("Előnézet sablonmentés nélkül")).to_be_visible()
            expect(page.get_by_role("table")).to_be_visible()
            assert not saved_payloads
            page.get_by_role("button", name="Vissza a megfeleltetéshez").click()
            page.get_by_label("Sablon neve").fill("Valódi próbasablon")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(
                page.get_by_text("Sablon mentve: Valódi próbasablon · v1")
            ).to_be_visible()
            expect(upload).to_be_hidden()
            page.get_by_role("button", name="Vissza a megfeleltetéshez").click()
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

            page.get_by_role("button", name="Vissza az előkészítéshez").click()
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
            page.get_by_role("button", name="Vissza a megfeleltetéshez").click()
            versions = client.get(
                f"{PREFIX}/import-templates/{first_id}/versions"
            ).json()
            assert {version["version"] for version in versions} == {1, 2}
            page.get_by_role("button", name="Vissza az előkészítéshez").click()
            page.get_by_text("Mentett sablonok és verziók", exact=True).click()
            page.get_by_role("button", name="Verziók", exact=True).click()
            version_list = page.get_by_role("list", name="Valódi próbasablon verziói")
            expect(version_list.get_by_role("button", name="betöltése")).to_have_count(2)
            version_list.get_by_role("button", name="Valódi próbasablon · v1 betöltése").click()
            expect(page.get_by_text("Felismert vagy betöltött sablon:", exact=False)).to_contain_text(
                "Valódi próbasablon · v1"
            )
            # A different file layout with no recognized parameter name or matching template.
            page.get_by_role("button", name="Vissza az előkészítéshez").click()
            upload.set_input_files({
                "name": "masik-szerkezet.csv",
                "mimeType": "text/csv",
                "buffer": b"SKU;Finish;Custom\n0009;Matt;Minta\n",
            })
            expect(rows).to_have_count(2)
            expect(page.get_by_text("Felismert vagy betöltött sablon:", exact=False)).to_have_count(0)
            finish = row("2. Finish").get_by_role("combobox")
            expect(finish).to_have_value("")
            approved = finish.locator('optgroup[label="Meglévő paraméterek"] option')
            expect(approved).to_have_text(["Paraméter: Szín"])
            finish.select_option(label="Paraméter: Szín")
            expect(parameter_dialog).to_have_count(0)
            expect(page.get_by_role("list", name="Paraméter: Szín hozzárendelései")).to_contain_text("Finish")

            row("3. Custom").get_by_role("combobox").select_option(label="Új paraméter…")
            parameter_dialog.get_by_label("Paraméter neve").fill("Egyedi jellemző")
            parameter_dialog.get_by_role("button", name="Paraméter elfogadása").click()
            page.get_by_label("Sablon neve").fill("Meglévő paraméterrel")
            page.get_by_role("button", name="Sablon mentése", exact=True).click()
            expect(page.get_by_text("Sablon mentve: Meglévő paraméterrel · v1")).to_be_visible()
            reused = saved_payloads[-1]
            assert reused["columns"][1]["target"]["header"] == template["parameters"][0]["header"]
            assert reused["new_parameters"] == [{"name": "Egyedi jellemző", "approved": True}]
            page.get_by_role("button", name="Vissza a megfeleltetéshez").click()
            upload.set_input_files({
                "name": "ismetelt-fejlec.csv",
                "mimeType": "text/csv",
                "buffer": "SKU;Szín;Szín\n0020;Fekete;Fehér\n".encode(),
            })
            expect(page.get_by_text("1 termék · 3 oszlop")).to_be_visible()
            color = page.get_by_role("list", name="Paraméter: Szín hozzárendelései")
            expect(color.get_by_role("listitem")).to_have_count(1)
            expect(color.locator("samp")).to_have_text("Fekete")
            expect(row("3. Szín").locator("samp")).to_have_text("Fehér")
            with Session(engine) as db:
                products = db.scalars(select(SupplierProduct).order_by(SupplierProduct.id))
                assert [(p.id, p.revision, p.last_run_id, p.data) for p in products] == snapshot
            assert not any(
                "approve" in path or "donor-" in path or "enrich" in path
                for _, path in requests
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
