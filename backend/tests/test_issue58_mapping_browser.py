"""#58 browser flow using the actual API and an isolated SQLite catalog."""

from importlib.util import find_spec
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import import_api
from app.import_engine import advance
from app.import_models import ImportProfile, ImportRun, SupplierProduct
from conftest import login
from test_product_classification import detail, patch
from test_product_parameters import WASHER, install_catalog

pytestmark = pytest.mark.skipif(
    find_spec("app.import_mapping_views") is None,
    reason="The real IMPORT-MAP-01 browser test requires backend PR #59.",
)
DIST = Path(__file__).resolve().parents[2] / "frontend/dist"
BASE = "/api/v1/imports"


@pytest.mark.parametrize("width", [390, 1440])
def test_upload_review_save_and_prepare_donor_parameters(
    environment, monkeypatch, width
):
    client, target, _, _ = environment
    install_catalog(target)

    def execute(run_id):
        with Session(target) as db:
            advance(db, run_id)

    monkeypatch.setattr(import_api, "enqueue", execute)
    login(client, "admin@example.hu")
    csrf = client.headers["X-CSRF-Token"]
    calls = []
    errors = []
    retry_approval = width == 1440

    def handle(route):
        nonlocal retry_approval
        request = route.request
        url = urlparse(request.url)
        if url.path.startswith("/api/"):
            if request.method != "GET":
                assert request.headers.get("x-csrf-token") == csrf
            path = url.path + (f"?{url.query}" if url.query else "")
            calls.append((request.method, url.path))
            if url.path.endswith("/approve") and retry_approval:
                retry_approval = False
                route.fulfill(
                    status=503,
                    json={"error": {"message": "Próbahiba az import jóváhagyásakor."}},
                )
                return
            response = client.request(
                request.method,
                path,
                content=request.post_data_buffer,
                headers={
                    "Content-Type": request.headers.get(
                        "content-type", "application/json"
                    )
                },
            )
            if url.path.endswith("/approve") and response.is_success:
                # Donor classification comes from the existing product workflow.
                # Establish real classifications before checking the mapping UI.
                with Session(target) as db:
                    ids = list(db.scalars(select(SupplierProduct.id)))
                for pid in ids:
                    result = patch(
                        client,
                        pid,
                        expected_revision=detail(client, pid)["revision"],
                        action="set",
                        navigation_node_id=WASHER,
                    )
                    assert result.status_code == 200, result.text
            route.fulfill(
                status=response.status_code,
                body=response.content,
                content_type=response.headers.get("content-type", "application/json"),
            )
            return
        file = (DIST / (url.path.lstrip("/") or "index.html")).resolve()
        assert file.is_relative_to(DIST.resolve())
        route.fulfill(
            body=file.read_bytes(),
            content_type=mimetypes.guess_type(file.name)[0]
            or "application/octet-stream",
        )

    with sync_playwright() as p:
        chromium = Path("/usr/bin/chromium")
        with p.chromium.launch(
            executable_path=str(chromium) if chromium.exists() else None,
            args=["--no-sandbox"],
        ) as browser:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://mapping.test/**", handle)
            page.goto("http://mapping.test/")
            page.get_by_role("navigation").get_by_role(
                "button", name="Beszállítói import", exact=True
            ).click()
            page.get_by_label("Új beszállító neve").fill("UNAS tesztbeszállító")
            page.get_by_role("button", name="Beszállító létrehozása").click()
            upload = page.get_by_label("CSV/XLSX fájl")
            expect(upload).to_be_enabled()
            upload.set_input_files(
                {
                    "name": "beszallito.csv",
                    "mimeType": "text/csv",
                    "buffer": (
                        "SKU;NAME;CATEGORY;NetPrice;EAN;Color;Unknown_01;Width\n"
                        "0001;Mosógép A;Gépek;100;5201137061819;Fekete;Megőrzött adat;60\n"
                        "0002;Mosógép B;Gépek;200;8,71999E+12;Fehér;B;59\n"
                        "0003;Mosógép C;Gépek;300;5904517345546;Fekete;C;61\n"
                    ).encode(),
                }
            )

            wizard = page.get_by_role("region", name="Oszlopmegfeleltetés", exact=True)
            expect(wizard.get_by_text("3 termék · 8 forrásoszlop")).to_be_visible(
                timeout=15000
            )
            columns = wizard.get_by_role("list", name="Forrásoszlopok").locator(
                ":scope > li"
            )
            expect(columns).to_have_count(8)
            expect(columns.nth(0)).to_contain_text("0001")
            expect(columns.nth(4)).to_contain_text("5201137061819")
            expect(columns.nth(4)).to_contain_text("8,71999E+12")
            expect(columns.nth(4)).to_contain_text("Tudományos jelölésű")
            expect(columns.nth(6)).to_contain_text("Megőrzött adat")
            expect(columns.nth(6).get_by_role("combobox")).to_have_value("")
            for index in (0, 1, 2, 3, 4, 5):
                columns.nth(index).get_by_role(
                    "button", name="Javaslat átvétele"
                ).click()
            expect(
                columns.nth(5).get_by_role("textbox", name="Paraméternév")
            ).to_have_value("Szín")

            check = wizard.get_by_role("button", name="Megfeleltetés ellenőrzése")
            expect(check).to_be_disabled()
            columns.nth(5).get_by_role("checkbox").check()
            width_row = columns.nth(7)
            width_row.get_by_role(
                "combobox", name="Célmező:", exact=False
            ).select_option("new")
            width_row.get_by_role("textbox", name="Paraméternév").fill("Szélesség")
            width_row.get_by_label("Típus").select_option("num")
            width_row.get_by_label("Mértékegység").fill("cm")
            width_row.get_by_role("checkbox").check()
            check.click()
            expect(
                wizard.get_by_role("alert", name="").filter(
                    has_text="pénzügyi megfeleltetés"
                )
            ).to_be_visible()
            with Session(target) as db:
                assert db.scalar(select(ImportProfile.id)) is None

            wizard.get_by_label("Jóváhagyom a pénzügyi megfeleltetést").check()
            wizard.get_by_label("Ismert egységes áfakulcs").select_option("27")
            check.click()
            expect(wizard.get_by_text("A megfeleltetés menthető.")).to_be_visible()
            expect(
                wizard.get_by_text(
                    "Számítás a nettó árból és az ismert áfakulcsból", exact=False
                )
            ).to_be_visible()
            expect(
                wizard.get_by_text("Alapértelmezett érték: 1", exact=False)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            wizard.get_by_role(
                "button", name="Megfeleltetés jóváhagyása és mentése"
            ).click()
            if width == 1440:
                expect(wizard.get_by_role("alert")).to_contain_text("Próbahiba")
                wizard.get_by_role(
                    "button", name="Import jóváhagyásának újrapróbálása"
                ).click()
            donor = page.get_by_role("region", name="Hiányzó eMAG-paraméterek")
            expect(
                donor.get_by_role("list", name="Eredeti beszállítói kategóriák")
            ).to_contain_text("Gépek (3 termék)", timeout=15000)
            expect(donor.get_by_label("eMAG-donor")).to_have_value("385")
            parameters = donor.get_by_role("list", name="Donorparaméterek")
            expect(parameters.get_by_role("checkbox")).to_have_count(7)
            expect(
                parameters.get_by_role("checkbox", name="Szín", exact=False)
            ).to_be_disabled()
            expect(
                parameters.get_by_role("checkbox", name="Szélesség", exact=False)
            ).to_be_disabled()

            donor.get_by_role("button", name="Összes kijelölése").click()
            expect(donor.get_by_role("status").filter(has_text="5 / 5")).to_be_visible()
            donor.get_by_role("button", name="Kijelölés törlése").click()
            expect(donor.get_by_role("status").filter(has_text="0 / 5")).to_be_visible()
            energy = parameters.get_by_role(
                "checkbox", name="Energiaosztály", exact=False
            )
            energy.click()
            expect(energy).to_be_checked()
            expect(
                donor.get_by_text("1 előkészített eMAG-mező", exact=False)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            assert calls.count(("POST", f"{BASE}/runs/1/column-mapping")) == 1
            detail_response = client.get(f"{BASE}/runs/1/prepared-fields").json()
            assert detail_response["donor_parameters"] == [
                {
                    "emag_category_id": 385,
                    "emag_parameter_id": 6509,
                    "name": "Energiaosztály",
                    "state": "selected_empty",
                }
            ]
            with Session(target) as db:
                run = db.get(ImportRun, 1)
                profile = db.get(ImportProfile, run.config["engine_mapping_profile_id"])
                stored = profile.config["engine_mapping"]
                assert stored["columns"][6]["target"] is None
                assert {
                    (p["name"], p["param_type"], p["unit"])
                    for p in stored["parameters"]
                } == {
                    ("Szín", "text", None),
                    ("Szélesség", "num", "cm"),
                }
                products = list(
                    db.scalars(select(SupplierProduct).order_by(SupplierProduct.id))
                )
                assert len(products) == 3
                assert products[0].data["sku"] == "0001"
                assert all(product.data["category"] == "Gépek" for product in products)
                assert "Unknown_01" in products[0].source_attributes

            # A later upload must reuse the stored decisions and expose changed headers.
            upload.set_input_files(
                {
                    "name": "masodik.csv",
                    "mimeType": "text/csv",
                    "buffer": (
                        "SKU;NAME;CATEGORY;NetPrice;EAN;Color;Unknown_02;Width;SHORT;LONG\n"
                        "0004;Mosógép D;Gépek;400;5201137061819;Fekete;Új;55;Rövid;Hosszú\n"
                        "0004;Mosógép D;Gépek;400;5201137061819;Fehér;Új;55;Rövid;Hosszú\n"
                    ).encode(),
                }
            )
            expect(
                wizard.get_by_text("Új oszlopok: LONG, SHORT, Unknown_02", exact=False)
            ).to_be_visible(timeout=15000)
            expect(
                wizard.get_by_role(
                    "combobox", name="Célmező: Color, 6. oszlop", exact=True
                )
            ).to_have_value("parameter:Paraméter: Szín||text|1|0|1|0|0|0|||0|1|1")
            wizard.get_by_role(
                "combobox", name="Célmező: SHORT, 9. oszlop", exact=True
            ).select_option("field:rovid_leiras")
            wizard.get_by_role(
                "combobox", name="Célmező: LONG, 10. oszlop", exact=True
            ).select_option("field:tulajdonsagok")
            wizard.get_by_label("Jóváhagyom a pénzügyi megfeleltetést").check()
            check.click()
            expect(wizard.get_by_text("A megfeleltetés menthető.")).to_be_visible()
            expect(
                wizard.get_by_text(
                    "Az import soronként jelzi az ismétlődéseket.", exact=False
                )
            ).to_contain_text("0004")
            expect(
                wizard.get_by_text("eredeti forrásadatként megmaradnak", exact=False)
            ).to_contain_text("Oszlop: SHORT")
            expect(
                wizard.get_by_role(
                    "button", name="Megfeleltetés jóváhagyása és mentése"
                )
            ).to_be_enabled()
            assert not errors
