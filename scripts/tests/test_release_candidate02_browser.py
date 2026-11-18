"""RC-02: integrated imports and HELP-02, real API + production bundle.

Uses rc02_sample.synthetic_feed(), never an uploaded customer file. SQLite and
worker execution are isolated to the inherited test environment.
"""
from types import SimpleNamespace
import pytest
from playwright.sync_api import expect
from sqlalchemy.orm import Session
from app import import_api
from app.import_engine import advance
from app.import_models import ImportRun, SupplierProduct
from app.models import Audit
from sqlalchemy import select
from test_classification_api_integration_browser import (
    _fixtures, environment, password_hash, extra_reference_categories,
    extra_reference_parameters, extra_reference_values,
)
from test_category02d_browser import app_browser
from rc02_sample import synthetic_feed

@pytest.fixture
def release_import(environment,monkeypatch):
    c,target,_,statements=environment
    _fixtures.login(c,'admin@example.hu')
    def worker(id):
        with Session(target) as db:advance(db,id)
    monkeypatch.setattr(import_api,'enqueue',worker)
    return SimpleNamespace(client=c,engine=target,statements=statements)


@pytest.mark.parametrize('width', [390, 1440])
def test_import_history_preserves_rc02_data_and_template_upload_is_analysis_only(release_import, width):
    f = release_import
    c = f.client
    url = '/api/v1/imports/runs'
    sid = c.post('/api/v1/imports/suppliers', json={'name': 'RC02 szintetikus beszállító'}).json()['id']

    def legacy_upload(name):
        result = c.post(url, data={'supplier_id': sid}, files={'file': (name, synthetic_feed())})
        assert result.status_code == 200, result.text
        return result.json()['id']

    first = legacy_upload('torlendo.csv')
    second = legacy_upload('megmarado.csv')
    run = c.get(f'{url}/{first}').json()
    assert len(run['analysis']['headers']) == 27
    assert tuple(run['analysis'][k] for k in ['physical_rows', 'data_rows', 'empty_rows']) == (4948, 3, 4945)
    assert all(col['field'] != 'price' for col in run['analysis']['columns'])
    approval = {
        'name': 'RC02 szintetikus profil', 'identity_field': 'sku',
        'mapping': {str(col['index']): col['field'] for col in run['analysis']['columns'] if col['field']},
    }
    assert c.post(f'{url}/{first}/approve', json=approval).status_code == 422
    assert c.delete(f'{url}/{first}').status_code == 200
    assert c.get(f'{url}/{first}').status_code == 404
    approved = c.post(f'{url}/{second}/approve', json={**approval, 'financial_approved': True})
    assert approved.status_code == 200, approved.text
    done = c.get(f'{url}/{second}').json()
    assert done['state'] == 'completed' and done['counters'] == {'ready': 3, 'empty': 4945}
    assert c.delete(f'{url}/{second}').status_code == 409

    with app_browser(f, width=width) as ui:
        p = ui.page
        nav = p.locator('.sidebar nav')
        expect(nav.get_by_role('button', name='Import', exact=True)).to_have_count(1)
        expect(nav.get_by_role('button', name='Beszállítói import', exact=True)).to_have_count(0)
        expect(nav.get_by_role('button', name='Export', exact=True)).to_have_count(0)
        nav.get_by_role('button', name='Import', exact=True).click()
        p.get_by_label('Webshopmotor', exact=True).select_option('unas')
        p.get_by_label('Beszállító', exact=True).select_option(str(sid))
        p.get_by_text('Korábban feltöltött fájlok', exact=True).click()
        expect(p.get_by_role('button', name=f'#{first} · torlendo.csv', exact=True)).to_have_count(0)
        p.get_by_role('button', name=f'#{second} · megmarado.csv', exact=True).click()
        rows = p.get_by_role('list', name='Forrásoszlopok').locator(':scope > li')
        expect(rows.or_(p.locator(".prep-bindings li"))).to_have_count(27)
        expect(p.get_by_text('Feldolgozott sorok', exact=True)).to_have_count(0)
        with p.expect_response(lambda r: r.url.endswith(url) and r.request.method == 'POST') as upload:
            p.get_by_label('CSV, XLS, XLSX vagy XML fájl').set_input_files(
                {'name': 'uj.csv', 'mimeType': 'text/csv', 'buffer': synthetic_feed()})
        assert upload.value.status == 200
        created = upload.value.json()
        assert created['analysis_only'] and created['id'] not in {first, second}
        expect(p.get_by_text('3 termék · 27 oszlop')).to_be_visible()
        expect(rows.or_(p.locator(".prep-bindings li"))).to_have_count(27)
        assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')

    with Session(f.engine) as db:
        products = list(db.scalars(select(SupplierProduct).where(SupplierProduct.supplier_id == sid)))
        assert len(products) == 3 and {product.last_run_id for product in products} == {second}
        data = {r.data['sku']: r.data for r in products}
        assert data['RC02-001']['purchase_price'] == '405.51'
        assert data['RC02-001']['list_price'] == '589.7637795'
        assert data['RC02-001']['stock'] == '-35132'
        assert not data['RC02-001'].get('gtin')
        assert data['RC02-003']['gtin'] == '5999000000017'
        assert db.get(ImportRun, first) is None
        assert any(a.action == 'import.delete' for a in db.scalars(select(Audit)))
