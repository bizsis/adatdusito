"""Production adapter exercised with the published CATEGORY-02A HTTP DTOs.

These are contract mocks, separate from presentation mocks and real API tests.
"""
from copy import deepcopy
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest
from playwright.sync_api import expect, sync_playwright
from test_classification_presentation_browser import presentation_build  # noqa: F401


@pytest.fixture
def contract_page(presentation_build):
    path = ['Háztartási gépek és klíma', 'Mosógépek', 'Elöltöltős mosógépek']
    node = {'navigation_node_id': 'web-item-114-3490', 'name': 'Elöltöltős mosógépek', 'path': path,
            'donors': [{'emag_category_id': 385, 'name': 'Mosógépek'}, {'emag_category_id': 386, 'name': 'Mosó-szárítógépek'}]}
    item = {'id': 7, 'revision': 3, 'fields': {'sku': '00001', 'name': 'Mosógép Alpha', 'category': 'Saját / Gépek'},
            'supplier_name': 'Beszállító A', 'source_line': 2,
            'source_category': {'id': 4, 'path': 'Saját / Gépek', 'origin': 'supplier', 'supplier_id': 1},
            'classification': {'status': 'needs_review', 'origin': 'suggestion', 'method': 'name', 'reason_codes': ['uncalibrated_suggestion'],
                               'navigation_node_id': None, 'navigation_path': None, 'donor_emag_category_id': None, 'donor_name': None,
                               'donor_choices': [], 'confidence': None, 'alternatives': [{'navigation_node_id': node['navigation_node_id'], 'path': path, 'score': None}],
                               'locked': False, 'rule_version': 'category-02a.1', 'decided_by': None, 'decided_at': None}}
    state = {'item': item, 'classify': True, 'conflict': False, 'writes': [], 'reads': [], 'map': None}

    def detail():
        return {**deepcopy(state['item']), 'capabilities': {'classify': state['classify']},
                'source_attributes': [{'key': 'Teljesítmény (W)', 'header': 'Teljesítmény (W)', 'label': 'Teljesítmény', 'unit': 'W', 'raw': '2100', 'present': False}], 'events': []}

    def route_request(route):
        u = urlparse(route.request.url)
        if not u.path.startswith('/api/v1/'):
            f = presentation_build / (u.path.lstrip('/') or 'tests/classification/index.html')
            route.fulfill(body=f.read_bytes(), content_type=mimetypes.guess_type(f.name)[0] or 'text/plain')
            return
        q = parse_qs(u.query)
        if route.request.method != 'GET':
            body = route.request.post_data_json
            state['writes'].append((u.path, route.request.method, body))
            assert 'tenant_id' not in (body or {}) and 'handle' not in (body or {})
            if state['conflict']:
                route.fulfill(status=409, json={'error': {'code': 'conflict', 'message': 'A revízió megváltozott.'}})
                return
            if '/category-maps/' in u.path:
                state['map'] = {**body, 'navigation_path': path, 'revision': 1, 'decided_at': None, 'decided_by': 1}
                route.fulfill(json={'source_category': item['source_category'], 'map': state['map'], 'products_changed': 17, 'locked_skipped': 3})
                return
            assert body['expected_revision'] == state['item']['revision']
            state['item']['revision'] += 1
            c = state['item']['classification']
            c.update(status='auto_classified' if body['action'] == 'set' else 'needs_review', origin='manual' if body['action'] == 'set' else 'suggestion', locked=body['action'] == 'set', navigation_node_id=body.get('navigation_node_id'), navigation_path=path if body['action'] == 'set' else None,
                     donor_emag_category_id=body.get('donor_emag_category_id'), donor_name='Mosógépek' if body.get('donor_emag_category_id') else None)
            route.fulfill(json=detail())
            return
        state['reads'].append((u.path, q))
        if u.path.endswith('/internal-categories'):
            result = {'items': [node], 'total': 457, 'offset': int(q.get('offset', ['0'])[0]), 'limit': 100}
        elif u.path.endswith('/category-maps'):
            result = {'items': [{'source_category': item['source_category'], 'product_count': 20, 'map': state['map'], 'suggestions': []}], 'next_cursor': None}
        elif u.path.endswith('/products/7'):
            result = detail()
        else:
            assert u.path.endswith('/workspace/products'), u.path
            result = {'items': [state['item']], 'next_cursor': 7 if q.get('cursor', ['0'])[0] == '0' else None, 'field_labels': {'sku': 'Cikkszám'}, 'status_counts': {'auto_classified': 100000, 'needs_review': 25000}}
        route.fulfill(json=result)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None, args=['--no-sandbox'])
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('http://contract.test/**', route_request)
        yield page, state
        assert not errors
        browser.close()


def open_detail(page):
    page.goto('http://contract.test/?contract')
    page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
    expect(page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_be_visible()


def prepare(page):
    open_detail(page)
    page.get_by_role('button', name='Besorolás szerkesztése', exact=True).click()
    page.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek', exact=True).click()
    page.get_by_label('Paraméterprofil', exact=True).select_option('385')
    page.get_by_label('Módosítás indoka', exact=True).fill('Ellenőrzött döntés')
    page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
    expect(page.get_by_role('heading', name='Előnézet', exact=True)).to_be_visible()


@pytest.mark.parametrize('width', [390, 1440])
def test_actual_dto_read_capabilities_filters_and_lazy_choices(contract_page, width):
    page, state = contract_page
    page.set_viewport_size({'width': width, 'height': 1000})
    open_detail(page)
    expect(page.get_by_text('2100 · A legutóbbi fájlból hiányzott', exact=True)).to_be_visible()
    expect(page.get_by_label('Termék keresése', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='Aktuális oldal kijelölése')).to_have_count(0)
    page.get_by_label('Besorolási státusz', exact=True).select_option('review')
    expect(page.get_by_role('button', name='Mosógép Alpha részletei')).to_be_visible()
    page.get_by_label('Forrás szerinti szűrés', exact=True).select_option('manual')
    expect(page.get_by_role('button', name='Mosógép Alpha részletei')).to_be_visible()
    assert any(q.get('status') == ['needs_review'] and q.get('origin') == ['manual'] for _, q in state['reads'])
    assert not state['writes']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_actual_patch_revision_donor_and_manual_lock(contract_page):
    page, state = contract_page
    prepare(page)
    assert not state['writes']
    expect(page.get_by_text('Helyi módosítás-összesítő', exact=False)).to_be_visible()
    page.get_by_role('button', name='Módosítás mentése', exact=True).click()
    expect(page.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_be_visible()
    url, method, body = state['writes'][0]
    assert url.endswith('/products/7/classification') and method == 'PATCH'
    assert body == {'expected_revision': 3, 'action': 'set', 'navigation_node_id': 'web-item-114-3490', 'donor_emag_category_id': 385, 'reason': 'Ellenőrzött döntés'}
    expect(page.locator('table').get_by_text('Saját / Gépek', exact=True)).to_be_visible()
    expect(page.locator('table').get_by_text('Kézi javítás védett', exact=True)).to_be_visible()


def test_actual_http_409_never_retries_or_reports_saved(contract_page):
    page, state = contract_page
    prepare(page)
    state['conflict'] = True
    page.get_by_role('button', name='Módosítás mentése', exact=True).click()
    expect(page.get_by_role('button', name='Friss adatok betöltése')).to_be_visible()
    assert len(state['writes']) == 1
    expect(page.get_by_text('A kézi besorolás mentve és zárolva.', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Friss adatok betöltése').click()
    expect(page.get_by_role('button', name='Mosógép Alpha részletei')).to_be_visible()


def test_actual_mapping_always_propagates_and_reports_real_counts(contract_page):
    page, state = contract_page
    page.goto('http://contract.test/?contract')
    page.get_by_role('tab', name='Saját kategóriatérkép és profilok').click()
    page.get_by_role('button', name='Saját / Gépek kategóriatérképének szerkesztése', exact=True).click()
    page.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek').click()
    page.get_by_label('Paraméterprofil', exact=True).select_option('385')
    expect(page.get_by_role('checkbox')).to_have_count(0)
    page.get_by_label('Módosítás indoka', exact=True).fill('Kategóriatérkép jóváhagyása')
    page.get_by_role('button', name='Módosítások előnézete', exact=True).click()
    assert not state['writes']
    page.get_by_role('button', name='Kategóriatérkép jóváhagyása', exact=True).click()
    expect(page.get_by_text('Kategóriatérkép mentve. Újrabesorolt termékek: 17; védett, kihagyott: 3.', exact=True)).to_be_visible()
    assert state['writes'][0][2]['expected_revision'] is None


def test_detail_capability_overrides_global_permission(contract_page):
    page, state = contract_page
    state['classify'] = False
    page.goto('http://contract.test/?contract')
    page.get_by_role('button', name='Mosógép Alpha részletei', exact=True).click()
    expect(page.get_by_text('2100 · A legutóbbi fájlból hiányzott', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='Besorolás szerkesztése', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Mosógép Alpha besorolásának módosítása', exact=True)).to_have_count(0)


def test_actual_cursor_category_filter_and_confidence_ratio(contract_page):
    page, state = contract_page
    state['item']['classification']['confidence'] = .985
    open_detail(page)
    expect(page.get_by_text('Megbízhatósági érték: 98,5%', exact=True)).to_be_visible()
    page.get_by_role('button', name='Következő termékek', exact=True).click()
    expect(page.get_by_role('button', name='Előző termékek', exact=True)).to_be_enabled()
    assert any(q.get('cursor') == ['7'] and q.get('limit') == ['25'] for path, q in state['reads'] if path.endswith('/products'))
    page.get_by_role('button', name='Kategória szerinti szűrés: Minden kategória', exact=True).click()
    page.get_by_role('button', name='Kiválasztás: Elöltöltős mosógépek', exact=True).click()
    expect(page.get_by_role('button', name='Mosógép Alpha részletei', exact=True)).to_be_visible()
    assert any(q.get('navigation_node_id') == ['web-item-114-3490'] and q.get('cursor') == ['0'] for _, q in state['reads'])
    assert not state['writes']


def test_documented_search_uses_q_on_server_and_resets_cursor(contract_page):
    page, state = contract_page
    page.goto('http://contract.test/?contract')
    page.get_by_role('button', name='Következő termékek', exact=True).click()
    expect(page.get_by_role('button', name='Előző termékek', exact=True)).to_be_enabled()
    search = page.get_by_label('Termék keresése', exact=True)
    expect(search).to_have_attribute('maxlength', '120')
    with page.expect_request(lambda r: urlparse(r.url).path.endswith('/workspace/products') and parse_qs(urlparse(r.url).query).get('q') == ['00001 50%_']):
        search.fill('00001 50%_')
    expect(page.get_by_text('Termékek betöltése…', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Mosógép Alpha részletei', exact=True)).to_be_visible()
    assert any(q.get('q') == ['00001 50%_'] and q.get('cursor') == ['0'] for _, q in state['reads'])
    assert not state['writes']
