"""Production CATEGORY-03B frontend + actual c05746d FastAPI/SQLite endpoints.

No external server/database. Optional backend dependency is explicit on the
frontend-only PR; the combined integration branch runs these without skips.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from playwright.sync_api import expect
from sqlalchemy import insert, select
from sqlalchemy.orm import Session
from test_category02d_browser import app_browser
from test_classification_api_integration_browser import (
    _fixtures, environment, password_hash, extra_reference_categories,
    extra_reference_parameters, extra_reference_values,
)

pytestmark=pytest.mark.skipif(importlib.util.find_spec('app.parameter_views') is None,reason='Requires CATEGORY-03A backend PR #26 c05746d.')


@pytest.fixture
def live_catalog(environment,monkeypatch):
    from app import import_api, product_jobs
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend/tests'))
    import test_product_parameters as helper
    c,engine,_,statements=environment
    monkeypatch.setattr(import_api,'enqueue',lambda _:None)
    queued=[];monkeypatch.setattr(product_jobs,'enqueue_parameters',queued.append)
    _fixtures.login(c,'admin@example.hu')
    supplier=c.post('/api/v1/imports/suppliers',json={'name':'Élő paraméterteszt beszállító'}).json()['id']
    helper.install_catalog(engine)
    pid=helper.washer(c,engine,supplier)
    return SimpleNamespace(client=c,engine=engine,statements=statements,helper=helper,pid=pid,supplier=supplier,queued=queued)


def open_product(ui,name='Mosógép A'):
    p=ui.page
    p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
    p.get_by_role('button',name=f'{name} részletei',exact=True).click()
    p.get_by_text('Termékparaméterek',exact=True).click()
    expect(p.get_by_role('heading',name='Paraméter-előkészítés – valódi API',exact=True)).to_be_visible()
    expect(p.locator('.parameter-table tbody tr').first).to_be_visible()


def apply_preview(p):
    p.get_by_role('button',name='Paraméterváltozások szerveres előnézete',exact=True).click()
    p.get_by_label('Döntés indoka',exact=True).fill('Valódi API előnézetének elfogadása')
    p.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    expect(p.get_by_role('heading',name='Szerveroldali változáselőnézet',exact=True)).to_be_visible()
    p.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(p.get_by_text('A szerver alkalmazta a paraméterváltozásokat. A nyers forrásadatok megmaradtak.',exact=True)).to_be_visible()


def slot_data(c,pid):
    r=c.get(f'/api/v1/workspace/products/{pid}/parameters');assert r.status_code==200,r.text
    return r.json()


def manual(p,action,value=None,source=None):
    p.get_by_label('Kézi művelet',exact=True).select_option(action)
    if value is not None:p.get_by_label('Új kézi érték',exact=True).fill(value)
    if source is not None:p.get_by_label('Elfogadandó forrás',exact=True).select_option(source)
    p.get_by_label('Kézi döntés indoka',exact=True).fill('Ellenőrzött, auditált kézi művelet')
    p.get_by_role('button',name='Kézi döntés áttekintése',exact=True).click()
    expect(p.get_by_text('Helyi megerősítés – nem szerveres változáselőnézet',exact=True)).to_be_visible()
    p.get_by_role('button',name='Kézi döntés mentése',exact=True).click()


@pytest.mark.parametrize('width',[390,1440])
def test_real_parameters_preview_apply_conversion_manual_lock_reset(live_catalog,width):
    c=live_catalog.client;pid=live_catalog.pid
    original=c.get(f'/api/v1/workspace/products/{pid}').json()['source_attributes']
    with app_browser(live_catalog,width=width) as ui:
        open_product(ui);p=ui.page
        expect(p.locator('.parameter-table').get_by_text('2,1 kW',exact=True)).to_be_visible()
        expect(p.locator('.parameter-table').get_by_text('2100 W',exact=True)).to_be_visible()
        assert slot_data(c,pid)['slots']==[]
        apply_preview(p)
        stored=slot_data(c,pid);power=next(s for s in stored['slots'] if s['slot_key']=='emag:6506')
        assert power['value']=='2100' and power['unit_conversion']['factor']=='1000'
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        manual(p,'set','2000')
        expect(p.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_be_visible()
        stored=slot_data(c,pid);power=next(s for s in stored['slots'] if s['slot_key']=='emag:6506')
        assert power['value']=='2000' and power['locked'] and power['sources'][0]['raw']=='2,1'
        assert c.get(f'/api/v1/workspace/products/{pid}').json()['source_attributes']==original
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        manual(p,'reset')
        expect(p.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_have_count(0)
        power=next(s for s in slot_data(c,pid)['slots'] if s['slot_key']=='emag:6506')
        assert power['value']=='2100' and not power['locked']
        patch_calls=[x for x in ui.calls if x['method']=='PATCH' and '/parameters/' in x['path']]
        assert len(patch_calls)==2 and all(x['status']==200 for x in patch_calls)
        assert any(x['method']=='POST' and x['path'].endswith('/parameters/preview') for x in ui.calls)
        assert not any('snapshot' in x['path'] or 'preparation-approval' in x['path'] for x in ui.calls)
        assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_real_pending_and_multiple_donors_never_autofill(live_catalog):
    h=live_catalog.helper;c=live_catalog.client;pid=live_catalog.pid
    rev=c.get(f'/api/v1/workspace/products/{pid}').json()['revision']
    assert c.patch(f'/api/v1/workspace/products/{pid}/classification',json={'expected_revision':rev,'action':'set','navigation_node_id':h.WASHER_DRYER}).status_code==200
    with app_browser(live_catalog) as ui:
        open_product(ui);apply_preview(ui.page)
        got=slot_data(c,pid)
        assert got['classification']['parameter_profile_state']=='pending_review'
        assert got['slots'] and all(s['slot_key'].startswith('src:') for s in got['slots'])
        ui.page.get_by_text('Paraméterforrás és donorprofilok',exact=True).click()
        expect(ui.page.get_by_text('A donor felülvizsgálatra vár.',exact=False)).to_be_visible()
    rev=c.get(f'/api/v1/workspace/products/{pid}').json()['revision']
    assert c.patch(f'/api/v1/workspace/products/{pid}/classification',json={'expected_revision':rev,'action':'set','navigation_node_id':h.EBOOK}).status_code==200
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        expect(p.get_by_label('Választandó paraméterprofil',exact=True)).to_have_value('')
        assert not any(s['slot_key'].startswith('emag:') for s in slot_data(c,pid)['slots'])
        p.get_by_label('Választandó paraméterprofil',exact=True).select_option('103')
        p.get_by_label('Profilválasztás indoka',exact=True).fill('Kifejezett profilválasztás, nem donorjóváhagyás')
        p.get_by_role('button',name='Profilválasztás áttekintése',exact=True).click()
        p.get_by_role('button',name='Paraméterprofil kiválasztása',exact=True).click()
        p.get_by_role('button',name='Mosógép A részletei',exact=True).click()
        p.get_by_text('Termékparaméterek',exact=True).click()
        apply_preview(p)
        got=slot_data(c,pid)
        assert got['classification']['parameter_profile_state']=='ready'
        assert any(s['slot_key']=='emag:10301' for s in got['slots'])


def test_real_alias_create_list_revoke_no_implicit_application(live_catalog):
    c=live_catalog.client;pid=live_catalog.pid
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
        p.get_by_label('Alias címkéje',exact=True).fill('Power')
        p.get_by_label('Alias egysége',exact=True).fill('kW')
        p.get_by_label('Alias célparamétere',exact=True).select_option('6506')
        p.get_by_label('Alias indoka',exact=True).fill('Szakmailag igazolt teljesítmény-alias')
        p.get_by_role('button',name='Aliasszabály áttekintése',exact=True).click()
        assert c.get('/api/v1/workspace/parameter-aliases').json()['items']==[]
        p.get_by_role('button',name='Aliasszabály megerősítése',exact=True).click()
        expect(p.get_by_role('button',name='Alias visszavonása: Power',exact=True)).to_be_visible()
        aliases=c.get('/api/v1/workspace/parameter-aliases').json()['items'];assert len(aliases)==1 and aliases[0]['scope']=='tenant'
        assert slot_data(c,pid)['slots']==[]
        p.get_by_role('button',name='Alias visszavonása: Power',exact=True).click()
        p.get_by_role('button',name='Aliasszabály megerősítése',exact=True).click()
        expect(p.get_by_role('button',name='Alias visszavonása: Power',exact=True)).to_have_count(0)
        revoked=c.get('/api/v1/workspace/parameter-aliases?state=revoked').json()['items']
        assert revoked[0]['version']==2


def test_real_revision_409_reload_does_not_repeat_apply(live_catalog):
    c=live_catalog.client;pid=live_catalog.pid
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_role('button',name='Paraméterváltozások szerveres előnézete',exact=True).click()
        p.get_by_label('Döntés indoka',exact=True).fill('Revíziós előnézet')
        p.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
        expect(p.get_by_role('heading',name='Szerveroldali változáselőnézet',exact=True)).to_be_visible()
        live_catalog.helper.apply(c,pid)
        p.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
        expect(p.get_by_role('button',name='Friss paraméteradatok betöltése',exact=True)).to_be_visible()
        calls=[x for x in ui.calls if x['path'].endswith('/parameters/apply')]
        assert len(calls)==1 and calls[0]['status']==409
        p.get_by_role('button',name='Friss paraméteradatok betöltése',exact=True).click()
        expect(p.locator('.parameter-table tbody tr').first).to_be_visible()


def test_real_overview_server_filters_and_readonly(live_catalog):
    c=live_catalog.client;pid=live_catalog.pid;live_catalog.helper.apply(c,pid)
    _fixtures.login(c,'processor@example.hu')
    with app_browser(live_catalog) as ui:
        p=ui.page;p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
        p.get_by_role('tab',name='Paraméteres termékáttekintés',exact=True).click()
        p.get_by_label('Paraméteres termékkeresés',exact=True).fill('001')
        p.get_by_label('Paraméterhely állapota',exact=True).select_option('missing')
        p.get_by_role('button',name='Paraméteres termék megnyitása: Mosógép A',exact=True).click()
        p.get_by_text('Termékparaméterek',exact=True).click()
        expect(p.locator('.parameter-table tbody tr').first).to_be_visible()
        expect(p.get_by_role('button',name='Paraméterváltozások szerveres előnézete',exact=True)).to_have_count(0)
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        expect(p.get_by_text('Csak olvasható; nincs paramétermódosítási jogosultság.',exact=True)).to_be_visible()
        assert any(x['path'].endswith('/parameter-diff') and x['query'].get('state')==['missing'] for x in ui.calls)
        assert not any(x['method']=='PATCH' for x in ui.calls)


def test_real_conflict_invalid_review_detached_and_candidate_resolution(live_catalog):
    h=live_catalog.helper;c=live_catalog.client;pid=live_catalog.pid
    h.washer(c,live_catalog.engine,live_catalog.supplier,
        head='SKU;NAME;CATEGORY;Szín;Szín;Energiaosztály;Kapacitás (kg)\n',
        extra=['001','Mosógép A','Gépek','Fehér','Fekete','C','8'])
    h.apply(c,pid)
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        states={s['state'] for s in slot_data(c,pid)['slots']}
        assert {'conflict','invalid','missing','present'}<=states
        p.get_by_role('button',name='Paraméterrészlet: Szín',exact=True).click()
        expect(p.locator('.parameter-table')).to_contain_text('Fehér')
        expect(p.locator('.parameter-table')).to_contain_text('Fekete')
        manual(p,'accept_candidate',source='Szín #2')
        expect(p.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_be_visible()
        color=next(s for s in slot_data(c,pid)['slots'] if s['slot_key']=='emag:6507')
        assert color['value']=='Fekete' and color['locked']
        p.get_by_role('button',name='Paraméterrészlet: Energiaosztály',exact=True).click()
        expect(p.get_by_label('Új kézi érték',exact=True)).to_be_disabled()
    rev=h.revision(c,pid)
    assert c.patch(f'/api/v1/workspace/products/{pid}/classification',json={
        'expected_revision':rev,'action':'set','navigation_node_id':h.VACUUM}).status_code==200
    h.apply(c,pid)
    with app_browser(live_catalog) as ui:
        open_product(ui)
        got=slot_data(c,pid)
        assert {'detached','review','source_only'}<={s['state'] for s in got['slots']}
        expect(ui.page.locator('.parameter-table')).to_contain_text('Fekete')
        assert any(s['slot_key']=='emag:5802' and s['candidates'][0]['raw']=='8' for s in got['slots'])


def test_real_locked_feed_refresh_preserves_old_and_current_raw(live_catalog):
    h=live_catalog.helper;c=live_catalog.client;pid=live_catalog.pid
    h.apply(c,pid)
    assert h.edit(c,pid,'emag:6506',action='set',value='2000',unit='W',reason='Adatlap').status_code==200
    h.washer(c,live_catalog.engine,live_catalog.supplier,power='2,3')
    h.apply(c,pid)
    with app_browser(live_catalog) as ui:
        open_product(ui)
        table=ui.page.locator('.parameter-table')
        expect(table).to_contain_text('2,1 kW')
        expect(table).to_contain_text('2,3 kW')
        expect(table).to_contain_text('2000 W')
        expect(table).to_contain_text('Aktuális termékforrás')
        power=next(s for s in slot_data(c,pid)['slots'] if s['slot_key']=='emag:6506')
        assert power['locked'] and power['value']=='2000'


@pytest.mark.parametrize('status',[403,404,422])
def test_real_manual_write_errors_require_explicit_reload(live_catalog,status):
    from app.access_models import PermissionException
    from app.models import LoginSession,Membership
    from sqlalchemy import update
    c=live_catalog.client;pid=live_catalog.pid
    if status==422:
        live_catalog.helper.washer(c,live_catalog.engine,live_catalog.supplier,
            head='SKU;NAME;CATEGORY;Energiaosztály\n',extra=['001','Mosógép A','Gépek','C'])
    live_catalog.helper.apply(c,pid)
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        title='Energiaosztály' if status==422 else 'Teljesítmény (kW)'
        p.get_by_role('button',name=f'Paraméterrészlet: {title}',exact=True).click()
        if status==403:
            with Session(live_catalog.engine) as db:
                db.add(PermissionException(user_id=2,context='tenant:1',permission='products.parameters',allowed=False));db.commit()
        elif status==404:
            with Session(live_catalog.engine) as db:
                db.add(Membership(tenant_id=2,user_id=2,role='tenant_admin'));db.execute(update(LoginSession).values(tenant_id=2));db.commit()
        if status==422:manual(p,'accept_candidate',source='Energiaosztály')
        else:manual(p,'set','2000')
        expect(p.get_by_role('alert').last).to_be_visible()
        writes=[x for x in ui.calls if x['method']=='PATCH' and '/parameters/' in x['path']]
        assert len(writes)==1 and writes[0]['status']==status
        expect(p.get_by_role('button',name='Kézi döntés áttekintése',exact=True)).to_be_disabled()


def test_real_catalog_unavailable_503_not_empty_success(live_catalog):
    from app.models import Setting
    from app.catalog_constants import ACTIVE_KEY
    from sqlalchemy import delete
    with Session(live_catalog.engine) as db:
        db.execute(delete(Setting).where(Setting.key==ACTIVE_KEY));db.commit()
    with app_browser(live_catalog) as ui:
        p=ui.page
        p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
        p.get_by_role('button',name='Mosógép A részletei',exact=True).click()
        p.get_by_text('Termékparaméterek',exact=True).click()
        expect(p.get_by_role('alert').last).to_be_visible()
        assert any(x['path'].endswith('/parameters/preview') and x['status']==503 for x in ui.calls)
        expect(p.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True)).to_have_count(0)


def test_real_expired_parameter_session_401_logs_out(live_catalog):
    from datetime import timedelta
    from app.models import LoginSession,now
    from sqlalchemy import update
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_role('tab',name='Paraméteres termékáttekintés',exact=True).click()
        expect(p.get_by_role('button',name='Paraméteres termék megnyitása: Mosógép A',exact=True)).to_be_visible()
        p.wait_for_load_state('networkidle')
        with Session(live_catalog.engine) as db:
            db.execute(update(LoginSession).values(expires_at=now()-timedelta(days=1)));db.commit()
        p.get_by_label('Paraméteres termékkeresés',exact=True).fill('001')
        expect(p.get_by_role('button',name='Bejelentkezés →',exact=True)).to_be_visible()
        assert any(x['path'].endswith('/parameter-diff') and x['status']==401 for x in ui.calls)


@pytest.mark.parametrize('where',['read','preview','apply','alias','job'])
def test_parameter_malformed_transport_never_claims_success(live_catalog,where):
    # Explicit transport corruption AFTER a genuine API response, not backend evidence.
    remaining=[True]
    def fault(route,response,call):
        path=call['path'];method=call['method']
        match=(where=='read' and path.endswith('/parameters') and method=='GET' or
               where=='preview' and path.endswith('/parameters/preview') or
               where=='apply' and path.endswith('/parameters/apply') or
               where=='alias' and path.endswith('/parameter-aliases') and method=='GET' or
               where=='job' and path.endswith('/parameter-runs') and method=='POST')
        if remaining and match:
            remaining.clear();route.fulfill(status=200,json={});return True
        return False
    with app_browser(live_catalog,fault=fault) as ui:
        p=ui.page
        if where in ('read','preview'):
            p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
            p.get_by_role('button',name='Mosógép A részletei',exact=True).click()
            p.get_by_text('Termékparaméterek',exact=True).click()
        else:
            open_product(ui)
            if where=='apply':
                p.get_by_role('button',name='Paraméterváltozások szerveres előnézete',exact=True).click()
                p.get_by_label('Döntés indoka',exact=True).fill('Ellenőrzött előnézet')
                p.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
                p.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
            elif where=='alias':p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
            else:
                expect(p.get_by_role('heading',name='Paraméterhelyek háttérfutása',exact=True)).to_be_visible()
                p.get_by_role('button',name='Futás indításának áttekintése',exact=True).click()
                p.get_by_role('button',name='Paraméterfutás indítása',exact=True).click()
        expect(p.get_by_role('alert').last).to_contain_text('nem értelmezhető')
        expect(p.get_by_text('A szerver alkalmazta a paraméterváltozásokat. A nyers forrásadatok megmaradtak.',exact=True)).to_have_count(0)
        if where=='apply':assert len([x for x in ui.calls if x['path'].endswith('/parameters/apply')])==1


def test_real_50002_stored_products_cursor_and_multiple_runs(live_catalog):
    from app.import_models import SupplierProduct
    from app import product_jobs
    from sqlalchemy import func
    c=live_catalog.client
    with Session(live_catalog.engine) as db:
        first=db.get(SupplierProduct,live_catalog.pid)
        for start in range(0,50001,2000):
            db.execute(insert(SupplierProduct),[dict(tenant_id=first.tenant_id,supplier_id=first.supplier_id,
                identity_key=f'large-{i}',data={'sku':f'large-{i}','name':f'Terhelés {i}'},
                last_run_id=first.last_run_id,last_line=i+2,revision=1,search_text=f'terhelés {i}\tlarge-{i}',
                source_attributes={}) for i in range(start,min(start+2000,50001))])
        db.commit()
        assert db.scalar(select(func.count()).select_from(SupplierProduct))==50002
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        expect(p.get_by_role('heading',name='Paraméterhelyek háttérfutása',exact=True)).to_be_visible()
        p.get_by_label('Futás hatóköre',exact=True).select_option('workspace')
        p.get_by_role('button',name='Futás indításának áttekintése',exact=True).click()
        p.get_by_role('button',name='Paraméterfutás indítása',exact=True).click()
        expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible()
        first=live_catalog.queued[-1]
        with Session(live_catalog.engine) as db:
            assert product_jobs.advance_parameters(db,first,batch=500)== 'completed'
        p.get_by_role('button',name='Paraméterfutás állapotának frissítése',exact=True).click()
        p.get_by_role('button',name='Következő legfeljebb 50 000 termék áttekintése',exact=True).click()
        with p.expect_response(lambda r:r.request.method=='POST' and r.url.split('?')[0].endswith('/workspace/parameter-runs')) as response:
            p.get_by_role('button',name='Paraméterfutás indítása',exact=True).click()
        assert response.value.status==200
        second=live_catalog.queued[-1];assert second!=first
        with Session(live_catalog.engine) as db:assert product_jobs.advance_parameters(db,second,batch=500)=='completed'
        p.get_by_role('button',name='Paraméterfutás állapotának frissítése',exact=True).click()
        expect(p.get_by_text(f'Futás #{second}: Futás befejezve',exact=False)).to_be_visible()
        one=c.get(f'/api/v1/workspace/product-jobs/{first}').json()
        two=c.get(f'/api/v1/workspace/product-jobs/{second}').json()
        assert (one['processed'],one['limit'],one['has_more'])==(50000,50000,True)
        assert (two['processed'],two['limit'],two['has_more'])==(2,50000,False)
        assert two['start_after_product_id']==one['next_start_after_product_id']
        from app.product_models import ProductParameterValue
        with Session(live_catalog.engine) as db:assert db.scalar(select(func.count()).select_from(ProductParameterValue))==0
        p.get_by_role('tab',name='Paraméteres termékáttekintés',exact=True).click()
        expect(p.get_by_role('button',name='Következő paraméteres termékek',exact=True)).to_be_visible()
        p.get_by_label('Paraméteres termékkeresés',exact=True).fill('large-50000')
        expect(p.get_by_role('button',name='Paraméteres termék megnyitása: Terhelés 50000',exact=True)).to_be_visible()
        assert max(len(x['json'].get('items',[])) for x in ui.calls if x['path'].endswith('/parameter-diff') and isinstance(x['json'],dict))<=25


def test_real_scoped_background_apply_idempotent_and_tenant_job_hidden(live_catalog):
    from app import product_jobs
    from app.main import app
    from fastapi.testclient import TestClient
    c=live_catalog.client
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_label('Futás hatóköre',exact=True).select_option('supplier')
        p.get_by_label('Futás módja',exact=True).select_option('apply')
        for turn in range(2):
            p.get_by_role('button',name='Futás indításának áttekintése',exact=True).click()
            p.get_by_role('button',name='Paraméterfutás indítása',exact=True).click()
            expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible()
            job=live_catalog.queued[-1]
            with Session(live_catalog.engine) as db:assert product_jobs.advance_parameters(db,job)=='completed'
            p.get_by_role('button',name='Paraméterfutás állapotának frissítése',exact=True).click()
            expect(p.get_by_text(f'Futás #{job}: Futás befejezve',exact=False)).to_be_visible()
            got=c.get(f'/api/v1/workspace/product-jobs/{job}').json()
            assert got['scope']['supplier_id']==live_catalog.supplier
            assert got['processed']==1 and got['products_changed']==(1 if turn==0 else 0)
        assert len(slot_data(c,live_catalog.pid)['slots'])==8
        other=TestClient(app,base_url='https://testserver');_fixtures.login(other,'other@example.hu')
        assert other.get(f'/api/v1/workspace/product-jobs/{job}').status_code==404
        assert other.get(f'/api/v1/workspace/products/{live_catalog.pid}/parameters').status_code==404
        assert other.get('/api/v1/workspace/parameter-diff').json()['items']==[]


def test_real_global_alias_requires_global_permission(live_catalog):
    c=live_catalog.client
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
        expect(p.get_by_label('Új alias hatóköre',exact=True).locator('option[value="global"]')).to_have_count(0)
    _fixtures.login(c)
    assert c.post('/api/v1/auth/tenant',json={'tenant_id':1}).status_code==200
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
        p.get_by_label('Új alias hatóköre',exact=True).select_option('global')
        p.get_by_label('Alias címkéje',exact=True).fill('Watt')
        p.get_by_label('Alias egysége',exact=True).fill('W')
        p.get_by_label('Alias célparamétere',exact=True).select_option('6506')
        p.get_by_label('Alias indoka',exact=True).fill('Globális, ellenőrzött címkeszabály')
        p.get_by_role('button',name='Aliasszabály áttekintése',exact=True).click()
        p.get_by_role('button',name='Aliasszabály megerősítése',exact=True).click()
        expect(p.get_by_role('button',name='Alias visszavonása: Watt',exact=True)).to_be_visible()
        global_alias=c.get('/api/v1/workspace/parameter-aliases?scope=global').json()['items'][0]
        assert global_alias['scope']=='global'
    _fixtures.login(c,'admin@example.hu')
    with app_browser(live_catalog) as ui:
        open_product(ui);p=ui.page
        p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
        expect(p.get_by_text('Watt',exact=True)).to_be_visible()
        expect(p.get_by_role('button',name='Alias visszavonása: Watt',exact=True)).to_have_count(0)
        assert c.delete(f"/api/v1/workspace/parameter-aliases/{global_alias['id']}?expected_version=1").status_code==403
