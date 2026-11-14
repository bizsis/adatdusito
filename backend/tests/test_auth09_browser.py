"""Real responsive UI and virtual platform authenticator against the actual API."""

import pytest
import pyotp
from playwright.sync_api import sync_playwright, expect
from conftest import login
from test_auth09 import encryption_key  # noqa: F401
from test_access_browser import browser_page


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_cloud_teal_help_settings_and_real_passkey_flow(environment, width, height):
    c, *_ = environment
    login(c)
    with sync_playwright() as p:
        browser, page, errors, _ = browser_page(
            p, c, width, height, origin="https://testserver"
        )
        cdp = page.context.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )
        page.goto("https://testserver/")
        expect(page.get_by_label("Munkaterület", exact=True)).to_be_visible()
        assert (
            page.locator(".sidebar").evaluate("e=>getComputedStyle(e).backgroundColor")
            == "rgb(255, 255, 255)"
        )
        page.get_by_role("navigation").get_by_role(
            "button", name="Rendszerhozzáférések", exact=True
        ).click()
        page.get_by_role("button", name="Szerepkörök", exact=True).click()
        expect(page.locator(".role-table th")).to_have_text(
            ["Szerepkör neve", "Típusa", "Felhasználók", "Állapot", "Műveletek"]
        )
        expect(
            page.locator(".permission-matrix table").first.locator("th")
        ).to_have_text(["Jogosultság neve", "Engedély", "Leírás"])
        row = page.locator(".permission-matrix tbody tr").filter(
            has=page.get_by_label("Import – Megtekintés", exact=True)
        )
        expect(row.locator("td").nth(1).locator("input[type=checkbox]")).to_have_count(
            1
        )
        expect(row.locator("td").nth(2)).to_contain_text("Beszállítók")
        summary = page.locator("h2 .help summary").first
        summary.focus()
        summary.press("Enter")
        expect(page.locator("h2 .help[open] [role=note]").first).to_be_visible()
        summary.press("Escape")
        expect(page.locator("h2 .help[open]")).to_have_count(0)
        page.get_by_role("navigation").get_by_role(
            "button", name="Rendszerbeállítások", exact=True
        ).click()
        expect(page.get_by_role("tablist")).to_be_visible()
        page.get_by_label("Alkalmazás megjelenített neve", exact=True).fill(
            "Cloud teszt"
        )
        page.get_by_role(
            "button", name="Általános beállítások mentése", exact=True
        ).click()
        expect(page.locator(".brand")).to_contain_text("Cloud teszt")
        page.get_by_role("tab", name="Hitelesítés és bejelentkezés", exact=True).click()
        page.get_by_label("Passkey / WebAuthn", exact=True).check()
        page.get_by_role(
            "button", name="Hitelesítési módok mentése", exact=True
        ).click()
        expect(page.get_by_role("status")).to_contain_text("mentve")
        page.get_by_role("button", name="Biztonság", exact=True).click()
        page.get_by_label("Eszköz megnevezése", exact=True).fill("Virtuális eszköz")
        page.get_by_role("button", name="Passkey hozzáadása", exact=True).click()
        expect(page.get_by_text("Passkey regisztrálva.", exact=True)).to_be_visible(
            timeout=20000
        )
        expect(page.get_by_text("Virtuális eszköz", exact=True)).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(path=f"/tmp/codex09-security-{width}.png", full_page=True)
        page.get_by_role("button", name="Kilépés", exact=True).click()
        page.get_by_role("button", name="Bejelentkezés passkeyjel", exact=True).click()
        expect(page.get_by_label("Munkaterület", exact=True)).to_be_visible(
            timeout=20000
        )
        assert not errors, errors
        browser.close()


def test_totp_qr_enrollment_and_recovery_login_from_ui(environment):
    c, *_ = environment
    login(c)
    with sync_playwright() as p:
        browser, page, errors, _ = browser_page(p, c, 1440, 1000)
        page.goto("http://access.test/")
        page.get_by_role("button", name="Biztonság", exact=True).click()
        page.get_by_role("button", name="TOTP beállítása", exact=True).click()
        expect(page.get_by_alt_text("TOTP aktiválási QR-kód")).to_be_visible()
        secret = page.get_by_label("TOTP manuális kulcs").inner_text()
        page.get_by_label("Aktiválási ellenőrzőkód", exact=True).fill(
            pyotp.TOTP(secret).now()
        )
        page.get_by_role("button", name="TOTP aktiválása", exact=True).click()
        expect(page.get_by_label("Helyreállítási kódok", exact=True)).to_be_visible()
        codes = (
            page.get_by_label("Helyreállítási kódok", exact=True)
            .input_value()
            .splitlines()
        )
        assert len(codes) == 10
        page.get_by_role("button", name="Kilépés", exact=True).click()
        page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True).fill(
            "root@example.hu"
        )
        page.get_by_label("Jelszó", exact=True).fill("Test-password-2026!")
        page.get_by_role("button", name="Bejelentkezés →", exact=True).click()
        page.get_by_label("Hitelesítőkód vagy helyreállítási kód", exact=True).fill(
            codes[0]
        )
        page.get_by_role(
            "button", name="Második faktor ellenőrzése", exact=True
        ).click()
        expect(page.get_by_label("Munkaterület", exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()


def test_smtp_web_editor_saves_redacted_secret_and_sends_test_message(
    environment, monkeypatch
):
    from app import mail_service

    c, *_ = environment
    login(c)
    sent = []

    class SMTP:
        def send_message(self, message):
            sent.append(message)
            return {}

        def quit(self):
            pass

    monkeypatch.setattr(mail_service, "connect", lambda cfg, web=True: SMTP())
    with sync_playwright() as p:
        browser, page, errors, _ = browser_page(p, c, 1440, 1000)
        page.goto("http://access.test/")
        page.get_by_role("navigation").get_by_role(
            "button", name="Rendszerbeállítások", exact=True
        ).click()
        page.get_by_role("tab", name="SMTP / Levelezés", exact=True).click()
        page.get_by_label("SMTP-kiszolgáló", exact=True).fill("smtp.example.hu")
        page.get_by_label("Port", exact=True).fill("465")
        page.get_by_label("Titkosítás", exact=True).select_option("tls")
        page.get_by_label("SMTP-felhasználónév", exact=True).fill("sender")
        page.get_by_label("SMTP-jelszó", exact=True).fill("synthetic-test-secret")
        page.get_by_label("Feladó e-mail-címe", exact=True).fill("sender@example.hu")
        page.get_by_role(
            "button", name="SMTP ellenőrzése és mentése", exact=True
        ).click()
        expect(page.get_by_role("status")).to_contain_text("mentve")
        expect(page.get_by_label("SMTP-jelszó", exact=True)).to_have_value("")
        page.get_by_label("Tesztlevél címzettje", exact=True).fill(
            "recipient@example.hu"
        )
        page.get_by_role("button", name="Tesztlevél küldése", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text(
            "postaládába érkezés nem igazolt"
        )
        assert len(sent) == 1 and not errors
        browser.close()
