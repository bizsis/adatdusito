"""RC-02: integrated imports and HELP-02, real API + production bundle.

Uses rc02_sample.synthetic_feed(), never an uploaded customer file. SQLite and
worker execution are isolated to the inherited test environment.
"""
import os
import re
from pathlib import Path
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

ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture
def release_import(environment,monkeypatch):
    c,target,_,statements=environment
    _fixtures.login(c,'admin@example.hu')
    def worker(id):
        with Session(target) as db:advance(db,id)
    monkeypatch.setattr(import_api,'enqueue',worker)
    return SimpleNamespace(client=c,engine=target,statements=statements)


def upload(p,name):
    with p.expect_response(lambda r:r.url.endswith('/api/v1/imports/runs') and r.request.method=='POST') as created:
        p.get_by_label('CSV/XLSX fájl',exact=True).set_input_files({'name':name,'mimeType':'text/csv','buffer':synthetic_feed()})
    assert created.value.status==200
    run=created.value.json()
    expect(p.get_by_role('heading',name=f"#{run['id']} – Jóváhagyásra vár",exact=True)).to_be_visible(timeout=15000)
    return run['id']


def shot(p,locator,name,width):
    expect(locator).to_be_visible()
    if os.environ.get('RC02_SCREENSHOTS')=='1' and width==1440:
        locator.evaluate("e=>e.scrollIntoView({block:'start'})")
        box=locator.bounding_box();scroll=p.evaluate('({x:scrollX,y:scrollY})')
        p.screenshot(path=str(ROOT/f'frontend/public/help/images/{name}.png'),full_page=True,
            clip={'x':box['x']+scroll['x'],'y':box['y']+scroll['y'],'width':box['width'],'height':min(box['height'],1400)},animations='disabled')

@pytest.mark.parametrize('width',[390,1440])
def test_complete_import_delete_refresh_reupload_and_financial_guards(release_import,width):
    f=release_import;c=f.client
    with app_browser(f,width=width) as ui:
        p=ui.page
        p.locator('.sidebar nav').get_by_role('button',name='Beszállítói import',exact=True).click()
        p.get_by_label('Új beszállító neve',exact=True).fill('RC02 szintetikus beszállító')
        with p.expect_response(lambda r:r.url.endswith('/imports/suppliers') and r.request.method=='POST') as supplier:
            p.get_by_role('button',name='Beszállító létrehozása',exact=True).click()
        sid=supplier.value.json()['id']
        expect(p.locator('main > section.card').first.locator('select').first).to_have_value(str(sid))
        name='szintetikus_27_oszlopos_regresszio_'+('hosszu_fajlnev_'*12)+'.csv'
        first=upload(p,name)
        run=c.get(f'/api/v1/imports/runs/{first}').json()
        assert len(run['analysis']['headers'])==27
        assert tuple(run['analysis'][k] for k in ['physical_rows','data_rows','empty_rows'])==(4948,3,4945)
        expect(p.locator('.row-counts')).to_have_text(re.compile(r'Összes sor:\s*4\s?948.*nem üres.*3.*üres sor:\s*4\s?945'))
        preview=p.locator('#import-preview ~ .preview-table').first
        expect(preview.locator('tbody tr')).to_have_count(3)
        size=p.locator('label:has-text("Sorok oldalanként") select').first
        expect(size).to_have_value('10')
        for n in ['5','25','50','10']:
            with p.expect_response(lambda r:r.url.endswith(f'/imports/runs/{first}/preview') and r.request.method=='POST'):
                size.select_option(n)
            expect(preview.locator('tbody tr')).to_have_count(3)
        expect(p.get_by_label('Megfeleltetés: LASTINITIALCOST',exact=True)).to_have_value('purchase_price')
        expect(p.get_by_label('Megfeleltetés: LISTPRICE',exact=True)).to_have_value('list_price')
        assert all(col['field']!='price' for col in run['analysis']['columns'])
        p.get_by_text('Pénzügyi értelmezés',exact=False).click()
        expect(p.get_by_role('textbox',name='Nettó/bruttó jelleg',exact=True)).to_have_value('nettó')
        expect(p.get_by_role('textbox',name='Pénznem',exact=True)).to_have_value('HUF')
        expect(p.get_by_text('utólagos Excel-formázás nem állítja helyre',exact=False)).to_be_visible()
        expect(preview.get_by_text('tudományos jelölés',exact=False).first).to_be_visible()
        expect(preview.get_by_text('negatív érték',exact=False).first).to_be_visible()
        expect(p.locator('.tech-json').first).to_be_hidden()
        shot(p,p.locator('table').filter(has_text='Eredeti oszlop'),'rc02-oszlopok',width)
        shot(p,preview,'rc02-elozet',width)
        # The real approval endpoint must reject missing financial confirmation.
        with p.expect_response(lambda r:r.url.endswith(f'/imports/runs/{first}/approve')) as denied:
            p.get_by_role('button',name='Megfeleltetés jóváhagyása és feldolgozás',exact=True).click()
        assert denied.value.status==422
        expect(p.get_by_role('alert').filter(has_text='pénzügyi').first).to_be_visible()
        shot(p,p.locator('form').filter(has=p.get_by_role('button',name='Megfeleltetés jóváhagyása és feldolgozás',exact=True)),'rc02-jovahagyas',width)
        history=p.locator('table.import-history')
        shot(p,history,'rc02-importtortenet',width)
        assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # A second, independent unapproved import must survive the deletion.
        # It also avoids SQLite's rowid-reuse artifact; MySQL identity is checked separately.
        other=c.post('/api/v1/imports/runs',data={'supplier_id':str(sid)},
                     files={'file':('rc02-megmarado.csv',b'SKU;NAME\nKEEP-001;Megmarado demo\n')})
        assert other.status_code==200
        keeper=other.json()['id']
        p.get_by_role('button',name=f'#{first} {name} törlése',exact=True).click()
        dialog=p.get_by_role('alertdialog')
        expect(dialog).to_contain_text('Megmarad')
        expect(dialog).to_contain_text('Véglegesen törlődik')
        shot(p,dialog,'rc02-importtorles',width)
        with p.expect_response(lambda r:r.url.endswith(f'/imports/runs/{first}') and r.request.method=='DELETE') as deleted:
            dialog.get_by_role('button',name='Végleges törlés',exact=True).click()
        assert deleted.value.status==200
        expect(p.get_by_role('status').filter(has_text=f'#{first} import')).to_contain_text('törölve')
        assert c.get(f'/api/v1/imports/runs/{first}').status_code==404
        p.reload()
        p.locator('.sidebar nav').get_by_role('button',name='Beszállítói import',exact=True).click()
        expect(p.locator('table.import-history tbody tr')).to_have_count(1)
        assert c.get(f'/api/v1/imports/runs/{keeper}').status_code==200
        p.locator('main > section.card').first.locator('select').first.select_option(str(sid))
        second=upload(p,'rc02-szintetikus-ujratoltes.csv')
        assert second!=first
        listed=c.get('/api/v1/imports/runs').json()
        assert first not in {r['id'] for r in listed}
        expect(p.get_by_role('button',name=f'#{first} {name} megnyitása',exact=True)).to_have_count(0)
        p.locator('label:has-text("Jóváhagyott összekapcsolási kulcs") select').select_option('sku')
        p.get_by_label('A pénzügyi mezők jelentését ellenőriztem',exact=False).check()
        with p.expect_response(lambda r:r.url.endswith(f'/imports/runs/{second}/approve')) as approved:
            p.get_by_role('button',name='Megfeleltetés jóváhagyása és feldolgozás',exact=True).click()
        assert approved.value.status==200
        done=c.get(f'/api/v1/imports/runs/{second}').json()
        assert done['state']=='completed' and done['counters']=={'ready':3,'empty':4945}
        assert c.delete(f'/api/v1/imports/runs/{second}').status_code==409
        with Session(f.engine) as db:
            products=list(db.scalars(select(SupplierProduct).where(SupplierProduct.supplier_id==sid)))
            assert len(products)==3
            data={r.data['sku']:r.data for r in products}
            assert data['RC02-001']['purchase_price']=='405.51'
            assert data['RC02-001']['list_price']=='589.7637795'
            assert data['RC02-001']['stock']=='-35132'
            assert not data['RC02-001'].get('gtin')
            assert data['RC02-003']['gtin']=='5999000000017'
            assert db.get(ImportRun,first) is None
            assert any(a.action=='import.delete' for a in db.scalars(select(Audit)))
        # The current manual must describe the actual integrated controls.
        p.goto('http://category02d.test/#/segedlet/import-elozmenyek-hibak')
        expect(p.locator('.help-article')).to_contain_text('Végleges törlés')
        expect(p.locator('.help-article')).not_to_contain_text('nem kínál Megszakítás')
        assert len([call for call in ui.calls if call['path'].endswith(f'/runs/{first}') and call['method']=='DELETE'])==1
