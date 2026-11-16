"""CATEGORY-03D: all input PRs + production 03A/03C clients, real FastAPI/SQLite.

Worker enqueue is intercepted; the real operation engine runs in-process.
Only explicitly labelled transport-corruption tests replace response JSON.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from playwright.sync_api import expect
from sqlalchemy import insert,select,func,update,delete
from sqlalchemy.orm import Session
from test_category02d_browser import app_browser
from test_classification_api_integration_browser import (
    _fixtures, environment, password_hash, extra_reference_categories,
    extra_reference_parameters, extra_reference_values,
)

ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture
def full_catalog(environment,monkeypatch):
    from app import import_api,product_jobs,bulk_operations as bo
    sys.path.insert(0,str(ROOT/'backend/tests'))
    import test_product_parameters as h
    c,engine,_,statements=environment
    monkeypatch.setattr(import_api,'enqueue',lambda _:None)
    monkeypatch.setattr(product_jobs,'enqueue',lambda _:None)
    monkeypatch.setattr(product_jobs,'enqueue_parameters',lambda _:None)
    queued=[];monkeypatch.setattr(bo,'enqueue',queued.append)
    _fixtures.login(c,'admin@example.hu')
    supplier=c.post('/api/v1/imports/suppliers',json={'name':'CATEGORY-03D közös fixture'}).json()['id']
    h.install_catalog(engine)
    pid=h.washer(c,engine,supplier,head='SKU;NAME;CATEGORY;Teljesítmény (kW);Szín;Kapacitás (kg)\n',extra=['001','Mosógép A','Gépek','2,1','fehér','8'])
    return SimpleNamespace(client=c,engine=engine,statements=statements,pid=pid,supplier=supplier,queued=queued,helper=h)


def overview(ui):
    p=ui.page
    p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
    p.get_by_role('tab',name='Paraméteres termékáttekintés',exact=True).click()
    expect(p.get_by_role('button',name='Teljes szűrt termékkör rögzítése',exact=True)).to_be_visible()


def snapshot(p,page=False):
    if page:
        p.get_by_label('Kijelölés: Mosógép A',exact=True).check()
        p.get_by_role('button',name='Kijelölt termékek rögzítése (1)',exact=True).click()
    else:p.get_by_role('button',name='Teljes szűrt termékkör rögzítése',exact=True).click()
    expect(p.get_by_text('A szerver rögzítette a termékkört és annak revízióit.',exact=True)).to_be_visible()


def finish(f,p):
    from app import bulk_operations as bo
    jid=f.queued[-1]
    with Session(f.engine) as db:
        while bo.advance(db,jid,batch=500)!='completed':pass
    p.get_by_role('button',name='Futás frissítése',exact=True).click()
    expect(p.get_by_text('Befejezve',exact=False).first).to_be_visible()
    return jid


def preview(f,p):
    p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
    expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible()
    return finish(f,p)


def apply_bulk(p):
    p.get_by_label('Tömeges döntés indoka',exact=True).fill('Ellenőrzött közös termékkör')
    p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True).click()
    p.get_by_role('button',name='Tömeges döntés megerősítése',exact=True).click()
    expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible()


@pytest.mark.parametrize('width',[390,1440])
def test_native_bulk_approval_revision_revalidate_revoke(full_catalog,width):
    f=full_catalog;c=f.client
    with app_browser(f,width=width) as ui:
        overview(ui);p=ui.page;snapshot(p,page=True);preview(f,p)
        assert c.get(f'/api/v1/workspace/products/{f.pid}/parameters').json()['slots']==[]
        apply_bulk(p);finish(f,p)
        got=c.get(f'/api/v1/workspace/products/{f.pid}/parameters').json()
        assert got['slots'] and next(s for s in got['slots'] if s['slot_key']=='emag:6506')['value']=='2100'
        p.get_by_role('button',name='Előkészítési ellenőrzés',exact=True).click()
        expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible();finish(f,p)
        p.get_by_label('Tömeges döntés indoka',exact=True).fill('A hiányzó értékek a kutatás céljai')
        p.get_by_role('button',name='Előkészítési jóváhagyás áttekintése',exact=True).click()
        p.get_by_role('button',name='Tömeges döntés megerősítése',exact=True).click()
        expect(p.get_by_role('heading',name='Előkészítési jóváhagyás #1',exact=True)).to_be_visible()
        approval=c.get('/api/v1/workspace/preparation-approvals/1').json()
        assert approval['valid']==1 and approval['research_targets']>0
        source=c.get(f'/api/v1/workspace/products/{f.pid}').json()['source_attributes']
        p.get_by_role('button',name='Paraméteres termék megnyitása: Mosógép A',exact=True).click()
        p.get_by_text('Termékparaméterek',exact=True).click()
        status=p.get_by_role('region',name='Termék előkészítési jóváhagyása',exact=True)
        expect(status).to_contain_text('Érvényes')
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        from test_parameter_api_browser import manual
        manual(p,'set','2200')
        expect(p.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_be_visible()
        expect(status).to_contain_text('Érvénytelen')
        p.get_by_role('tab',name='Paraméteres termékáttekintés',exact=True).click()
        p.get_by_role('button',name='Jóváhagyás #1 megnyitása',exact=True).click()
        detail=p.get_by_role('region',name='Jóváhagyás 1 részletei',exact=True)
        expect(detail).to_contain_text('Jelenleg érvényes: 0; érvénytelen: 1')
        expect(detail).to_contain_text('product_changed')
        p.get_by_role('button',name='Jóváhagyás újramérésének áttekintése',exact=True).click()
        p.get_by_role('button',name='Jóváhagyási döntés megerősítése',exact=True).click()
        expect(p.get_by_role('button',name='Jóváhagyás újramérésének áttekintése',exact=True)).to_be_enabled()
        p.get_by_label('Visszavonás indoka',exact=True).fill('Új előkészítési ellenőrzés szükséges')
        p.get_by_role('button',name='Jóváhagyás visszavonásának áttekintése',exact=True).click()
        p.get_by_role('button',name='Jóváhagyási döntés megerősítése',exact=True).click()
        expect(detail).to_contain_text('Visszavont')
        assert c.get(f'/api/v1/workspace/products/{f.pid}').json()['source_attributes']==source
        body=p.locator('body').inner_text()
        secret_tokens=[v for call in ui.calls if isinstance(call['json'],dict) for k,v in call['json'].items() if k.endswith('_token')]
        assert secret_tokens and all(t not in body and t not in p.url for t in secret_tokens)
        assert p.evaluate('localStorage.length')==0
        assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_native_bulk_partial_revision_and_no_silent_retry(full_catalog):
    f=full_catalog;c=f.client
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);preview(f,p)
        rev=f.helper.revision(c,f.pid)
        assert c.patch(f'/api/v1/workspace/products/{f.pid}/classification',json={'expected_revision':rev,'action':'set','navigation_node_id':f.helper.WASHER}).status_code==200
        apply_bulk(p)
        from app import bulk_operations as bo
        jid=f.queued[-1]
        with Session(f.engine) as db:assert bo.advance(db,jid)=='completed'
        p.get_by_role('button',name='Futás frissítése',exact=True).click()
        expect(p.get_by_text('Részleges siker',exact=False)).to_be_visible()
        expect(p.get_by_text('Elavult termékrevízió: 1',exact=True)).to_be_visible()
        p.get_by_label('Tétel alkalmazási állapota',exact=True).select_option('stale')
        expect(p.get_by_role('region',name='Tömeges futás tételei')).to_contain_text('Elavult termékrevízió')
        assert c.get(f'/api/v1/workspace/products/{f.pid}/parameters').json()['slots']==[]
        assert len([x for x in ui.calls if x['path'].endswith('/apply') and 'parameter-bulk-previews' in x['path']])==1


def test_native_three_pending_donors_and_choice_stay_blocked(full_catalog):
    f=full_catalog;c=f.client;h=f.helper
    from app import product_catalog as pc
    import test_bulk_preparation as b
    nodes=[h.WASHER,h.WASHER_DRYER,'web-item-114-3820','web-item-83-4339',h.EBOOK,None]
    ids=b.seed(c,f.engine,f.supplier,nodes)
    assert len(pc.internal_categories())==457
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);jid=preview(f,p)
        data=c.get(f'/api/v1/workspace/product-jobs/{jid}').json()
        assert data['outcomes']['skipped_pending_review']==3
        assert data['outcomes']['skipped_choice_required']==1
        assert data['outcomes']['skipped_no_donor']==1
        # Import updates identity 001; the resulting six-product layout has one ready donor.
        assert data['outcomes']['eligible']==1
        for pid in ids[1:4]:
            d=c.get(f'/api/v1/workspace/products/{pid}').json()
            assert d['classification']['parameter_profile_state']=='pending_review'
            assert c.get(f'/api/v1/workspace/products/{pid}/parameters').json()['slots']==[]
        expect(p.get_by_text('Donor felülvizsgálatra vár: 3',exact=True)).to_be_visible()


def test_native_bulk_token_expiry_and_readonly(full_catalog):
    f=full_catalog
    from app.product_models import ProductSelection
    from app.models import now
    from datetime import timedelta
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p)
        with Session(f.engine) as db:
            db.execute(update(ProductSelection).values(expires_at=now()-timedelta(seconds=1)));db.commit()
        p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
        expect(p.get_by_role('alert').last).to_be_visible()
        calls=[x for x in ui.calls if x['path'].endswith('/parameter-bulk-previews')]
        assert len(calls)==1 and calls[0]['status']==409
    _fixtures.login(f.client,'processor@example.hu')
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);preview(f,p)
        expect(p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True)).to_have_count(0)
        expect(p.get_by_role('button',name='Előkészítési jóváhagyás áttekintése',exact=True)).to_have_count(0)


@pytest.mark.parametrize('where',['selection','apply','job'])
def test_native_bad_dto_and_explicit_idempotent_recovery(full_catalog,where):
    f=full_catalog;remaining=[True]
    def fault(route,response,call):
        if call['method']=='POST' and call['path'].startswith('/api/v1/workspace/'):
            assert route.request.headers.get('x-csrf-token')
        path=call['path'];method=call['method']
        match=(where=='selection' and path.endswith('/product-selections') or
               where=='apply' and 'parameter-bulk-previews/' in path and path.endswith('/apply') or
               where=='job' and '/product-jobs/' in path and not path.endswith('/items') and method=='GET')
        if match and remaining:
            remaining.clear();route.fulfill(status=200,json={});return True
        return False
    with app_browser(f,fault=fault) as ui:
        overview(ui);p=ui.page
        if where=='selection':
            p.get_by_role('button',name='Teljes szűrt termékkör rögzítése',exact=True).click()
            expect(p.get_by_role('alert').last).to_contain_text('nem értelmezhető')
            expect(p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True)).to_have_count(0)
            return
        snapshot(p)
        if where=='job':
            p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
            expect(p.get_by_role('alert').last).to_contain_text('nem értelmezhető')
            expect(p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True)).to_have_count(0)
            return
        preview(f,p)
        p.get_by_label('Tömeges döntés indoka',exact=True).fill('Idempotens helyreállítás')
        p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True).click()
        p.get_by_role('button',name='Tömeges döntés megerősítése',exact=True).click()
        expect(p.get_by_role('alert').last).to_contain_text('nem értelmezhető')
        p.get_by_role('button',name='Azonos kérés kézi ismétlése (idempotens)',exact=True).click()
        expect(p.get_by_text('A szerver a már létező alkalmazási futást adta vissza.',exact=True)).to_be_visible()
        finish(f,p)
        from app.product_models import ProductJob
        with Session(f.engine) as db:
            assert db.scalar(select(func.count()).select_from(ProductJob).where(ProductJob.kind=='bulk_apply'))==1
        applies=[x for x in ui.calls if 'parameter-bulk-previews/' in x['path'] and x['path'].endswith('/apply')]
        assert len(applies)==2 and applies[1]['json']['replayed']


def test_native_manual_lock_survives_bulk_source_refresh(full_catalog):
    f=full_catalog;c=f.client;h=f.helper
    h.apply(c,f.pid)
    assert h.edit(c,f.pid,'emag:6506',action='set',value='2200',unit='W',reason='Gyártói adatlap').status_code==200
    h.washer(c,f.engine,f.supplier,head='SKU;NAME;CATEGORY;Teljesítmény (kW);Szín;Kapacitás (kg)\n',extra=['001','Mosógép A','Gépek','2,3','fekete','8'])
    raw=c.get(f'/api/v1/workspace/products/{f.pid}').json()['source_attributes']
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);preview(f,p)
        expect(p.get_by_text('védett: 1',exact=False)).to_be_visible()
        apply_bulk(p);finish(f,p)
        slots=c.get(f'/api/v1/workspace/products/{f.pid}/parameters').json()['slots']
        power=next(s for s in slots if s['slot_key']=='emag:6506')
        assert power['value']=='2200' and power['locked']
        assert power['sources'][0]['raw']=='2,1'
        assert next(s for s in slots if s['slot_key']=='emag:6507')['value']=='Fekete'
        assert c.get(f'/api/v1/workspace/products/{f.pid}').json()['source_attributes']==raw


def test_native_250k_selection_boundary_and_50002_multi_run(full_catalog):
    """Actual stored SQLite rows; not a MySQL benchmark, import or 250k apply."""
    from app.import_models import SupplierProduct
    from app.product_models import ProductSelection,ProductSelectionItem,ProductParameterValue
    from app import bulk_operations as bo
    from datetime import timedelta
    f=full_catalog;c=f.client
    with Session(f.engine) as db:
        first=db.get(SupplierProduct,f.pid)
        for begin in range(0,250000,5000):
            db.execute(insert(SupplierProduct),[dict(tenant_id=first.tenant_id,supplier_id=first.supplier_id,
                identity_key=f'cap-{i}',data={'sku':f'cap-{i}','name':f'Kapacitás {i}'},last_run_id=first.last_run_id,
                last_line=i+2,revision=1,search_text=f'cohort {i}' if i<50002 else f'other {i}',source_attributes={})
                for i in range(begin,min(begin+5000,250000))])
        db.commit()
        assert db.scalar(select(func.count()).select_from(SupplierProduct))==250001
    rejected=c.post('/api/v1/workspace/product-selections',json={'filters':{}})
    assert rejected.status_code==422
    with Session(f.engine) as db:
        # The refused snapshot is atomic; no hidden truncation to 250k.
        assert db.scalar(select(func.count()).select_from(ProductSelection))==0
        db.execute(delete(SupplierProduct).where(SupplierProduct.id==db.scalar(select(func.max(SupplierProduct.id)))))
        db.commit()
    accepted=c.post('/api/v1/workspace/product-selections',json={'filters':{}})
    assert accepted.status_code==200 and accepted.json()['total']==250000
    from datetime import datetime
    data=accepted.json()
    assert abs((datetime.fromisoformat(data['expires_at'])-datetime.fromisoformat(data['created_at'])).total_seconds()-7200)<1
    with Session(f.engine) as db:
        assert db.scalar(select(func.count()).select_from(ProductSelectionItem).where(ProductSelectionItem.selection_id==data['id']))==250000
    with app_browser(f) as ui:
        overview(ui);p=ui.page
        p.get_by_label('Paraméteres termékkeresés',exact=True).fill('cohort')
        expect(p.get_by_role('button',name='Teljes szűrt termékkör rögzítése',exact=True)).to_be_enabled()
        snapshot(p)
        p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
        expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible()
        jid=f.queued[-1]
        with Session(f.engine) as db:
            assert bo.advance(db,jid,batch=500)=='pending'
            midway=c.get(f'/api/v1/workspace/product-jobs/{jid}').json()
            assert (midway['processed'],midway['run_limit'],midway['runs'])==(50000,50000,1)
            assert bo.advance(db,jid,batch=500)=='completed'
            assert db.scalar(select(func.count()).select_from(ProductParameterValue))==0
        p.get_by_role('button',name='Futás frissítése',exact=True).click()
        expect(p.get_by_text('Befejezve',exact=False).first).to_be_visible()
        final=c.get(f'/api/v1/workspace/product-jobs/{jid}').json()
        assert (final['processed'],final['total'],final['runs'])==(50002,50002,2)
        assert f.queued.count(jid)==2
        assert not any('selection_token' in x['path'] or 'preview_token' in x['path'] for x in ui.calls)


def test_native_large_category_map_uses_2000_threshold_not_parameter_limit(full_catalog):
    from app.import_models import SupplierProduct
    from app import product_jobs
    from test_category02d_browser import inspect as inspect_mapping
    f=full_catalog
    with Session(f.engine) as db:
        first=db.get(SupplierProduct,f.pid)
        source=first.source_category_id
        db.execute(insert(SupplierProduct),[dict(tenant_id=first.tenant_id,supplier_id=first.supplier_id,
            identity_key=f'map-{i}',data={'sku':f'map-{i}','name':f'Térkép {i}','category':'Gépek'},
            source_category_id=source,last_run_id=first.last_run_id,last_line=i+2,revision=1,search_text=f'map {i}',source_attributes={}) for i in range(2000)])
        db.commit()
    with app_browser(f) as ui:
        p=ui.page
        p.get_by_role('navigation').get_by_role('button',name='Termékadatok',exact=True).click()
        p.get_by_role('tab',name='Saját kategóriatérkép és profilok',exact=True).click()
        p.get_by_role('button',name='Gépek kategóriatérképének szerkesztése',exact=True).click()
        inspect_mapping(p)
        p.get_by_role('button',name='Kategóriatérkép jóváhagyása',exact=True).click()
        expect(p.get_by_text('Az újrabesorolás háttérben fut:',exact=False)).to_be_visible()
        result=next(x['json'] for x in ui.calls if x['method']=='PUT' and '/category-maps/' in x['path'])
        assert result['products_changed'] is None and result['locked_skipped'] is None
        assert result['reapply']['total']==2001 and result['reapply']['mode']=='queued'
        with Session(f.engine) as db:assert product_jobs.advance(db,result['reapply']['job_id'])=='completed'
        got=f.client.get(f"/api/v1/workspace/product-jobs/{result['reapply']['job_id']}").json()
        assert got['processed']==2001 and got['locked_skipped']==1


@pytest.mark.parametrize('status',[403,409])
def test_native_bulk_write_error_requires_new_snapshot(full_catalog,status):
    from app.product_models import ProductJob
    from app.access_models import PermissionException
    f=full_catalog
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);jid=preview(f,p)
        p.get_by_label('Tömeges döntés indoka',exact=True).fill('Szerver által újraellenőrzött döntés')
        p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True).click()
        with Session(f.engine) as db:
            if status==403:db.add(PermissionException(user_id=2,context='tenant:1',permission='products.bulk',allowed=False))
            else:
                j=db.get(ProductJob,jid);j.counters={**j.counters,'outcomes':{'eligible':2}}
            db.commit()
        p.get_by_role('button',name='Tömeges döntés megerősítése',exact=True).click()
        expect(p.get_by_role('alert').last).to_be_visible()
        calls=[x for x in ui.calls if 'parameter-bulk-previews/' in x['path'] and x['path'].endswith('/apply')]
        assert len(calls)==1 and calls[0]['status']==status
        expect(p.get_by_role('button',name='Azonos kérés kézi ismétlése (idempotens)',exact=True)).to_have_count(0)
        expect(p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True)).to_be_disabled()


@pytest.mark.parametrize('status',[422,503])
def test_native_bulk_selection_empty_or_catalog_unavailable(full_catalog,status):
    from app.models import Setting
    from app.catalog_constants import ACTIVE_KEY
    f=full_catalog
    with app_browser(f) as ui:
        overview(ui);p=ui.page
        if status==422:
            p.get_by_label('Paraméteres termékkeresés',exact=True).fill('biztosan-nincs-ilyen-termék')
            expect(p.get_by_text('Nincs a paraméterszűrésnek megfelelő termék.',exact=True)).to_be_visible()
        else:
            with Session(f.engine) as db:db.execute(delete(Setting).where(Setting.key==ACTIVE_KEY));db.commit()
        p.get_by_role('button',name='Teljes szűrt termékkör rögzítése',exact=True).click()
        expect(p.get_by_role('alert').last).to_be_visible()
        calls=[x for x in ui.calls if x['path'].endswith('/product-selections')]
        assert len(calls)==1 and calls[0]['status']==status
        expect(p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True)).to_have_count(0)


def test_native_bulk_requires_both_new_permissions(full_catalog):
    from app.access_models import PermissionException
    f=full_catalog
    with Session(f.engine) as db:
        db.add(PermissionException(user_id=3,context='tenant:1',permission='products.parameters',allowed=True));db.commit()
    _fixtures.login(f.client,'processor@example.hu')
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);preview(f,p)
        expect(p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True)).to_have_count(0)
        data=next(x['json'] for x in ui.calls if x['path'].endswith('/parameter-bulk-previews'))
        r=f.client.post(f"/api/v1/workspace/parameter-bulk-previews/{data['preview']['id']}/apply",json={'preview_token':data['preview_token'],'confirm':True,'expected_eligible':1,'idempotency_key':'native-and-permissions'})
        assert r.status_code==403


def test_native_queue_failure_resume_and_cancel(full_catalog,monkeypatch):
    from app import bulk_operations as bo
    from app.product_models import ProductParameterValue
    f=full_catalog;available={'ready':False}
    def enqueue(jid):
        if not available['ready']:raise ConnectionError('isolated broker fixture')
        f.queued.append(jid)
    monkeypatch.setattr(bo,'enqueue',enqueue)
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p)
        p.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
        expect(p.get_by_text('A sorba állítás nem sikerült. A futás kifejezetten folytatható.',exact=True)).to_be_visible()
        available['ready']=True
        with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/resume')) as response:
            p.get_by_role('button',name='Feldolgozás folytatása',exact=True).click()
        assert response.value.status==200
        jid=f.queued[-1]
        with Session(f.engine) as db:assert bo.advance(db,jid,batch=1,max_batches=1)=='pending'
        with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/cancel')) as response:
            p.get_by_role('button',name='Hátralévő feldolgozás megszakítása',exact=True).click()
        assert response.value.status==200
        expect(p.get_by_text('Megszakítva',exact=False)).to_be_visible()
        data=f.client.get(f'/api/v1/workspace/product-jobs/{jid}').json()
        assert data['processed']==1 and data['state']=='cancelled'
        with Session(f.engine) as db:assert db.scalar(select(func.count()).select_from(ProductParameterValue))==0
