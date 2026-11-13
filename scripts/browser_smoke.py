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
    page.get_by_role("navigation").get_by_role("button", name="Kategóriák").click()
    expected_roots = [
        "Háztartási gépek és klíma",
        "TV és szórakozás",
        "Telefon, Tablet, Laptop",
        "Számítástechnika",
        "Fotó-Videó, Okos eszközök",
        "Szupermarket",
        "Otthon, barkács, kert",
        "Játékok, Baba, Mama",
        "Divat, ékszerek és kiegészítők",
        "Szépségápolás",
        "Sport és utazás",
        "Könyvek, Filmek és Irodaszerek",
        "Autó- és motor felszerelések",
    ]
    expect(page.locator(".tree > ul > li")).to_have_count(13)
    names = page.locator(".tree > ul > li > .tree-row > .tree-name").evaluate_all(
        "(items)=>items.map(e=>e.childNodes[0].textContent.trim())"
    )
    assert names == expected_roots
    page.screenshot(
        path=str(args.artifacts / "webshop-roots-desktop.png"), full_page=True
    )
    page.get_by_role("button", name="TV és szórakozás alkategóriái", exact=True).click()
    page.locator("button.tree-name").filter(has_text="Televíziók").first.click()
    expect(page.get_by_role("heading", name="Televíziók", exact=True)).to_be_visible()
    expect(page.locator(".category-full-path")).to_contain_text(
        "TV és szórakozás / Televíziók"
    )
    expect(page.get_by_text("LED TV", exact=True)).to_be_visible()
    assert (
        page.get_by_role("heading", name="Kategóriaparaméterek", exact=True).count()
        == 0
    )
    page.get_by_role("button", name="TV és szórakozás /", exact=True).click()
    expect(
        page.get_by_role("heading", name="TV és szórakozás", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Alkategóriák megnyitása", exact=True).click()
    expect(page.locator(".tree-location")).to_contain_text("TV és szórakozás")
    page.get_by_label("Kategóriakeresés", exact=True).fill("Televíziók")
    expect(page.locator(".tree-path").first).to_contain_text("TV és szórakozás")
    page.screenshot(
        path=str(args.artifacts / "webshop-hierarchy-desktop.png"), full_page=True
    )
    page.get_by_role("navigation").get_by_role("button", name="Paraméterkereső").click()
    expect(page.get_by_text("Szín", exact=True)).to_be_visible()
    page.get_by_role("button", name="Megnyitás →").first.click()
    expect(page.locator(".value-list li").filter(has_text="Fekete")).to_be_visible()
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
    page.get_by_role("navigation").get_by_role("button", name="Kategóriák").click()
    expect(page.get_by_role("heading", name="Kategóriák", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator(".tree > ul > li")).to_have_count(13)
    page.screenshot(path=str(args.artifacts / "reference-mobile.png"), full_page=True)
    page.get_by_role("button", name="Kilépés", exact=True).click()
    expect(page.get_by_role("heading", name="Adatdúsító", exact=True)).to_be_visible()
    assert not errors, errors
    browser.close()
print(
    "Desktop and 390px mobile UI: login failure/success, dashboard, hierarchy, parameter values, users, tenants, dialog and logout passed; no JavaScript errors."
)
