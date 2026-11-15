"""Real frontend + real CATEGORY-02A API; skipped until dependency PR #18 lands.

Fixture databases are isolated SQLite. Never contacts a VPS or reference server.
"""
import importlib.util
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('category02_backend_fixtures', ROOT / 'backend/tests/conftest.py')
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
password_hash = _fixtures.password_hash
extra_reference_categories = _fixtures.extra_reference_categories
extra_reference_parameters = _fixtures.extra_reference_parameters
extra_reference_values = _fixtures.extra_reference_values
environment = _fixtures.environment
pytestmark = pytest.mark.skipif(importlib.util.find_spec('app.product_catalog') is None, reason='Requires CATEGORY-02A backend PR #18 (8c5db11); no invented fallback API.')


def import_rows(client, engine, supplier):
    from app.import_engine import advance
    from sqlalchemy.orm import Session
    content = 'SKU;NAME;CATEGORY;Teljesítmény (W)\n001;Mosógép Alpha;Saját / Gépek;2100\n002;Mosógép Beta;Saját / Gépek;2200\n'.encode()
    r = client.post('/api/v1/imports/runs', data={'supplier_id': str(supplier)}, files={'file': ('products.csv', content)})
    assert r.status_code == 200, r.text
    run = r.json()['id']
    with Session(engine) as db:
        advance(db, run)
    r = client.post(f'/api/v1/imports/runs/{run}/approve', json={'name': 'Teszt profil', 'mapping': {'0': 'sku', '1': 'name', '2': 'category'}, 'identity_field': 'sku'})
    assert r.status_code == 200, r.text
    with Session(engine) as db:
        advance(db, run)
    assert client.get(f'/api/v1/imports/runs/{run}').json()['state'] == 'completed'


@pytest.mark.parametrize('width', [390, 1440])
def test_real_api_manual_map_inheritance_lock_and_settings(environment, monkeypatch, width):
    from app import import_api
    c, engine, _, reference_statements = environment
    monkeypatch.setattr(import_api, 'enqueue', lambda _: None)
    _fixtures.login(c, 'admin@example.hu')
    supplier = c.post('/api/v1/imports/suppliers', json={'name': 'API teszt beszállító'}).json()['id']
    import_rows(c, engine, supplier)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))

        def route(request):
            u = urlparse(request.request.url)
            if u.path.startswith('/api/'):
                headers = {'Content-Type': request.request.headers.get('content-type', 'application/json')}
                if 'x-csrf-token' in request.request.headers:
                    headers['X-CSRF-Token'] = request.request.headers['x-csrf-token']
                response = c.request(request.request.method, u.path + ('?' + u.query if u.query else ''), content=request.request.post_data_buffer, headers=headers)
                request.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type', 'application/json'))
            else:
                dist = ROOT / 'frontend/dist'
                f = (dist / (u.path.lstrip('/') or 'index.html')).resolve()
                assert f.is_relative_to(dist.resolve())
                request.fulfill(body=f.read_bytes(), content_type=mimetypes.guess_type(f.name)[0] or 'text/plain')

        page.route('http://category-api.test/**', route)
        page.goto('http://category-api.test/')
        page.get_by_role('navigation').get_by_role('button', name='Termékadatok', exact=True).click()
        with page.expect_response(lambda r: urlparse(r.url).path.endswith('/workspace/products') and parse_qs(urlparse(r.url).query).get('q') == ['Alpha']):
            page.get_by_label('Termék keresése', exact=True).fill('Alpha')
        expect(page.get_by_role('button', name='Mosógép Beta részletei', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='Mosógép Alpha részletei', exact=True)).to_be_visible()
        with page.expect_response(lambda r: urlparse(r.url).path.endswith('/workspace/products') and 'q' not in parse_qs(urlparse(r.url).query)):
            page.get_by_label('Termék keresése', exact=True).fill('')
        expect(page.get_by_role('button', name='Mosógép Beta részletei', exact=True)).to_be_visible()
        page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
        expect(page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_be_visible()
        page.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()
        page.get_by_label('Kategória keresése', exact=True).fill('Elöltöltős mosógépek')
        page.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek', exact=True).click()
        page.get_by_label('Módosítás indoka', exact=True).fill('Valódi API kézi teszt')
        page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        page.get_by_role('button', name='Módosítás mentése', exact=True).click()
        expect(page.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_be_visible()
        rows = c.get('/api/v1/workspace/products').json()['items']
        alpha = next(i for i in rows if i['fields']['sku'] == '001')
        assert alpha['classification']['locked'] and alpha['classification']['donor_emag_category_id'] == 385
        assert alpha['source_category']['path'] == 'Saját / Gépek'
        saved_revision = alpha['revision']
        page.get_by_role('tab', name='Saját kategóriatérkép és profilok').click()
        page.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        page.get_by_label('Kategória keresése', exact=True).fill('Elöltöltős mosógépek')
        page.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek', exact=True).click()
        page.get_by_label('Módosítás indoka', exact=True).fill('Valódi térkép öröklődés')
        page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        page.get_by_role('button', name='Kategóriatérkép jóváhagyása', exact=True).click()
        expect(page.get_by_text('Kategóriatérkép mentve. Újrabesorolt termékek: 1; védett, kihagyott: 1.', exact=True)).to_be_visible()
        rows = c.get('/api/v1/workspace/products').json()['items']
        assert all(i['classification']['status'] == 'auto_classified' for i in rows)
        alpha = next(i for i in rows if i['fields']['sku'] == '001')
        assert alpha['revision'] == saved_revision and alpha['classification']['locked']
        # Reimport must preserve both original values and a manual classification lock.
        import_rows(c, engine, supplier)
        alpha = c.get(f"/api/v1/workspace/products/{alpha['id']}").json()
        assert alpha['classification']['locked'] and alpha['classification']['donor_emag_category_id'] == 385
        assert any(e['kind'] == 'classification_manual' for e in alpha['events'])
        assert any(a['raw'] == '2100' for a in alpha['source_attributes'])
        # A concurrent real API write invalidates the open preview without retry.
        page.get_by_role('tab', name='Terméklista', exact=True).click()
        page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
        page.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()
        page.get_by_label('Művelet', exact=True).select_option('reset')
        page.get_by_label('Módosítás indoka', exact=True).fill('Védelem feloldása')
        page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        expect(page.get_by_role('heading', name='Előnézet', exact=True)).to_be_visible()
        latest = c.get(f"/api/v1/workspace/products/{alpha['id']}").json()
        other = c.patch(f"/api/v1/workspace/products/{alpha['id']}/classification", json={'expected_revision': latest['revision'], 'action': 'set', 'navigation_node_id': 'web-item-114-3490', 'reason': 'Másik admin közben javított'})
        assert other.status_code == 200, other.text
        page.get_by_role('button', name='Módosítás mentése', exact=True).click()
        expect(page.get_by_role('button', name='Friss adatok betöltése', exact=True)).to_be_visible()
        page.get_by_role('button', name='Friss adatok betöltése', exact=True).click()
        assert c.get(f"/api/v1/workspace/products/{alpha['id']}").json()['classification']['locked']
        page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
        page.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()
        page.get_by_label('Művelet', exact=True).select_option('reset')
        page.get_by_label('Módosítás indoka', exact=True).fill('Automatikus besorolás visszaállítása')
        page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        page.get_by_role('button', name='Módosítás mentése', exact=True).click()
        expect(page.get_by_text('A kézi védelem feloldva, az automatikus besorolás frissült.', exact=True)).to_be_visible()
        after_reset = c.get(f"/api/v1/workspace/products/{alpha['id']}").json()
        assert not after_reset['classification']['locked']
        assert after_reset['classification']['origin'] == 'category_map'
        # Existing settings/auth transport supplies the threshold; no frontend default.
        _fixtures.login(c)
        page.reload()
        page.get_by_role('navigation').get_by_role('button', name='Rendszerbeállítások', exact=True).click()
        page.get_by_role('tab', name='Kategóriabesorolás', exact=True).click()
        expect(page.get_by_label('Kategória-besorolási admin küszöb (%)', exact=True)).to_have_value('98')
        page.get_by_label('Kategória-besorolási admin küszöb (%)', exact=True).fill('97')
        page.get_by_role('button', name='Besorolási küszöb mentése', exact=True).click()
        expect(page.get_by_text('A beállítások mentve, újraindítás nélkül érvényesek.', exact=True)).to_be_visible()
        assert c.get('/api/v1/system/settings').json()['classification']['auto_threshold'] == .97
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        assert all(not s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP')) for s in reference_statements)
        browser.close()
