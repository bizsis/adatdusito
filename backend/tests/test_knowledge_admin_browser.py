"""Real reference admin workflow with FastAPI and SQLite, desktop and 390 px."""

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from app import knowledge_uploads as jobs
from conftest import login

DIST = Path(__file__).resolve().parents[2] / "frontend/dist"


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_reference_admin_upload_preview_import_repeat_revoke_and_audit(
    environment, monkeypatch, width, height
):
    client, target, _, _ = environment
    login(client)

    def execute(id):
        with Session(target) as db:
            jobs.process(db, id)

    monkeypatch.setattr(jobs, "enqueue", execute)

    def handle(route):
        url = urlparse(route.request.url)
        if url.path.startswith("/api/"):
            result = client.request(
                route.request.method,
                url.path + ("?" + url.query if url.query else ""),
                content=route.request.post_data_buffer,
                headers={
                    "Content-Type": route.request.headers.get(
                        "content-type", "application/json"
                    )
                },
            )
            route.fulfill(
                status=result.status_code,
                body=result.content,
                content_type=result.headers.get("content-type", "application/json"),
            )
        else:
            file = (DIST / (url.path.lstrip("/") or "index.html")).resolve()
            assert file.is_relative_to(DIST.resolve())
            route.fulfill(
                body=file.read_bytes(),
                content_type=mimetypes.guess_type(file.name)[0] or "text/plain",
            )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=(
                "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None
            ),
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("http://knowledge.test/**", handle)
        page.goto("http://knowledge.test/")
        page.get_by_role("navigation").get_by_role(
            "button", name="Referencia-adatbázisok", exact=True
        ).click()
        upload = page.get_by_role("region", name="Új referenciaadat-import")
        upload.get_by_label("Forrás megnevezése", exact=True).fill("Demó tudásforrás")
        upload.get_by_label("Referencia CSV/XLSX fájl").set_input_files(
            {
                "name": "source.csv",
                "mimeType": "text/csv",
                "buffer": "SKU;NAME;EAN;Gyártó;Email;Nettó Ár\n0001;Mosógép;5201137061819;Minta;private@example.invalid;100\n0002;Porszívó;5904517345546;Minta;secret@example.invalid;200\n".encode(),
            }
        )
        upload.get_by_role("checkbox").check()
        upload.get_by_role(
            "button", name="Feltöltés és oszlopfelismerés", exact=True
        ).click()
        run = page.get_by_role("region", name="Referenciaimport állapota")
        expect(
            run.get_by_role("heading", name=re.compile("Ellenőrzésre váró előnézet"))
        ).to_be_visible()
        expect(
            run.get_by_label("Referencia megfeleltetés: SKU", exact=True)
        ).to_have_value("sku")
        expect(
            run.get_by_label("Referencia megfeleltetés: Email", exact=True)
        ).to_have_value("exclude")
        run.get_by_text("Termékadatok előnézete", exact=True).click()
        expect(run.locator("td").filter(has_text="[Kizárva]")).to_have_count(4)
        expect(run.get_by_text("private@example.invalid", exact=True)).to_have_count(0)
        run.get_by_role("button", name="Referenciaimport indítása", exact=True).click()
        expect(run.get_by_role("heading", name=re.compile("Befejezve"))).to_be_visible()
        detail = page.get_by_role("region", name="Referenciaforrás részletei")
        expect(
            detail.get_by_role("heading", name="Demó tudásforrás", exact=True)
        ).to_be_visible()
        expect(
            detail.get_by_text("Érvényes EAN/GTIN: 2 / 2", exact=False)
        ).to_be_visible()
        run.get_by_role("button", name="Import ismétlése", exact=True).click()
        expect(
            run.get_by_role("heading", name="#2 – Befejezve", exact=False)
        ).to_be_visible()
        expect(
            run.locator("dt", has_text="Változatlan termék").locator("..").locator("dd")
        ).to_have_text("2")
        detail.get_by_text("Forrás és felhasználás kezelése", exact=True).click()
        detail.get_by_label("Felhasználási állapot", exact=True).select_option(
            "revoked"
        )
        detail.get_by_label("Döntés indoklása", exact=True).fill(
            "Teszt: jogosultság visszavonva"
        )
        detail.get_by_role("button", name="Forrásbeállítás mentése", exact=True).click()
        expect(
            detail.get_by_text("Kizárt · A közös dúsításból kizárva", exact=True)
        ).to_be_visible()
        expect(
            detail.get_by_text("Forrásbeállítás módosítása", exact=False)
        ).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        )
        assert not errors
        login(client, "admin@example.hu")
        page.reload()
        expect(
            page.get_by_role("navigation").get_by_role(
                "button", name="Referencia-adatbázisok", exact=True
            )
        ).to_have_count(0)
        assert not errors
        browser.close()
