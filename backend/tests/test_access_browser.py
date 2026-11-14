"""Actual responsive UI, actual RBAC API and actual token acceptance."""

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import sync_playwright, expect
from app import invitations
from conftest import login


def browser_page(p, client, width, height, origin="http://access.test"):
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    browser = p.chromium.launch(
        executable_path="/usr/bin/chromium"
        if Path("/usr/bin/chromium").exists()
        else None,
        args=["--no-sandbox"],
    )
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    paths = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(request):
        u = urlparse(request.request.url)
        paths.append(u.path)
        if u.path.startswith("/api/"):
            headers = {
                "Content-Type": request.request.headers.get(
                    "content-type", "application/json"
                )
            }
            if "x-csrf-token" in request.request.headers:
                headers["X-CSRF-Token"] = request.request.headers["x-csrf-token"]
            r = client.request(
                request.request.method,
                u.path + ("?" + u.query if u.query else ""),
                content=request.request.post_data_buffer,
                headers=headers,
            )
            request.fulfill(
                status=r.status_code,
                body=r.content,
                content_type=r.headers.get("content-type", "application/json"),
            )
        else:
            f = (dist / (u.path.lstrip("/") or "index.html")).resolve()
            assert f.is_relative_to(dist.resolve())
            request.fulfill(
                body=f.read_bytes(),
                content_type=mimetypes.guess_type(f.name)[0] or "text/plain",
            )

    page.route(origin + "/**", route)
    return browser, page, errors, paths


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_superadmin_workspace_role_and_member_editor(environment, width, height):
    client, *_ = environment
    login(client)
    with sync_playwright() as p:
        browser, page, errors, _ = browser_page(p, client, width, height)
        page.goto("http://access.test/")
        picker = page.get_by_label("Munkaterület", exact=True)
        expect(picker.locator("option")).to_have_text(
            ["Rendszerszint", "Első ügyfél", "Második ügyfél"]
        )
        page.get_by_label("Munkaterület keresése", exact=True).fill("Második")
        expect(picker.locator("option")).to_have_text(
            ["Rendszerszint", "Második ügyfél"]
        )
        picker.select_option(label="Második ügyfél")
        expect(page.get_by_label("Munkaterület", exact=True)).to_have_value("2")
        page.get_by_label("Munkaterület", exact=True).select_option(label="Első ügyfél")
        page.get_by_role("navigation").get_by_role(
            "button", name="Munkatársak és hozzáférések", exact=True
        ).click()
        expect(
            page.get_by_role("heading", name="Munkatársak és hozzáférések", level=2)
        ).to_be_visible()
        page.get_by_role("button", name="Szerepkörök", exact=True).click()
        page.get_by_role("button", name="Új szerepkör", exact=True).click()
        page.get_by_label("Szerepkör neve", exact=True).fill("Böngészős ellenőr")
        page.get_by_label("Szerepkör technikai kódja").fill("browser_review")
        page.get_by_label("Import – Megtekintés", exact=True).check()
        page.get_by_label("Referenciák – Megtekintés", exact=True).check()
        page.get_by_role("button", name="Szerepkör mentése", exact=True).click()
        expect(
            page.get_by_role("button", name="Megnyitás: Böngészős ellenőr", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Munkatársak", exact=True).click()
        page.get_by_role("button", name="Hozzáférések: Feldolgozó", exact=True).click()
        page.get_by_label("Adatfeldolgozó", exact=True).uncheck()
        page.get_by_label("Böngészős ellenőr", exact=True).check()
        page.get_by_text("Egyedi engedélyek és tiltások", exact=True).click()
        page.get_by_label("Kivétel: imports.read", exact=True).select_option("deny")
        page.get_by_role("button", name="Hozzáférések mentése", exact=True).click()
        expect(page.get_by_text(re.compile("Hozzáférések mentve"))).to_be_visible()
        expect(
            page.get_by_text(re.compile("Import – Megtekintés: Tiltott"))
        ).to_be_visible()
        page.get_by_label("Munkaterület", exact=True).select_option("")
        page.get_by_role("navigation").get_by_role(
            "button", name="Rendszerhozzáférések", exact=True
        ).click()
        expect(page.get_by_text("processor@example.hu", exact=True)).to_have_count(0)
        page.get_by_role("button", name="Szerepkörök", exact=True).click()
        page.get_by_role("button", name="Új szerepkör", exact=True).click()
        page.get_by_label("Szerepkör neve", exact=True).fill(
            "Böngészős rendszerellenőr"
        )
        page.get_by_label("Szerepkör technikai kódja").fill("browser_system_auditor")
        page.get_by_label("Rendszerbeállítások – Megtekintés", exact=True).check()
        page.get_by_label("Rendszeraudit – Megtekintés", exact=True).check()
        page.get_by_role("button", name="Szerepkör mentése", exact=True).click()
        expect(
            page.get_by_role(
                "button", name="Megnyitás: Böngészős rendszerellenőr", exact=True
            )
        ).to_be_visible()
        page.get_by_role("button", name="Rendszerfelhasználók", exact=True).click()
        page.get_by_label(
            "Név/e-mail keresése (3 karaktertől globális adminisztrátori keresés)"
        ).fill("processor")
        page.get_by_role("button", name="Hozzáférések: Feldolgozó", exact=True).click()
        page.get_by_label("Böngészős rendszerellenőr", exact=True).check()
        page.get_by_role("button", name="Hozzáférések mentése", exact=True).click()
        expect(page.get_by_text(re.compile("Hozzáférések mentve"))).to_be_visible()
        assert not errors
        browser.close()
    login(client, "processor@example.hu")
    assert client.get("/api/v1/auth/me").json()["workspaces"] == []
    assert client.get("/api/v1/settings").status_code == 200
    assert (
        client.put("/api/v1/settings/display_name", json={"value": "No"}).status_code
        == 403
    )


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_invitation_owner_sets_password_and_logs_in(
    environment, monkeypatch, width, height
):
    client, *_ = environment
    sent = []
    monkeypatch.setattr(
        invitations, "send_email", lambda email, token, workspace: sent.append(token)
    )
    login(client, "admin@example.hu")
    with sync_playwright() as p:
        browser, page, errors, paths = browser_page(p, client, width, height)
        page.goto("http://access.test/")
        page.get_by_role("navigation").get_by_role(
            "button", name="Munkatársak és hozzáférések", exact=True
        ).click()
        page.get_by_role("button", name="Meghívások", exact=True).click()
        page.get_by_label("Meghívott e-mail-címe").fill("browser-invite@example.hu")
        page.get_by_label("Adatfeldolgozó", exact=True).check()
        page.get_by_role("button", name="Meghívás küldése", exact=True).click()
        expect(page.get_by_text(re.compile("Meghívás elküldve"))).to_be_visible()
        assert len(sent) == 1
        page.goto("http://access.test/#invite=" + sent[0])
        expect(
            page.get_by_role("heading", name="Adatdúsító – meghívás elfogadása")
        ).to_be_visible()
        page.get_by_label("Neved", exact=True).fill("Meghívott Munkatárs")
        page.get_by_label("Saját jelszó", exact=True).fill("Own-browser-password!")
        page.get_by_role("button", name="Meghívás elfogadása", exact=True).click()
        expect(
            page.get_by_text("A meghívást elfogadtad. A tagság aktív.", exact=True)
        ).to_be_visible()
        page.get_by_role(
            "button", name="Tovább a bejelentkezéshez / munkaterülethez", exact=True
        ).click()
        page.get_by_label("Felhasználónév vagy e-mail-cím").fill(
            "browser-invite@example.hu"
        )
        page.locator("input[type=password]").fill("Own-browser-password!")
        page.get_by_role("button", name="Bejelentkezés →", exact=True).click()
        expect(page.get_by_label("Munkaterület", exact=True)).to_have_value("1")
        expect(
            page.get_by_role("navigation").get_by_role(
                "button", name="Beszállítói import", exact=True
            )
        ).to_be_visible()
        assert not errors and not any(sent[0] in path for path in paths)
        browser.close()
