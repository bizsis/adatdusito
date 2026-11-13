"""Desktop/mobile UI smoke test, using a synthetic cloud Superadmin only."""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument("--credentials", required=True, type=Path)
parser.add_argument(
    "--artifacts", type=Path, default=Path("/tmp/adatdusito-codex02-browser")
)
args = parser.parse_args()
credentials = json.loads(args.credentials.read_text())
args.artifacts.mkdir(parents=True, exist_ok=True)
base = "http://127.0.0.1:18080"
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="/usr/bin/chromium", args=["--no-sandbox"]
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base)
    expect(page.get_by_role("heading", name="Adatdúsító", exact=True)).to_be_visible()
    expect(
        page.get_by_text(
            "Ügyfelek, felhasználók és kategória és termékparaméter referenciaadatok egy helyen.",
            exact=True,
        )
    ).to_be_visible()
    page.screenshot(path=str(args.artifacts / "login-desktop.png"), full_page=True)
    page.get_by_label("Email-cím", exact=True).fill(credentials["email"])
    page.get_by_label("Jelszó", exact=True).fill("wrong-password")
    page.get_by_role("button", name="Bejelentkezés →").click()
    expect(page.get_by_role("alert")).to_contain_text("Hibás email-cím vagy jelszó.")
    page.get_by_label("Jelszó", exact=True).fill(credentials["password"])
    page.get_by_role("button", name="Bejelentkezés →").click()
    expect(page.get_by_role("heading", name="Áttekintés", exact=True)).to_be_visible()
    expect(page.get_by_text("Alkalmazás-adatbázis", exact=True)).to_be_visible()
    page.screenshot(path=str(args.artifacts / "dashboard-desktop.png"), full_page=True)
    page.get_by_role("navigation").get_by_role("button", name="eMAG-kategóriák").click()
    expect(
        page.get_by_text("Hiányzó szülőjű kategória", exact=False).first
    ).to_be_visible()
    page.get_by_role("button", name="Műszaki cikkek alkategóriái", exact=True).click()
    page.get_by_role("button", name="Laptopok eMAG 2000", exact=False).click()
    expect(page.get_by_role("heading", name="Laptopok", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Termékbesorolásra választható", exact=True)
    ).to_be_visible()
    expect(page.locator(".category-full-path")).to_contain_text(
        "Műszaki cikkek / Laptopok"
    )
    expect(page.locator(".tree-row.selected")).to_contain_text("Laptopok")
    expect(page.get_by_text("Paraméterek: 1", exact=True)).to_be_visible()
    page.get_by_role("button", name="Műszaki cikkek", exact=True).click()
    expect(
        page.get_by_role("heading", name="Műszaki cikkek", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Alkategóriák megnyitása", exact=True).click()
    expect(page.locator(".tree-location")).to_contain_text("Műszaki cikkek")
    page.get_by_role("button", name="Laptopok eMAG 2000", exact=False).click()
    expect(page.get_by_text("Szín", exact=True)).to_be_visible()
    page.get_by_role("button", name="Megnyitás →").click()
    expect(page.locator(".value-list li").filter(has_text="Fekete")).to_be_visible()
    page.screenshot(path=str(args.artifacts / "reference-desktop.png"), full_page=True)
    page.get_by_label("Kategóriakeresés", exact=True).fill("Laptop")
    expect(page.locator(".tree-path")).to_contain_text("Műszaki cikkek")
    page.get_by_role(
        "combobox", name="Kategóriafa megjelenítése", exact=True
    ).select_option("all")
    expect(
        page.get_by_role(
            "heading", name="Források és tényleges lefedettség", exact=True
        )
    ).to_be_visible()
    expect(
        page.locator(".source-grid").get_by_text("eMAG magyar webshop", exact=True)
    ).to_be_visible()
    page.get_by_role("navigation").get_by_role("button", name="Felhasználók").click()
    expect(page.get_by_role("heading", name="Felhasználók", exact=True)).to_be_visible()
    page.get_by_role("button", name="+ Új felhasználó").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="Bezárás", exact=True).click()
    page.get_by_role("navigation").get_by_role("button", name="Ügyfelek").click()
    expect(page.get_by_role("heading", name="Ügyfelek", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.get_by_role("heading", name="Ügyfelek", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "Mobile page overflows viewport"
    )
    page.screenshot(path=str(args.artifacts / "tenants-mobile.png"), full_page=True)
    page.get_by_role("navigation").get_by_role("button", name="eMAG-kategóriák").click()
    expect(
        page.get_by_role("heading", name="eMAG-kategóriák", exact=True)
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(args.artifacts / "reference-mobile.png"), full_page=True)
    page.get_by_role("button", name="Kilépés", exact=True).click()
    expect(page.get_by_role("heading", name="Adatdúsító", exact=True)).to_be_visible()
    assert not errors, errors
    browser.close()
print(
    "Desktop and 390px mobile UI: login failure/success, dashboard, hierarchy, parameter values, users, tenants, dialog and logout passed; no JavaScript errors."
)
