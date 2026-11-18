"""Browser acceptance tests against documented TEMPLATE-PREP-01 responses."""

import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

DIST = Path(__file__).resolve().parents[1] / "dist"
CURRENCIES = "HUF EUR USD GBP CHF CZK PLN RON BGN RSD UAH".split()
FIELDS = [
    ("cikkszam", "Cikkszám"),
    ("termek_megnevezes", "Termék megnevezés"),
    ("kategoria", "Kategória"),
    ("alternativ_kategoria", "Alternatív kategória"),
    ("gyarto", "Gyártó"),
    ("raktarkeszlet", "Raktárkészlet #0"),
    ("netto_ar", "Nettó ár"),
    ("brutto_ar", "Bruttó ár"),
    ("netto_akcios_ar", "Nettó akciós ár"),
    ("brutto_akcios_ar", "Bruttó akciós ár"),
    ("akcio_kezdete", "Akció kezdete"),
    ("akcio_vege", "Akció vége"),
    ("afa", "ÁFA"),
    ("ean", "EAN"),
    ("gyartoi_cikkszam", "Gyártói cikkszám"),
    ("reszletes_leiras", "Részletes leírás"),
    ("rovid_leiras", "Rövid leírás"),
    ("mennyisegi_egyseg", "Mennyiségi egység"),
    ("masodlagos_egyseg", "Másodlagos egység"),
    ("masodlagos_mennyiseg", "Másodlagos mennyiség"),
    ("min_rendelheto", "Min. rendelhető mennyiség"),
    ("lepeskoz", "Lépésköz"),
    ("statusz", "Státusz"),
    ("tomeg", "Tömeg"),
    ("osszevonas_alapja", "Termék összevonás alapja"),
    ("export_tiltas", "Export tiltás"),
    ("kep", "Kép"),
    ("lapful_1", "További lapfül 1"),
    ("lapful_2", "További lapfül 2"),
    ("lapful_3", "További lapfül 3"),
    ("kiegeszito_termekek", "Kiegészítő termékek"),
    ("hasonlo_termekek", "Hasonló termékek"),
    ("parameter", "Paraméter"),
]
VALUES = [
    ("SKU", "0001"),
    ("NAME", "Termék"),
    ("CATEGORY", "Saját|Áru"),
    ("Color", "Fekete"),
    ("Image1", "https://example.invalid/1.png"),
    ("Image2", "https://example.invalid/2.png"),
    ("Alt1", "Kategória 1"),
    ("Alt2", "Kategória 2"),
    ("Stock1", "3"),
    ("Stock2", "31"),
    ("Barcode", "8,71999E+12"),
    ("Unknown_01", "Megmarad"),
    ("Currency", "EUR"),
]
DEFAULTS = {"statusz": "1", "afa": "27"}
OLD_RUN = {
    "id": 11,
    "filename": "korabbi.csv",
    "supplier_id": 1,
    "state": "completed",
    "error": None,
}
PARAMETER = {"name": "Szín", "param_type": "text", "group_name": "", "unit": None}


def targets():
    engine = {"key": "unas", "name": "UNAS"}
    return {
        "engine": engine,
        "engines": [engine],
        "currencies": CURRENCIES,
        "default_currency": "HUF",
        "defaults": DEFAULTS,
        "targets": [
            {
                "key": key,
                "label": label,
                "required": key == "cikkszam",
                "type": "price" if key.endswith("_ar") else "text",
                "multiple": (
                    "instances"
                    if key in {"alternativ_kategoria", "raktarkeszlet", "parameter"}
                    else "ordered" if key == "kep" else None
                ),
            }
            for key, label in FIELDS
        ],
    }


@pytest.fixture
def open_application():
    def open_page(browser, width, write=True, catalog_available=True):
        page = browser.new_page(viewport={"width": width, "height": 900})
        state = {"requests": [], "saves": [], "reports": [], "errors": [], "uploads": 0}
        page.on("pageerror", lambda error: state["errors"].append(str(error)))
        suppliers = [{"id": 1, "name": "Minta beszállító"}]
        runs = [OLD_RUN]
        saved = []

        def handle(route):
            request = route.request
            url = urlparse(request.url)
            path = url.path.removeprefix("/api/v1")
            if not url.path.startswith("/api/"):
                file = (DIST / (url.path.lstrip("/") or "index.html")).resolve()
                assert file.is_relative_to(DIST.resolve())
                route.fulfill(
                    body=file.read_bytes(),
                    content_type=mimetypes.guess_type(file.name)[0],
                )
                return

            method = request.method
            query = parse_qs(url.query)
            state["requests"].append((method, path, query))
            if method != "GET":
                assert request.headers["x-csrf-token"] == "csrf-prep"
            if path == "/auth/me":
                response = {
                    "user": {
                        "id": 1,
                        "name": "Teszt",
                        "active": True,
                        "superadmin": False,
                    },
                    "tenant_id": 1,
                    "system": False,
                    "workspace": {"tenant_id": 1, "name": "Teszt ügyfél"},
                    "workspaces": [],
                    "memberships": [],
                    "role": "tenant_admin",
                    "csrf_token": "csrf-prep",
                    "permissions": [
                        "imports.read",
                        "exports.read",
                        "exports.fields.manage",
                    ]
                    + (
                        ["imports.create", "imports.manage", "imports.approve"]
                        if write
                        else []
                    ),
                }
            elif path == "/auth/methods":
                response = {
                    "password": True,
                    "branding": {"display_name": "Adatdúsító"},
                }
            elif path == "/access/workspaces":
                response = {"items": [{"tenant_id": 1, "name": "Teszt ügyfél"}]}
            elif path == "/system/status":
                response = {"status": "ok", "checks": {}}
            elif path == "/imports/template-targets":
                assert query == {"engine": ["unas"]}
                if not catalog_available:
                    route.fulfill(
                        status=404,
                        json={
                            "error": {"message": "A sablon API még nincs telepítve."}
                        },
                    )
                    return
                response = targets()
            elif path == "/imports/suppliers":
                if method == "POST":
                    response = {"id": 2, "name": request.post_data_json["name"]}
                    suppliers.append(response)
                else:
                    response = suppliers
            elif path == "/imports/runs":
                if method == "POST":
                    assert (
                        'name="supplier_id"' in request.post_data
                        and 'name="purpose"' in request.post_data
                        and "\r\n\r\ntemplate\r\n" in request.post_data
                        and "friss.csv" in request.post_data
                    )
                    state["uploads"] += 1
                    response = {
                        "id": 20 + state["uploads"],
                        "supplier_id": 1,
                        "filename": "friss.csv",
                        "state": "uploaded",
                        "error": None,
                    }
                    runs.insert(0, response)
                else:
                    response = runs
            elif path.startswith("/imports/suppliers/") and path.endswith(
                "/import-templates"
            ):
                response = {
                    "templates": (
                        [
                            {
                                **saved[-1]["version"],
                                "currency": saved[-1]["body"]["currency"],
                                "versions": len(saved),
                                "columns": len(VALUES),
                                "price_missing": True,
                            }
                        ]
                        if saved
                        else []
                    ),
                    "legacy": [
                        {
                            "id": 30,
                            "name": "Korábbi profil",
                            "version": 2,
                            "kind": "import_profile",
                        }
                    ],
                }
            elif path.startswith("/imports/import-templates/") and path.endswith(
                "/versions"
            ):
                response = [item["version"] for item in saved]
            elif path.startswith("/imports/runs/") and path.endswith(
                "/template-preparation"
            ):
                run_id = int(path.split("/")[3])
                archived = run_id == 11
                assert query["engine"] == ["unas"]
                chosen = query.get("template_id", [None])[0]
                matched = next(
                    (item for item in saved if str(item["version"]["id"]) == chosen),
                    None,
                )
                if chosen is None and saved and not archived:
                    matched = saved[-1]
                columns = []
                drift = run_id > 21
                for index, (header, value) in enumerate(VALUES):
                    changed = drift and header == "Unknown_01"
                    if changed:
                        header = "Unknown_02"
                    suggestion = None
                    assignment = None
                    if index in (0, 1, 2):
                        target = {"key": FIELDS[index][0]}
                        assignment = {"state": "mapped", "target": target}
                        suggestion = {
                            "target": target,
                            "confidence": 1,
                            "method": "exact",
                        }
                    elif header == "Color":
                        suggestion = {
                            "target": {"key": "parameter", "parameter": PARAMETER},
                            "confidence": 0.7,
                            "method": "new_parameter",
                        }
                    source = "auto" if assignment else None
                    if matched and not changed:
                        assignment = {
                            k: v
                            for k, v in matched["body"]["columns"][index].items()
                            if k != "index"
                        }
                        source = "template"
                    columns.append(
                        {
                            "index": index,
                            "header": header,
                            "occurrence": 1,
                            "sample": value,
                            "empty": False,
                            "sample_source": "analysis" if archived else "file",
                            "warnings": (
                                ["scientific_notation_identifier"]
                                if index == 10
                                else []
                            ),
                            "suggestion": suggestion,
                            "assignment": assignment,
                            "assignment_source": source,
                            "status": (
                                "new"
                                if changed
                                else (
                                    "from_template"
                                    if source == "template"
                                    else "unmapped"
                                )
                            ),
                        }
                    )
                currency = query["currency"][0]
                response = {
                    "run_id": run_id,
                    "supplier_id": 1,
                    "engine": "unas",
                    "currency": currency,
                    "file": {
                        "format": "csv",
                        "data_rows": None if archived else 3,
                        "source_available": not archived,
                    },
                    "columns": columns,
                    "template_candidates": [],
                    "approved_parameters": [],
                    "template": (
                        {
                            **matched["version"],
                            "missing_headers": ["Unknown_01"] if drift else [],
                            "new_headers": ["Unknown_02"] if drift else [],
                        }
                        if matched
                        else None
                    ),
                    "defaults": matched["body"]["defaults"] if matched else DEFAULTS,
                    "warnings": (
                        [
                            {
                                "code": "currency_mismatch",
                                "columns": [12],
                                "values": ["EUR"],
                            }
                        ]
                        if currency != "EUR"
                        else []
                    ),
                }
            elif path.endswith("/template-preparation/validate"):
                body = request.post_data_json
                state["reports"].append(body)
                errors = (
                    []
                    if any(
                        (c.get("target") or {}).get("key") == "cikkszam"
                        for c in body["columns"]
                    )
                    else [{"code": "cikkszam_required"}]
                )
                response = {
                    "valid": not errors,
                    "errors": errors,
                    "warnings": [{"code": "price_missing"}],
                    "fields": [],
                    "price_missing": True,
                }
            elif path == "/imports/import-templates" and method == "POST":
                body = request.post_data_json
                state["saves"].append(body)
                version = {
                    "id": 41 + len(saved),
                    "name": body["name"],
                    "version": len(saved) + 1,
                    "template_key": "minta",
                }
                saved.append({"body": body, "version": version})
                response = {
                    **version,
                    "price_missing": True,
                    "validation": {
                        "valid": True,
                        "errors": [],
                        "warnings": [{"code": "price_missing"}],
                        "fields": [],
                        "price_missing": True,
                    },
                }
            elif path.startswith("/imports/runs/") and method == "GET":
                run = next(run for run in runs if run["id"] == int(path.split("/")[-1]))
                response = {**run, "state": "awaiting_approval"}
            else:
                route.fulfill(
                    status=404, json={"error": {"message": f"Váratlan végpont: {path}"}}
                )
                return
            route.fulfill(json=response)

        page.route("http://prep.test/**", handle)
        page.goto("http://prep.test/")
        navigation = page.get_by_role("navigation")
        expect(
            navigation.get_by_role("button", name="Import", exact=True)
        ).to_have_count(1)
        expect(
            navigation.get_by_role("button", name="Beszállítói import", exact=True)
        ).to_have_count(0)
        expect(
            navigation.get_by_role("button", name="Export", exact=True)
        ).to_have_count(0)
        navigation.get_by_role("button", name="Import", exact=True).click()
        return page, state

    return open_page


@pytest.fixture
def chromium():
    with sync_playwright() as p:
        with p.chromium.launch(
            executable_path=(
                "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None
            ),
            args=["--no-sandbox"],
        ) as browser:
            yield browser


@pytest.mark.parametrize("width", [390, 1440])
def test_full_template_preparation(open_application, chromium, width):
    page, state = open_application(chromium, width)
    expect(
        page.get_by_role("heading", name="Előkészítés / Sablonkészítés")
    ).to_be_visible()
    currency = page.get_by_label("Pénznem", exact=True)
    motor = page.get_by_label("Webshopmotor")
    expect(currency).to_have_value("HUF")
    expect(currency.locator("option")).to_have_text(CURRENCIES)
    motor.select_option("unas")
    targets_panel = page.get_by_role("region", name="UNAS-célmezők")
    expect(targets_panel.locator(".prep-list strong")).to_have_text(
        [
            label + (" *" if index == 0 else "")
            for index, (_, label) in enumerate(FIELDS)
        ]
    )
    expect(page.get_by_role("heading", name="Beszállító és fájl")).to_be_visible()
    expect(page.get_by_text("Feldolgozott sorok", exact=True)).to_have_count(0)
    expect(page.get_by_text("Hiányzó eMAG-paraméterek", exact=True)).to_have_count(0)
    expect(page.get_by_label("Státusz alapértéke")).to_have_value("1")
    expect(page.get_by_label("ÁFA alapértéke")).to_have_value("27")
    page.get_by_label("ÁFA alapértéke").select_option("5")
    supplier = page.get_by_label("Beszállító", exact=True)
    supplier.select_option("1")
    page.get_by_text("Új beszállító", exact=True).click()
    page.get_by_label("Új beszállító neve").fill("Második beszállító")
    page.get_by_role("button", name="Beszállító létrehozása").click()
    expect(supplier).to_have_value("2")
    supplier.select_option("1")

    upload = page.get_by_label("CSV, XLS, XLSX vagy XML fájl")
    expect(upload).to_have_attribute("accept", ".csv,.xls,.xlsx,.xml")
    payload = {
        "name": "friss.csv",
        "mimeType": "text/csv",
        "buffer": b"SKU;NAME\n0001;Termek\n0002;Masik\n0003;Harmadik\n",
    }
    upload.set_input_files(payload)
    sources = page.get_by_role("list", name="Forrásoszlopok")
    rows = sources.locator(":scope > li")
    expect(rows).to_have_count(len(VALUES))
    expect(page.get_by_text("3 termék · 13 oszlop")).to_be_visible()
    expect(rows.nth(0).locator("samp")).to_have_text("0001")
    expect(rows.nth(10).locator("samp")).to_have_text("8,71999E+12")
    expect(rows.nth(10)).to_contain_text("hiányzó számjegyek")
    expect(page.get_by_text("Az értékek átváltás nélkül", exact=False)).to_be_visible()
    currency.select_option("EUR")
    expect(page.get_by_text("Az értékek átváltás nélkül", exact=False)).to_have_count(0)

    expect(
        targets_panel.get_by_role("list", name="Cikkszám hozzárendelései")
    ).to_contain_text("SKU")
    targets_panel.get_by_role("button", name="1. SKU hozzárendelés törlése").click()
    expect(rows.nth(0).get_by_role("combobox")).to_have_value("")
    if width == 1440:
        rows.nth(0).locator(".prep-source-handle").drag_to(
            targets_panel.locator('[data-target="cikkszam"]')
        )
    else:
        rows.nth(0).get_by_role("combobox").select_option(label="Cikkszám")
    expect(
        targets_panel.get_by_role("list", name="Cikkszám hozzárendelései")
    ).to_contain_text("SKU")

    if width == 1440:
        name_bindings = targets_panel.get_by_role(
            "list", name="Termék megnevezés hozzárendelései"
        )
        source_handle = name_bindings.locator(".prep-binding-handle")
        target_handle = rows.nth(2).locator(".prep-source-handle")
        target_handle.scroll_into_view_if_needed()
        source_handle.hover()
        box = source_handle.bounding_box()
        assert box
        page.mouse.down()
        page.mouse.move(
            box["x"] + box["width"] / 2 + 16, box["y"] + box["height"] / 2, steps=5
        )
        target_handle.hover()
        target_handle.hover()  # Chromium fires dragover after a second pointer move.
        page.mouse.up()
        expect(name_bindings).to_contain_text("CATEGORY")
        expect(rows.nth(1).get_by_role("combobox")).to_have_value("")
        rows.nth(1).get_by_role("combobox").select_option(label="Termék megnevezés")
        rows.nth(2).get_by_role("combobox").select_option(label="Kategória")

    rows.nth(3).get_by_role(
        "button", name="Javaslat átvétele: Paraméter: Szín", exact=False
    ).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Paraméter neve")).to_have_value("Szín")
    dialog.get_by_label("Paraméter neve").fill("Termékszín")
    dialog.get_by_label("Paraméter típusa").select_option("enum")
    dialog.get_by_role("button", name="Paraméter elfogadása").click()
    expect(
        targets_panel.get_by_role("list", name="Paraméter: Termékszín hozzárendelései")
    ).to_contain_text("Color")

    targets_panel.get_by_role(
        "button", name="+ Alternatív kategória", exact=True
    ).click()
    targets_panel.get_by_role("button", name="+ Raktárkészlet", exact=True).click()
    for index, field in [
        (4, "Kép"),
        (5, "Kép"),
        (6, "Alternatív kategória"),
        (7, "Alternatív kategória 2"),
        (8, "Raktárkészlet #0"),
        (9, "Raktárkészlet #1"),
    ]:
        rows.nth(index).get_by_role("combobox").select_option(label=field)
    targets_panel.get_by_role("button", name="6. Image2 előrébb").click()
    expect(
        targets_panel.get_by_role("list", name="Kép hozzárendelései")
        .get_by_role("listitem")
        .first
    ).to_contain_text("Image2")
    targets_panel.get_by_role("button", name="+ Paraméter", exact=True).click()
    dialog.get_by_label("Paraméter neve").fill("Ellenőrző mező")
    dialog.get_by_label("Forrásoszlop").select_option("11")
    dialog.get_by_role("button", name="Paraméter elfogadása").click()
    expect(
        targets_panel.get_by_role(
            "list", name="Paraméter: Ellenőrző mező hozzárendelései"
        )
    ).to_contain_text("Unknown_01")
    targets_panel.get_by_role(
        "button", name="12. Unknown_01 hozzárendelés törlése"
    ).click()
    expect(rows.nth(11).get_by_role("combobox")).to_have_value("")
    rows.nth(11).get_by_role("combobox").select_option("unused")
    expect(rows.nth(11).locator("samp")).to_have_text("Megmarad")
    expect(page.get_by_label("Státusz alapértéke")).to_have_value("1")
    expect(page.get_by_label("ÁFA alapértéke")).to_have_value("5")
    page.get_by_label("Státusz alapértéke").select_option("0")
    page.get_by_label("ÁFA alapértéke").select_option("18")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_label("Sablon neve").fill("UNAS sablon")
    page.get_by_role("button", name="Sablon mentése", exact=True).click()
    expect(page.get_by_text("Sablon mentve: UNAS sablon · v1")).to_be_visible()
    expect(page.get_by_text("Hiányzik az eladási ár.", exact=False)).to_be_visible()
    first = state["saves"][0]
    assert len(first["columns"]) == len(VALUES)
    assert (
        first["defaults"] == {"statusz": "0", "afa": "18"}
        and first["currency"] == "EUR"
    )
    assert first["columns"][11] == {"index": 11, "state": "unused"}
    assert first["columns"][12] == {"index": 12, "state": None}
    assert first["columns"][4]["target"] == {"key": "kep", "order": 2}
    assert first["columns"][5]["target"] == {"key": "kep", "order": 1}
    assert first["new_parameters"] == [
        {**PARAMETER, "name": "Termékszín", "param_type": "enum", "approved": True}
    ]

    upload.set_input_files(payload)
    expect(
        page.get_by_text("Felismert vagy betöltött sablon:", exact=False)
    ).to_contain_text("UNAS sablon · v1")
    expect(page.get_by_text("Hiányzó oszlopok: Unknown_01")).to_be_visible()
    expect(page.get_by_text("Új oszlopok: Unknown_02")).to_be_visible()
    expect(rows.nth(11).get_by_role("combobox")).to_have_value("")
    expect(
        targets_panel.get_by_role("list", name="Paraméter: Termékszín hozzárendelései")
    ).to_contain_text("Color")
    page.get_by_role("button", name="Sablon mentése", exact=True).click()
    expect(page.get_by_text("Sablon mentve: UNAS sablon · v2")).to_be_visible()
    assert state["saves"][-1]["template_id"] == 41
    assert state["saves"][-1]["new_parameters"] == []
    page.get_by_text("Korábban feltöltött fájlok", exact=True).click()
    page.get_by_role("button", name="#11 · korabbi.csv").click()
    expect(
        page.get_by_text("A minták a korábbi fájlelemzésből származnak.")
    ).to_be_visible()
    page.get_by_text("Mentett sablonok és verziók", exact=True).click()
    expect(page.get_by_text("Korábbi profil · v2")).to_be_visible()
    page.get_by_role("button", name="Verziók", exact=True).click()
    page.get_by_role("button", name="UNAS sablon · v1 betöltése").click()
    expect(
        page.get_by_text("Felismert vagy betöltött sablon:", exact=False)
    ).to_contain_text("UNAS sablon · v1")
    assert not any(
        "/approve" in path
        or "/donor-" in path
        or "/enrich" in path
        or method == "DELETE"
        for method, path, _ in state["requests"]
    )
    assert not state["errors"]


def test_read_only_and_unavailable_backend(open_application, chromium):
    page, state = open_application(chromium, 390, write=False)
    page.get_by_label("Webshopmotor").select_option("unas")
    page.get_by_label("Beszállító", exact=True).select_option("1")
    expect(page.get_by_label("CSV, XLS, XLSX vagy XML fájl")).to_have_count(0)
    expect(page.get_by_text("Új beszállító", exact=True)).to_have_count(0)
    page.get_by_text("Korábban feltöltött fájlok", exact=True).click()
    page.get_by_role("button", name="#11 · korabbi.csv").click()
    expect(page.get_by_label("Célmező: 1. SKU")).to_be_disabled()
    expect(page.get_by_role("button", name="Sablon mentése", exact=True)).to_have_count(
        0
    )
    assert not state["saves"] and not state["errors"]
    unavailable, _ = open_application(chromium, 1440, catalog_available=False)
    expect(unavailable.get_by_role("alert")).to_contain_text(
        "A sablonkészítés nem érhető el"
    )
    expect(unavailable.get_by_label("Webshopmotor")).to_be_disabled()
    expect(unavailable.get_by_text("Feldolgozott sorok", exact=True)).to_have_count(0)
