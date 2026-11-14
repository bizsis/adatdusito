"""Exercise the shared response decoder and rendered errors with synthetic responses."""

import mimetypes
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def api_browser(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    compiled = tmp_path_factory.mktemp("api-response")
    subprocess.run(
        [str(root / "frontend/node_modules/.bin/tsc"),
         str(root / "frontend/src/apiResponse.ts"), "--target", "ES2022",
         "--module", "ESNext", "--strict", "--skipLibCheck", "--outDir", str(compiled)],
        check=True,
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None,
            args=["--no-sandbox"],
        )
        yield browser, root / "frontend/dist", compiled / "apiResponse.js"
        browser.close()


def test_response_decoder_contract(api_browser):
    browser, _, helper = api_browser
    page = browser.new_page()
    page.route("http://api.test/**", lambda route: route.fulfill(
        body=helper.read_text() if route.request.url.endswith("/helper.js") else "<html></html>",
        content_type="text/javascript" if route.request.url.endswith("/helper.js") else "text/html",
    ))
    page.goto("http://api.test/")
    result = page.evaluate("""async () => {
      const {readApiResponse, apiErrorMessage} = await import('/helper.js');
      const check = (ok, label) => { if (!ok) throw new Error(label); };
      for (const status of [413, 204]) {
        let read = false;
        try {
          const value = await readApiResponse({status, ok: status === 204,
            json() { read = true; throw new Error('must not read'); }});
          check(status === 204 && value === null, '204 null');
        } catch (error) {
          check(status === 413 && error.message ===
            'Túl nagy fájl, legfeljebb 50 MB tölthető fel.', '413 before parsing');
        }
        check(!read, 'body must not be parsed');
      }
      for (const data of [{items: [1]}, [1, 2], null, 'ok']) {
        const actual = await readApiResponse(new Response(JSON.stringify(data)));
        check(JSON.stringify(actual) === JSON.stringify(data), 'JSON success');
      }
      for (const status of [400, 401, 403, 422, 503]) {
        const data = await readApiResponse(new Response(
          JSON.stringify({error: {message: 'Pontos API-hiba'}}), {status}));
        check(apiErrorMessage(status, data) === 'Pontos API-hiba', 'JSON error preserved');
      }
      for (const body of ['', '<html>proxy</html>', '{broken']) {
        for (const status of [400, 401, 403, 502, 503, 504]) {
          const data = await readApiResponse(new Response(body, {status}));
          check(data === null, 'non-JSON error');
          check(apiErrorMessage(status, data).length > 10, 'Hungarian fallback');
        }
        try {
          await readApiResponse(new Response(body));
          throw new Error('invalid success accepted');
        } catch (error) {
          check(error.message === 'A kiszolgáló válasza nem értelmezhető. Próbáld újra.',
            'invalid success must fail gracefully');
        }
      }
      const aborted = new DOMException('cancelled', 'AbortError');
      try {
        await readApiResponse({status: 200, ok: true, json() { throw aborted; }});
        throw new Error('abort swallowed');
      } catch (error) { check(error === aborted, 'abort identity'); }
      check(apiErrorMessage(400, {error: {message: {internal: 'detail'}}}) ===
        'A művelet sikertelen.', 'non-string details');
      return true;
    }""")
    assert result is True
    page.close()


@pytest.mark.parametrize("status,body,message", [
    (413, "<html>413 Request Entity Too Large</html>", "Túl nagy fájl, legfeljebb 50 MB tölthető fel."),
    (413, '{"error":{"message":"other limit"}}', "Túl nagy fájl, legfeljebb 50 MB tölthető fel."),
    (502, "<html>Bad Gateway</html>", "A szolgáltatás átmenetileg nem érhető el. Próbáld újra később."),
    (503, "", "A szolgáltatás átmenetileg nem érhető el. Próbáld újra később."),
    (504, "{broken", "A kiszolgáló nem válaszolt időben. Próbáld újra később."),
    (401, '{"error":{"message":"Hibás bejelentkezési adatok."}}', "Hibás bejelentkezési adatok."),
])
def test_shared_api_displays_hungarian_errors(api_browser, status, body, message):
    browser, dist, _ = api_browser
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        path = urlparse(route.request.url).path
        if path == "/api/v1/auth/login":
            route.fulfill(status=status, body=body, content_type="text/html")
        elif path == "/api/v1/auth/me":
            route.fulfill(status=401, json={"error": {"message": "Bejelentkezés szükséges."}})
        elif path.startswith("/api/"):
            route.fulfill(json={"password": True, "google": False, "passkey": False,
                                "registration": False, "branding": {
                                    "display_name": "Adatdúsító", "system_name": "Paksi Informatika"}})
        else:
            file = dist / (path.lstrip("/") or "index.html")
            route.fulfill(body=file.read_bytes(),
                          content_type=mimetypes.guess_type(file.name)[0] or "text/plain")

    page.route("http://api.test/**", route_request)
    page.goto("http://api.test/")
    page.get_by_label("Felhasználónév vagy e-mail-cím", exact=True).fill("test")
    page.get_by_label("Jelszó", exact=True).fill("test-password")
    page.get_by_role("button", name="Bejelentkezés →", exact=True).click()
    expect(page.get_by_text(message, exact=True)).to_be_visible()
    assert not errors
    page.close()
