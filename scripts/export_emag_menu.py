"""Manual public Hungarian eMAG menu capture; run on the operator's own machine.

No database access, no proxy bypass, no credentials, no product-catalog crawling.
Playwright is the only dependency (scripts/browser-requirements.txt).
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.robotparser import RobotFileParser
import zipfile

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.emag.hu/"
CORE = Path(__file__).with_name("emag_menu") / "menu_capture.js"


def save_report(directory, report, errors, robots, browser_name):
    report.update(
        errors=errors,
        robots=robots,
        browser=browser_name,
        execution_location="operator_machine",
        reference_database_writes=False,
    )
    for index, group in enumerate(report.get("root_groups", []), 1):
        html = group.pop("html_evidence", "")
        filename = f"{index:02}-menu.html"
        (directory / filename).write_bytes(html.encode("utf-8"))
        group["html_evidence_file"] = filename
        group["html_sha256"] = hashlib.sha256(html.encode()).hexdigest()
    output = directory / "emag-menu-export.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "OLVASS_EL.txt").write_text(
        "Nyilvános eMAG-menü megfigyelése, nem kész Marketplace-kategóriafa.\n"
        "A JSON a DOM-ban talált neveket és hivatkozásokat tartalmazza.\n"
        "A canonical_emag_id minden új megfigyelésnél null; megfeleltetésre vár.\n"
        "Brand shop / kampány / termékkereső link is előfordulhat: ezeket ellenőrizni kell.\n"
        "A HTML és képernyőképek kizárólag a menü bizonyítékai.\n"
        "A teljes webshop-kategóriafa lefedettségét nem igazoljuk.\n"
        "A ZIP-et add át a fejlesztéshez; jelszófájlt, böngészőprofilt ne csatolj.\n",
        encoding="utf-8",
    )
    archive = directory / "emag-menu-export.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.iterdir()):
            if path.is_file() and path != archive:
                bundle.write(path, path.name)
    return archive


def main():
    parser = argparse.ArgumentParser(
        description="eMAG magyar főmenü és almenük ellenőrizhető exportja"
    )
    parser.add_argument("--output", type=Path, default=Path.home() / "Downloads")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Láthatatlan mód; CAPTCHA/sütidialógus esetén válaszd a látható böngészőt.",
    )
    parser.add_argument(
        "--channel",
        choices=["chrome", "msedge"],
        help="Telepített Chrome vagy Edge használata.",
    )
    parser.add_argument(
        "--executable-path",
        help="Teszteléshez/egyedi telepítéshez a Chromium elérési útja.",
    )
    parser.add_argument(
        "--panel-selector",
        help="Ha a menü DOM-ja eltér: a látható almenü pontos CSS-szelektora.",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Kézi hover + F8 mentés; Enter a terminálban az export lezárásához.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.2,
        help="Minimum 1 másodperc a csoportok között.",
    )
    args = parser.parse_args()
    if args.manual and args.headless:
        parser.error("A kézi módhoz látható böngésző kell.")
    if not CORE.is_file():
        parser.error(
            "Hiányzik a scripts/emag_menu/menu_capture.js fájl. A teljes projektből futtasd."
        )
    directory = args.output / (
        "emag-menu-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    directory.mkdir(parents=True, exist_ok=False)
    errors = []
    robots_info = {}
    report = {
        "root_groups": [],
        "captured_root_count": 0,
        "all_expected_panels_captured": False,
        "full_category_tree_verified": False,
    }
    print("Kimeneti könyvtár:", directory)
    print("A program nem lép be fiókba és nem ment böngészőprofilt vagy sütiket.")
    with sync_playwright() as p:
        launch = {"headless": args.headless}
        if args.channel:
            launch["channel"] = args.channel
        if args.executable_path:
            launch["executable_path"] = args.executable_path
        browser = p.chromium.launch(**launch)
        context = browser.new_context(
            viewport={"width": 1800, "height": 1100}, locale="hu-HU"
        )
        page = context.new_page()
        try:
            response = context.request.get(BASE + "robots.txt", timeout=20000)
            robots_info = {"url": BASE + "robots.txt", "status": response.status}
            if response.status != 200:
                raise RuntimeError(
                    "A robots.txt nem ellenőrizhető. Automatizált letöltés helyett használd a dokumentált, saját böngészős DOM-exportot."
                )
            content = response.text()
            if content.lstrip("\ufeff \r\n\t").startswith("<"):
                raise RuntimeError(
                    "A robots.txt helyett HTML/ellenőrző oldal érkezett; a program leáll."
                )
            robots_info["sha256"] = hashlib.sha256(content.encode()).hexdigest()
            rules = RobotFileParser(BASE + "robots.txt")
            rules.parse(content.splitlines())
            robots_info["homepage_allowed"] = rules.can_fetch(
                "AdatdusitoMenuExport", BASE
            )
            if not robots_info["homepage_allowed"]:
                raise RuntimeError(
                    "A robots szabály nem engedi az automatizált kezdőlap-olvasást; a program leáll."
                )
            page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            if not args.headless:
                print(
                    "\nA megnyílt böngészőben kezeld a sütikérdést, majd hagyd az eMAG főoldalán."
                )
                print(
                    "Nem kell bejelentkezned. Hozzáférés-tiltásnál ne próbálj védelmet megkerülni."
                )
                input("Ha kész: Enter itt a terminálban. ")
            page.evaluate(CORE.read_text(encoding="utf-8"))
            if args.panel_selector:
                page.evaluate(
                    "s=>AdatdusitoMenuCapture.setPanelSelector(s)", args.panel_selector
                )
            # Open the public menu using normal interactions, without following a link.
            trigger = page.get_by_text("Kategóriák", exact=True).first
            try:
                trigger.wait_for(state="visible", timeout=8000)
                trigger.hover(timeout=5000)
                page.wait_for_timeout(400)
                if not page.evaluate("AdatdusitoMenuCapture.discover().length"):
                    trigger.click(timeout=5000)
                page.wait_for_function(
                    "AdatdusitoMenuCapture.discover().length > 0", timeout=6000
                )
            except PlaywrightTimeoutError:
                if not args.manual:
                    errors.append(
                        {"error": "A főmenü nem jelent meg; próbáld a --manual módot."}
                    )
            roots = page.evaluate("AdatdusitoMenuCapture.discover()")
            print("Látható főcsoportok:", len(roots), "/ 13")
            if args.manual:
                print(
                    "Nyisd ki a Kategóriák menüt. Minden bal oldali főcsoport fölött nyomj F8-at."
                )
                print(
                    "A böngésző konzolja jelzi a mentést. Nem szükséges F9-et nyomni."
                )
                input("Ha mind a 13 csoport kész: Enter itt a terminálban. ")
            else:
                for root in roots:
                    label = root["name"]
                    try:
                        locator = page.get_by_text(label, exact=True)
                        # Only the visible root link is hovered, never a product/category page.
                        target = None
                        for candidate in locator.all():
                            if candidate.is_visible():
                                target = candidate
                                break
                        if target is None:
                            raise RuntimeError("A főcsoport nem látható.")
                        target.hover(timeout=6000)
                        page.wait_for_timeout(int(max(1.0, args.delay) * 1000))
                        captured = page.evaluate(
                            "({label,selector})=>AdatdusitoMenuCapture.capture(label,selector?{panelSelector:selector}:{})",
                            {"label": label, "selector": args.panel_selector},
                        )
                        panel = page.evaluate_handle("AdatdusitoMenuCapture.lastPanel")
                        element = panel.as_element()
                        if element:
                            shot = f"{len(page.evaluate('AdatdusitoMenuCapture.report().root_groups')):02}-menu.png"
                            element.screenshot(path=str(directory / shot), timeout=5000)
                        print(
                            "Mentve:",
                            captured["name"],
                            len(captured["links"]),
                            "menühivatkozás",
                        )
                    except Exception as error:
                        errors.append(
                            {"root": label, "error": str(error).splitlines()[0][:300]}
                        )
                        print("Részleges / sikertelen:", label)
            report = page.evaluate("AdatdusitoMenuCapture.report()")
        except Exception as error:
            errors.append({"error": str(error).splitlines()[0][:500]})
            print("A gyűjtés nem teljes:", errors[-1]["error"])
        finally:
            archive = save_report(
                directory, report, errors, robots_info, browser.version
            )
            context.close()
            browser.close()
    print("\nMentett főcsoportok:", report.get("captured_root_count", 0), "/ 13")
    print(
        "Hiányzó főcsoportok:",
        ", ".join(report.get("missing_roots", []))
        or ("nincs" if report.get("all_expected_panels_captured") else "nem mérhető"),
    )
    duplicates = report.get("duplicate_panel_contents", [])
    if duplicates:
        print(
            "Figyelem: azonos paneltartalom több főcsoportnál; kézi ellenőrzés kell:",
            len(duplicates),
        )
    if errors:
        print("Rögzített hibák:", len(errors), "– részletek a JSON-ban.")
    print("A teljes kategóriafa és a Marketplace-megfeleltetés nincs igazolva.")
    print("Átadandó fájl:", archive)
    return (
        0
        if report.get("all_expected_panels_captured")
        and not report.get("duplicate_panel_contents")
        and not errors
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
