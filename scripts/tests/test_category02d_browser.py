"""CATEGORY-02D: actual merged PR APIs and DOM; explicit transport faults are labelled.

Only isolated fixture SQLite is written. The large stock is test data, not a new
import, and every normal response is produced by the real FastAPI application.
"""
from contextlib import contextmanager
from datetime import timedelta
import json
import mimetypes
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session
from app import import_api, product_catalog as pc
from app.import_engine import advance
from app.import_models import SupplierProduct
from app.models import LoginSession, Membership, now
from app.access_models import PermissionException
from app.product_models import ProductSourceCategory
from test_classification_api_integration_browser import (
    _fixtures, environment, password_hash, extra_reference_categories,
    extra_reference_parameters, extra_reference_values,
)

ROOT = Path(__file__).resolve().parents[2]
WASHER = 'web-item-114-3490'


@pytest.fixture
def catalog(environment, monkeypatch):
    c, engine, _, statements = environment
    monkeypatch.setattr(import_api, 'enqueue', lambda _: None)
    _fixtures.login(c, 'admin@example.hu')
    supplier = c.post('/api/v1/imports/suppliers', json={'name': 'CATEGORY-02D beszállító'}).json()['id']
    feed = 'SKU;NAME;CATEGORY;EAN\n001;Mosógép Alpha;Saját / Gépek;5901234123457\n002;Mosógép Beta;Saját / Gépek;4006381333931\n'.encode()
    r = c.post('/api/v1/imports/runs', data={'supplier_id': str(supplier)}, files={'file': ('category02d.csv', feed)})
    assert r.status_code == 200, r.text
    run = r.json()['id']
    with Session(engine) as db:
        advance(db, run)
    r = c.post(f'/api/v1/imports/runs/{run}/approve', json={'name': 'CATEGORY-02D', 'mapping': {'0': 'sku', '1': 'name', '2': 'category', '3': 'gtin'}, 'identity_field': 'sku'})
    assert r.status_code == 200, r.text
    with Session(engine) as db:
        advance(db, run)
    assert c.get(f'/api/v1/imports/runs/{run}').json()['state'] == 'completed'
    rows = c.get('/api/v1/workspace/products').json()['items']
    return SimpleNamespace(client=c, engine=engine, supplier=supplier, run=run, rows=rows, statements=statements)


@contextmanager
def app_browser(catalog, width=1440, fault=None, *, legacy_import=False):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        calls, errors = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(request):
            u = urlparse(request.request.url)
            if not u.path.startswith('/api/'):
                f = (ROOT / 'frontend/dist' / (u.path.lstrip('/') or 'index.html')).resolve()
                assert f.is_relative_to((ROOT / 'frontend/dist').resolve())
                request.fulfill(body=f.read_bytes(), content_type=mimetypes.guess_type(f.name)[0] or 'text/plain')
                return
            if legacy_import and u.path == '/api/v1/imports/engines/unas/registry':
                request.fulfill(status=404, json={'detail': 'Not Found'})
                return
            headers = {'Content-Type': request.request.headers.get('content-type', 'application/json')}
            if 'x-csrf-token' in request.request.headers:
                headers['X-CSRF-Token'] = request.request.headers['x-csrf-token']
            response = catalog.client.request(request.request.method, u.path + ('?' + u.query if u.query else ''), content=request.request.post_data_buffer, headers=headers)
            call = {'path': u.path, 'query': parse_qs(u.query), 'method': request.request.method, 'status': response.status_code, 'bytes': len(response.content), 'json': None}
            try:
                call['json'] = response.json()
            except ValueError:
                pass
            calls.append(call)
            if fault and fault(request, response, call):
                call['transport_fault'] = True
                return
            request.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type', 'application/json'))
        page.route('http://category02d.test/**', route)
        page.goto('http://category02d.test/')
        yield SimpleNamespace(page=page, calls=calls)
        assert not errors
        assert all(not s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP')) for s in catalog.statements)
        browser.close()


def products(ui):
    ui.page.get_by_role('navigation').get_by_role('button', name='Termékadatok', exact=True).click()


def edit(ui):
    p = ui.page
    p.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
    p.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()


def inspect(p, category='Elöltöltős mosógépek'):
    p.get_by_label('Kategória keresése', exact=True).fill(category)
    p.get_by_role('button', name=f'Kiválasztás: {category}', exact=True).click()
    p.get_by_label('Módosítás indoka', exact=True).fill('CATEGORY-02D ellenőrzött döntés')
    p.get_by_role('button', name='Módosítások előnézete', exact=True).click()
    expect(p.get_by_role('region', name='Módosítás előnézete', exact=True)).to_be_visible()


@pytest.mark.parametrize('query,expected_sku', [('Alpha','001'), ('001','001'), ('5901234123457','001'), ('4006381333931','002')])
def test_real_name_sku_ean_search_and_counts(catalog, query, expected_sku):
    with app_browser(catalog) as ui:
        products(ui)
        with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('q') == [query]):
            ui.page.get_by_label('Termék keresése', exact=True).fill(query)
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(1)
        expect(ui.page.locator('.classification-products')).to_contain_text(expected_sku)
        call = [c for c in ui.calls if c['query'].get('q') == [query]][-1]
        assert call['status'] == 200 and call['json']['status_counts'] == {'auto_classified': 0, 'needs_review': 1}
        assert call['json']['next_cursor'] is None
        ui.page.get_by_label('Besorolási státusz', exact=True).select_option('assigned')
        expect(ui.page.get_by_text('Nincs a szűrésnek megfelelő termék.', exact=True)).to_be_visible()
        call = [c for c in ui.calls if c['query'].get('status') == ['auto_classified']][-1]
        assert call['json']['status_counts'] == {'auto_classified': 0, 'needs_review': 1}


def test_real_457_categories_paginated_without_changing_fixed_tree(catalog):
    snapshot = {k: (n['path'][:], n['path_ids'][:]) for k, n in pc.internal_categories().items()}
    assert len(snapshot) == 457
    from app.curated_taxonomy import specification
    expected_roots = [r['name'] for r in specification()['roots']]
    roots = catalog.client.get('/api/v1/reference/navigation', params={'scope': 'tree'}).json()
    assert [r['name'] for r in roots['items']] == expected_roots
    assert len(expected_roots) == 13
    with app_browser(catalog, width=390) as ui:
        products(ui); edit(ui)
        for index in range(5):
            expect(ui.page.locator('.classification-choices > li')).to_have_count(57 if index == 4 else 100)
            if index < 4:
                with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('offset') == [str((index + 1) * 100)]):
                    ui.page.get_by_role('button', name='Következő kategóriák', exact=True).click()
        expect(ui.page.get_by_role('button', name='Következő kategóriák', exact=True)).to_be_disabled()
        served = [c['json'] for c in ui.calls if c['path'].endswith('/internal-categories')]
        assert all(v['total'] == 457 for v in served)
        assert {n['navigation_node_id'] for v in served for n in v['items']} == set(snapshot)
        assert len({path[0] for path, _ in snapshot.values()}) == 13
        assert not any(c['method'] in ('PATCH','PUT','DELETE') for c in ui.calls)
    assert snapshot == {k: (n['path'][:], n['path_ids'][:]) for k, n in pc.internal_categories().items()}


def test_real_multiple_donors_are_explicit_and_not_enrichment_approval(catalog):
    node = pc.internal_categories()['web-item-1-4246']
    assert len(node['donors']) == 2
    with app_browser(catalog) as ui:
        products(ui); edit(ui)
        p = ui.page
        p.get_by_label('Kategória keresése', exact=True).fill('Töltőkábelek')
        p.get_by_role('button', name='Kiválasztás: Töltőkábelek', exact=True).click()
        profile = p.get_by_label('Paraméterprofil', exact=True)
        expect(profile.locator('option')).to_have_count(3)
        profile.select_option(str(node['donors'][1]['emag_category_id']))
        p.get_by_label('Módosítás indoka', exact=True).fill('Külön kiválasztott donorprofil')
        p.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        expect(p.get_by_role('region', name='Módosítás előnézete')).to_contain_text(node['donors'][1]['name'])
        expect(p.get_by_text('A kategória kiválasztása nem jelenti', exact=False)).to_be_visible()
        p.get_by_role('button', name='Módosítás mentése', exact=True).click()
        expect(p.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_be_visible()
        detail = catalog.client.get(f"/api/v1/workspace/products/{catalog.rows[0]['id']}").json()
        assert detail['classification']['donor_emag_category_id'] == node['donors'][1]['emag_category_id']
        assert detail['source_category']['path'] == 'Saját / Gépek'


def test_real_mapping_pagination_save_preview_delete_and_exit(catalog):
    with catalog.engine.begin() as db:
        db.execute(insert(ProductSourceCategory), [dict(tenant_id=1, supplier_id=catalog.supplier, path_key=f'extra-{i}', path_text=f'Lapozott kategória {i:03}') for i in range(52)])
    with app_browser(catalog) as ui:
        products(ui); p = ui.page
        p.get_by_role('tab', name='Saját kategóriatérkép és profilok').click()
        expect(p.locator('.classification-mappings > li')).to_have_count(50)
        p.get_by_role('button', name='Következő kategóriatérképek', exact=True).click()
        expect(p.locator('.classification-mappings > li')).to_have_count(3)
        p.get_by_role('button', name='Előző kategóriatérképek', exact=True).click()
        p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        inspect(p)
        region = p.get_by_role('region', name='Módosítás előnézete')
        expect(region).to_contain_text('Helyi módosítás-összesítő, nem szerveroldali próbafuttatás')
        expect(region).to_contain_text('Mentéskor derül ki')
        assert not any(c['method'] == 'PUT' for c in ui.calls)
        p.get_by_role('button', name='Mégse', exact=True).click()
        expect(region).to_have_count(0)
        assert not any(c['method'] == 'PUT' for c in ui.calls)
        p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        inspect(p)
        p.get_by_role('button', name='Kategóriatérkép jóváhagyása', exact=True).click()
        expect(p.get_by_text('Kategóriatérkép mentve. Újrabesorolt termékek: 2; védett, kihagyott: 0.', exact=True)).to_be_visible()
        p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        p.get_by_label('Művelet', exact=True).select_option('reset')
        p.get_by_label('Módosítás indoka', exact=True).fill('Térkép visszavonása')
        p.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        p.get_by_role('button', name='Kategóriatérkép törlése', exact=True).click()
        expect(p.get_by_text('Kategóriatérkép törölve. Újrabesorolt termékek: 2; védett, kihagyott: 0.', exact=True)).to_be_visible()
        assert any(c['method'] == 'DELETE' and c['status'] == 200 and c['query'].get('expected_revision') == ['1'] for c in ui.calls)
        maps = catalog.client.get('/api/v1/workspace/category-maps').json()['items']
        assert maps[0]['map'] is None
        assert all(i['classification']['status'] == 'needs_review' for i in catalog.client.get('/api/v1/workspace/products').json()['items'])


def test_real_stock_above_50000_is_paged_not_truncated(catalog):
    old = catalog.rows[0]
    with catalog.engine.begin() as db:
        for start in range(0, 50001, 1000):
            batch = []
            for i in range(start, min(start + 1000, 50001)):
                data = {'sku': f'bulk-{i:05}', 'name': f'Tárolt termék {i:05}'}
                batch.append(dict(tenant_id=1, supplier_id=catalog.supplier, identity_key=f'bulk-{i}', data=data, last_run_id=catalog.run, last_line=i+2, source_category_id=old['source_category']['id'], search_text=pc.search_text(data)))
            db.execute(insert(SupplierProduct), batch)
    with app_browser(catalog) as ui:
        products(ui)
        expect(ui.page.get_by_text('Szűrt találatok: 50\u00a0003', exact=True)).to_be_visible()
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(25)
        first = next(c for c in ui.calls if c['path'].endswith('/workspace/products'))
        with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('cursor') == [str(first['json']['next_cursor'])]):
            ui.page.get_by_role('button', name='Következő termékek', exact=True).click()
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(25)
        second = [c for c in ui.calls if c['path'].endswith('/workspace/products')][-1]
        assert set(i['id'] for i in first['json']['items']).isdisjoint(i['id'] for i in second['json']['items'])
        assert second['json']['status_counts']['needs_review'] == 50003
        assert max(c['bytes'] for c in ui.calls if c['path'].endswith('/workspace/products')) < 100000
        with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('q') == ['bulk-50000']):
            ui.page.get_by_label('Termék keresése', exact=True).fill('bulk-50000')
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(1)
        expect(ui.page.locator('.classification-products')).to_contain_text('bulk-50000')
        assert pc.RUN_PRODUCT_LIMIT == 50000


@pytest.mark.parametrize('status', [403, 404, 409, 422])
def test_real_write_errors_never_claim_success(catalog, monkeypatch, status):
    with app_browser(catalog) as ui:
        products(ui); edit(ui); inspect(ui.page)
        product_id = catalog.rows[0]['id']
        if status == 403:
            with Session(catalog.engine) as db:
                db.add(PermissionException(user_id=2, context='tenant:1', permission='products.classify', allowed=False))
                db.commit()
        elif status == 404:
            # Change only the request's lookup through real tenant context; no fabricated 404 response.
            with Session(catalog.engine) as db:
                db.add(Membership(tenant_id=2, user_id=2, role='tenant_admin'))
                db.execute(update(LoginSession).values(tenant_id=2))
                db.commit()
            assert catalog.client.get('/api/v1/workspace/products').status_code == 200
        elif status == 409:
            detail = catalog.client.get(f'/api/v1/workspace/products/{product_id}').json()
            r = catalog.client.patch(f'/api/v1/workspace/products/{product_id}/classification', json={'action': 'set', 'expected_revision': detail['revision'], 'navigation_node_id': WASHER})
            assert r.status_code == 200
        else:
            original = pc.internal_category
            monkeypatch.setattr(pc, 'internal_category', lambda key: None if key == WASHER else original(key))
        with ui.page.expect_response(lambda r: urlparse(r.url).path.endswith('/classification') and r.request.method == 'PATCH') as result:
            ui.page.get_by_role('button', name='Módosítás mentése', exact=True).click()
        assert result.value.status == status
        expect(ui.page.get_by_role('alert')).to_be_visible()
        expect(ui.page.get_by_role('region', name='Módosítás előnézete')).to_have_count(0)
        expect(ui.page.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_have_count(0)
        assert len([c for c in ui.calls if c['method'] == 'PATCH']) == 1
        if status == 409:
            ui.page.get_by_role('button', name='Friss adatok betöltése', exact=True).click()
            ui.page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
            expect(ui.page.get_by_text('Kézi javítás védett', exact=True).last).to_be_visible()


def test_real_expired_session_401_exits_workspace(catalog):
    with app_browser(catalog) as ui:
        products(ui)
        expect(ui.page.get_by_role('button', name='Mosógép Alpha részletei')).to_be_visible()
        with catalog.engine.begin() as db:
            db.execute(update(LoginSession).values(expires_at=now()-timedelta(days=1)))
        with ui.page.expect_response(lambda r: urlparse(r.url).path.endswith('/workspace/products') and r.status == 401):
            ui.page.get_by_label('Termék keresése', exact=True).fill('Alpha')
        expect(ui.page.get_by_role('button', name='Bejelentkezés →', exact=True)).to_be_visible()
        expect(ui.page.locator('.classification-workspace')).to_have_count(0)


@pytest.mark.parametrize('body', [None, {'items': [], 'next_cursor': None, 'field_labels': {}, 'status_counts': {'auto_classified': -1, 'needs_review': 0}}, {'items': [{}], 'next_cursor': None, 'field_labels': {}, 'status_counts': {'auto_classified': 0, 'needs_review': 1}}])
def test_malformed_bootstrap_is_an_error_and_retry_uses_real_api(catalog, body):
    remaining = [True]
    def fault(route, response, call):
        if remaining and call['path'].endswith('/workspace/products'):
            remaining.clear(); route.fulfill(status=200, json=body); return True
        return False
    with app_browser(catalog, fault=fault) as ui:
        products(ui)
        expect(ui.page.get_by_role('alert')).to_contain_text('nem értelmezhető')
        expect(ui.page.get_by_text('Még nincs feldolgozott termék', exact=False)).to_have_count(0)
        ui.page.get_by_role('button', name='Újrapróbálás', exact=True).click()
        expect(ui.page.get_by_role('button', name='Mosógép Alpha részletei')).to_be_visible()


def test_server_failure_then_fast_search_recovery(catalog):
    remaining = [True]
    def fault(route, response, call):
        if remaining and call['path'].endswith('/workspace/products') and call['query'].get('q') == ['Alpha']:
            remaining.clear(); route.fulfill(status=503, json={'error': {'code': 'unavailable', 'message': 'Átmeneti teszthiba'}}); return True
        return False
    with app_browser(catalog, fault=fault) as ui:
        products(ui)
        with ui.page.expect_response(lambda r: r.status == 503):
            ui.page.get_by_label('Termék keresése', exact=True).fill('Alpha')
        expect(ui.page.get_by_role('alert')).to_contain_text('Átmeneti teszthiba')
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(0)
        ui.page.get_by_role('button', name='Adatok újratöltése', exact=True).click()
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(1)
        with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('q') == ['Beta']):
            ui.page.get_by_label('Termék keresése', exact=True).fill('Al')
            ui.page.get_by_label('Termék keresése', exact=True).fill('Bet')
            ui.page.get_by_label('Termék keresése', exact=True).fill('Beta')
        expect(ui.page.locator('.classification-products')).to_contain_text('Mosógép Beta')
        expect(ui.page.locator('.classification-products')).not_to_contain_text('Mosógép Alpha')
        assert not any(c['query'].get('q') in (['Al'], ['Bet']) for c in ui.calls)


def test_readonly_capability_and_real_tenant_switch_discard_old_context(catalog):
    _fixtures.login(catalog.client, 'processor@example.hu')
    with app_browser(catalog) as ui:
        products(ui)
        ui.page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
        expect(ui.page.get_by_text('Revízió:', exact=False)).to_be_visible()
        expect(ui.page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_have_count(0)
        detail = [c for c in ui.calls if c['path'].endswith(f"/products/{catalog.rows[0]['id']}")][-1]
        assert detail['json']['capabilities'] == {'classify': False}
    _fixtures.login(catalog.client)
    assert catalog.client.post('/api/v1/auth/tenant', json={'tenant_id': 1}).status_code == 200
    with app_browser(catalog) as ui:
        products(ui)
        with ui.page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('q') == ['Alpha']):
            ui.page.get_by_label('Termék keresése', exact=True).fill('Alpha')
        ui.page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
        expect(ui.page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_be_visible()
        with ui.page.expect_response(lambda r: urlparse(r.url).path.endswith('/auth/tenant')):
            ui.page.get_by_label('Munkaterület', exact=True).select_option(label='Második ügyfél')
        products(ui)
        expect(ui.page.get_by_text('Nincs a szűrésnek megfelelő termék.', exact=True)).to_be_visible()
        expect(ui.page.get_by_label('Termék keresése', exact=True)).to_have_value('')
        expect(ui.page.get_by_role('button', name='Mosógép Alpha részletei', exact=True)).to_have_count(0)
        expect(ui.page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_have_count(0)
        assert catalog.client.get(f"/api/v1/workspace/products/{catalog.rows[0]['id']}").status_code == 404
        with ui.page.expect_response(lambda r: urlparse(r.url).path.endswith('/auth/tenant')):
            ui.page.get_by_label('Munkaterület', exact=True).select_option(label='Első ügyfél')
        products(ui)
        expect(ui.page.locator('.classification-products tbody tr')).to_have_count(2)


@pytest.mark.parametrize('where', ['detail', 'choices', 'maps', 'product_write', 'map_write'])
def test_malformed_read_or_committed_write_has_no_false_success(catalog, where):
    remaining = [True]
    def fault(route, response, call):
        path, method = call['path'], call['method']
        match = (where == 'detail' and path.endswith(f"/products/{catalog.rows[0]['id']}") or
                 where == 'choices' and path.endswith('/internal-categories') or
                 where == 'maps' and path.endswith('/category-maps') or
                 where == 'product_write' and method == 'PATCH' or
                 where == 'map_write' and method == 'PUT')
        if remaining and match:
            remaining.clear(); route.fulfill(status=200, json={}); return True
        return False
    with app_browser(catalog, fault=fault) as ui:
        products(ui); p = ui.page
        if where in ('maps','map_write'):
            p.get_by_role('tab', name='Saját kategóriatérkép és profilok').click()
            if where == 'map_write':
                p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
                inspect(p)
                p.get_by_role('button', name='Kategóriatérkép jóváhagyása', exact=True).click()
        else:
            p.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
            if where != 'detail':
                p.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()
                if where == 'product_write':
                    inspect(p)
                    p.get_by_role('button', name='Módosítás mentése', exact=True).click()
        expect(p.get_by_role('alert')).to_contain_text('nem értelmezhető')
        expect(p.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_have_count(0)
        expect(p.get_by_text('Kategóriatérkép mentve.', exact=False)).to_have_count(0)
        if where in ('map_write', 'product_write'):
            # The server committed; corrupting its response must not turn it into
            # a second blind write or a fabricated success. Explicit read recovers.
            assert len([c for c in ui.calls if c['method'] in ('PATCH', 'PUT')]) == 1
            p.get_by_role('button', name='Friss adatok betöltése', exact=True).click()
            if where == 'product_write':
                expect(p.locator('.classification-products').get_by_text('Kézi javítás védett', exact=True)).to_be_visible()
            else:
                expect(p.get_by_text('Jóváhagyott kategóriatérkép', exact=False)).to_be_visible()
        elif where == 'choices':
            p.get_by_label('Kategória keresése', exact=True).fill('Elöltöltős mosógépek')
            expect(p.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek', exact=True)).to_be_visible()
        else:
            p.get_by_role('button', name='Adatok újratöltése', exact=True).click()
            if where == 'maps':
                expect(p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True)).to_be_visible()
            else:
                p.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
                expect(p.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_be_visible()


def test_real_mapping_409_reload_then_explicit_rejection(catalog):
    source_id = catalog.rows[0]['source_category']['id']
    with app_browser(catalog) as ui:
        products(ui); p = ui.page
        p.get_by_role('tab', name='Saját kategóriatérkép és profilok').click()
        p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        inspect(p)
        r = catalog.client.put(f'/api/v1/workspace/category-maps/{source_id}', json={'expected_revision': None, 'state': 'approved', 'navigation_node_id': WASHER})
        assert r.status_code == 200
        with p.expect_response(lambda r: r.request.method == 'PUT' and r.status == 409):
            p.get_by_role('button', name='Kategóriatérkép jóváhagyása', exact=True).click()
        expect(p.get_by_text('Kategóriatérkép mentve.', exact=False)).to_have_count(0)
        p.get_by_role('button', name='Friss adatok betöltése', exact=True).click()
        p.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
        p.get_by_label('Művelet', exact=True).select_option('reject')
        p.get_by_label('Módosítás indoka', exact=True).fill('Térkép visszautasítva felülvizsgálatkor')
        p.get_by_role('button', name='Módosítások előnézete', exact=True).click()
        p.get_by_role('button', name='Kategóriatérkép elutasítása', exact=True).click()
        expect(p.get_by_text('Kategóriatérkép elutasítva. Újrabesorolt termékek: 2; védett, kihagyott: 0.', exact=True)).to_be_visible()
        result = catalog.client.get('/api/v1/workspace/category-maps').json()['items'][0]['map']
        assert result['state'] == 'rejected' and result['revision'] == 2
        assert result['navigation_node_id'] is None and result['donor_emag_category_id'] is None


def test_delayed_old_real_response_cannot_replace_new_search(catalog):
    pending = []
    def delay(route, response, call):
        if call['path'].endswith('/workspace/products') and call['query'].get('q') == ['Alpha']:
            pending.append((route, response)); return True
        return False
    with app_browser(catalog, fault=delay) as ui:
        products(ui); p = ui.page
        with p.expect_request(lambda r: parse_qs(urlparse(r.url).query).get('q') == ['Alpha']):
            p.get_by_label('Termék keresése', exact=True).fill('Alpha')
        # Let the real response enter the deliberately delayed transport queue.
        for _ in range(100):
            if pending:
                break
            p.wait_for_timeout(10)
        assert pending
        with p.expect_response(lambda r: parse_qs(urlparse(r.url).query).get('q') == ['Beta']):
            p.get_by_label('Termék keresése', exact=True).fill('Beta')
        expect(p.locator('.classification-products')).to_contain_text('Mosógép Beta')
        old_route, old_response = pending.pop()
        old_route.fulfill(status=old_response.status_code, body=old_response.content, content_type='application/json')
        p.wait_for_timeout(100)
        expect(p.locator('.classification-products')).not_to_contain_text('Mosógép Alpha')
        expect(p.locator('.classification-products tbody tr')).to_have_count(1)
