"""CATEGORY-03B UI/controller tests with presentation mocks, NOT backend API integration.

Synthetic /__category03b_test__/ routes are test adapters only. No final API,
source database, AI request or real background job is claimed by this suite.
"""
from copy import deepcopy
import json
import mimetypes
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope='module')
def parameter_build(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp('category03b-ui')
    subprocess.run(['node','node_modules/vite/bin/vite.js','build','--config','tests/parameters/vite.config.mjs'], cwd=root/'frontend', env={**os.environ,'CATEGORY03_TEST_DIST':str(output)}, check=True,capture_output=True,text=True)
    return output


@pytest.fixture
def parameter_page(parameter_build):
    def value(raw, normalized=None, raw_unit='W', unit='kW'):
        return dict(raw=raw,rawUnit=raw_unit,normalized=normalized,unit=unit,source='beszallito.csv / futás 18 / sor 2 / oszlop 4',conversionNote='Jóváhagyott dimenzióhelyes konverzió' if normalized else '')
    def row(key, title, status='present', match='confirmed', own=True, donor=True, **extra):
        return dict(key=key,status=status,match=match,explanation='A forrásérték megmarad; az egyezés indoka külön ellenőrizhető.',own=dict(key='own-'+key,title=title,required=False,value=value('2100','2,1')) if own else None,
                    donor=dict(key='donor-'+key,title=title,type='szám',unit='kW',required=True,constraint='') if donor else None,
                    correction=None,aliasSuggestion=None,locked=False,canEdit=True,history=[],**extra)
    rows = [row('power','Teljesítmény'),row('missing','Garancia',status='missing',match='none',own=False),row('alias','Kapacitás',status='conflict',match='ambiguous'),row('invalid','Feszültség',status='invalid'),row('own-only','Saját megjegyzés',match='none',donor=False),row('capacity-kg','Kapacitás',donor=False,match='none')]
    rows[1]['donor']['unit']='hónap';rows[1]['donor']['type']='egész szám'
    rows[3]['donor']['unit']='V'
    rows[2]['explanation']='Azonos címke mellett eltérő mértékegység: jelentésellenőrzés szükséges.'
    rows[4]['status']='source_only'
    rows += [row('review','Terhelhetőség',status='review',match='ambiguous'), row('detached','Korábbi mérési adat',status='detached',match='none',donor=False)]
    rows[2]['additionalSources']=[dict(key='second-source',title='Másik megőrzött forrásoszlop',value=value('8',None,'kg','kg'))]
    rows[2]['aliasSuggestion']='Űrtartalom / kapacitás – kézi ellenőrzés'
    rows[2]['own']['value']=value('7',None,'kg','kg');rows[2]['donor']['unit']='l'
    rows[3]['donor']['constraint']='Csak 230 V'
    rows[3]['own']['value']=value('110',None,'V','V')
    rows[4]['own']['value']=value('Eredeti szöveg',None,None,None)
    rows[5]['own']['value']=value('9',None,'kg','kg')
    profiles=[dict(key='reviewed',title='Mosógépek – ellenőrzött profil',path='Háztartás / Mosógépek',review='approved'),dict(key='pending',title='Vitatott profil',path='Másik forrás / Ellenőrzés',review='pending_review')]
    job=dict(key='parameter-job',context={'revision':1},state='partial',progressPercent=37,processed=18500,total=50000,changed=18000,skipped=400,failed=100,message='A hátralévő tételek folytathatók.',errors=[dict(label='SKU-009',message='Revízióütközés')],canResume=True,canCancel=True)
    state=dict(rows=rows,profiles=profiles,profile='reviewed',requests=[],writes=[],previews={},fail_read=False,deny_values=False,no_values=False,conflict=False,deny_apply=0,local=False,overwrites=0,invalid_run=False,job=job,revision=1,hold=False,pending=[],preparation='review',can_approve=False)
    def route_request(route):
        u=urlparse(route.request.url)
        if not u.path.startswith('/__category03b_test__/'):
            f=parameter_build/(u.path.lstrip('/') or 'tests/parameters/index.html')
            route.fulfill(body=f.read_bytes(),content_type=mimetypes.guess_type(f.name)[0] or 'text/plain');return
        _,_,workspace,operation=u.path.split('/')
        body=route.request.post_data_json
        state['requests'].append((workspace,operation,deepcopy(body)))
        if operation=='diff':
            if state['fail_read']:
                route.fulfill(status=503,json={});return
            filtered=deepcopy(state['rows'])
            if body['filters']['search']:
                filtered=[r for r in filtered if body['filters']['search'].casefold() in ((r['own'] or r['donor'])['title']).casefold()]
            if body['filters']['status']!='all':filtered=[r for r in filtered if r['status']==body['filters']['status']]
            if body['filters']['match']!='all':filtered=[r for r in filtered if r['match']==body['filters']['match']]
            offset=int(body['cursor'] or 0)
            result=dict(rows=filtered[offset:offset+4],next=str(offset+4) if len(filtered)>offset+4 else None,total=len(filtered),totalProducts=125000,context={'revision':state['revision'],'workspace':workspace},versionLabel='Katalógus v12 / termékrevízió '+str(state['revision']),profiles=state['profiles'],activeProfileKey=state['profile'],preparation=dict(state=state['preparation'],canApprove=state['can_approve'],explanation='A jóváhagyás a visszakapott revízióra érvényes.' if state['preparation']=='approved' else 'Az egyezési konfliktusok rendezettek; az üres érték később kutatható.' if state['can_approve'] else 'A hiányzó érték megengedett; az egyezési konfliktusokat felül kell vizsgálni.',audit='Teszt szerverpillanatkép'))
            if workspace=='two':result['rows']=[{**result['rows'][0],'key':'other','own':{**result['rows'][0]['own'],'title':'Másik ügyfél paramétere'}}]
            if state['hold'] and workspace=='one':state['pending'].append((route,result));return
        elif operation=='values':
            if state['deny_values']:route.fulfill(status=503,json={});return
            values=['2,1','2,2','2,3','2,4'];values=[v for v in values if body['search'] in v];offset=int(body['cursor'] or 0)
            result=dict(hasList=not state['no_values'],items=[] if state['no_values'] else values[offset:offset+2],next=None if state['no_values'] else str(offset+2) if offset+2<len(values) else None)
        elif operation=='snapshot':result=dict(handle={'opaque':'server-snapshot'},count=125000,description='A szerver által rögzített termékkör')
        elif operation=='preview':
            handle='preview-'+str(len(state['previews'])+1);state['previews'][handle]=deepcopy(body)
            bulk='selection' in body
            result=dict(origin='local' if state['local'] else 'server',handle=handle,summary='Meglévő saját értékek megmaradnak.',canApply=True,eligible=124995 if bulk else 1,preserved=6,addedEmpty=2,locked=3 if bulk else 0,conflicts=2 if bulk else 0,blocked=0,sourceOverwrites=state['overwrites'],changes=[dict(label='Paraméterhely',before='Nincs hely',after='Új üres hely – érték nélkül')],runs=[dict(label='1. futás',count=50001 if state['invalid_run'] else 50000),dict(label='2. futás',count=50000),dict(label='3. futás',count=25000)] if bulk else [])
        elif operation=='apply':
            if state['conflict']:route.fulfill(status=409,json={});return
            if state['deny_apply']:route.fulfill(status=state['deny_apply'],json={});return
            intent=state['previews'][body['handle']];state['writes'].append(deepcopy(intent));state['revision']+=1
            action=intent['action']
            if action=='edit':
                r=next(r for r in state['rows'] if r['key']==intent['rowKey']);r['correction']=intent['correction'];r['locked']=True;r['history'].append(dict(when='2026-11-15',actor='Teszt Admin',reason=intent['reason'],before=r['own']['value']['raw'],after=intent['correction']))
            elif action=='unlock':next(r for r in state['rows'] if r['key']==intent['rowKey'])['locked']=False
            elif action=='approve_alias':next(r for r in state['rows'] if r['key']==intent['rowKey'])['match']='confirmed'
            elif action=='select_profile':state['profile']=intent['profileKey']
            elif action=='approve_preparation':state['preparation']='approved';state['can_approve']=False
            result=dict(message='Tesztadapter által visszaigazolt mentés.',job=state['job'] if 'selection' in intent else None)
        elif operation=='job':result=state['job']
        elif operation=='resume':state['job']={**state['job'],'state':'running','canResume':False,'progressPercent':38};result=state['job']
        elif operation=='cancel':state['job']={**state['job'],'state':'cancelled','canCancel':False,'canResume':False};result=state['job']
        else:raise AssertionError(operation)
        route.fulfill(json=result)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None,args=['--no-sandbox'])
        page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('http://parameter.test/**',route_request)
        yield page,state
        assert not errors
        browser.close()


def open_preview(page):
    page.get_by_role('button',name='Hiányzó üres helyek előnézete',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Ellenőrzött előkészítés')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    expect(page.get_by_role('region',name='Paraméterváltozások előnézete',exact=True)).to_be_visible()


@pytest.mark.parametrize('width',[390,1440])
def test_statuses_raw_normalized_units_constraint_and_responsive(parameter_page,width):
    page,state=parameter_page;page.set_viewport_size({'width':width,'height':1000});page.goto('http://parameter.test/')
    table=page.locator('.parameter-table')
    for text in ('Meglévő','Hiányzó hely','Ütközés','Érvénytelen','2100','2,1','kg','Csak 230 V'):
        expect(table.get_by_text(text,exact=False).first).to_be_visible()
    expect(table.get_by_text('Bizonytalan egyezés – jóváhagyásra vár',exact=True)).to_be_visible()
    assert '125\u00a0000' in page.inner_text('main')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/category03b-parameters-{width}.png',full_page=True)
    assert not state['writes']


def test_no_match_and_equal_names_are_not_merged(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Következő paraméterek',exact=True).click()
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)
    expect(page.get_by_text('Eredeti szöveg',exact=False)).to_be_visible()
    expect(page.get_by_text('Nincs donor-megfelelés; a saját érték megmarad.',exact=True).first).to_be_visible()
    page.get_by_role('button',name='Előző paraméterek',exact=True).click()
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)
    assert len(state['rows'])==8 and sum(bool(r['own']) and r['own']['title']=='Kapacitás' for r in state['rows'])==2


def test_filters_are_callbacks_and_fast_search_discards_stale_scope(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_label('Paraméter állapota',exact=True).select_option('conflict')
    expect(page.locator('.parameter-table tbody tr')).to_have_count(1)
    assert state['requests'][-1][2]['filters']['status']=='conflict'
    page.get_by_label('Paraméter állapota',exact=True).select_option('all')
    with page.expect_response(lambda r: '/__category03b_test__/' in r.url and r.request.post_data_json.get('filters',{}).get('search')=='Feszültség'):
        page.get_by_label('Paraméter keresése',exact=True).fill('Fes')
        page.get_by_label('Paraméter keresése',exact=True).fill('Feszültség')
    expect(page.locator('.parameter-table tbody tr')).to_have_count(1)
    assert not any(c[2].get('filters',{}).get('search')=='Fes' for c in state['requests'])


def test_preview_before_apply_and_source_preservation(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Paraméterrészlet: Teljesítmény',exact=True).click()
    page.get_by_label('Kézi javított érték',exact=True).fill('2,2')
    page.get_by_label('Javítás egysége',exact=True).fill('kW')
    page.get_by_role('button',name='Kézi javítás előnézete',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Igazolt kézi javítás')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    assert not state['writes']
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_text('Tesztadapter által visszaigazolt mentés.',exact=True)).to_be_visible()
    assert state['rows'][0]['own']['value']['raw']=='2100'
    assert state['rows'][0]['correction']=='2,2' and state['rows'][0]['locked']
    expect(page.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_be_visible()
    page.get_by_role('button',name='Paraméterrészlet: Teljesítmény',exact=True).click()
    expect(page.get_by_role('button',name='Kézi javítás előnézete',exact=True)).to_have_count(0)
    page.get_by_role('button',name='Védelem feloldásának előnézete',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Jogosult auditált feloldás')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_text('Kézi paraméterjavítás védett',exact=True)).to_have_count(0)
    assert state['writes'][-1]['action']=='unlock'


@pytest.mark.parametrize('mode',['readonly','missing-writes'])
def test_no_unbacked_writes(parameter_page,mode):
    page,state=parameter_page;page.goto('http://parameter.test/?'+mode)
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)
    for label in ('Hiányzó üres helyek előnézete','Termékkör rögzítése tömeges előnézethez','Előkészítési jóváhagyás előnézete'):
        expect(page.get_by_role('button',name=label,exact=True)).to_have_count(0)
    assert not state['writes']


@pytest.mark.parametrize('mode',['local','overwrites'])
def test_local_estimate_and_source_overwrite_never_apply(parameter_page,mode):
    page,state=parameter_page;state[mode]=True if mode=='local' else 1;page.goto('http://parameter.test/');open_preview(page)
    expect(page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True)).to_be_disabled()
    assert not state['writes']


@pytest.mark.parametrize('status',[401,403,404,409,422])
def test_write_errors_no_fake_success_or_automatic_retry(parameter_page,status):
    page,state=parameter_page;state['conflict']=status==409;state['deny_apply']=0 if status==409 else status
    page.goto('http://parameter.test/');open_preview(page)
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_role('alert')).to_be_visible()
    expect(page.get_by_role('region',name='Paraméterváltozások előnézete',exact=True)).to_have_count(0)
    assert len([r for r in state['requests'] if r[1]=='apply'])==1 and not state['writes']
    page.get_by_role('button',name='Friss paraméteradatok betöltése',exact=True).click()
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)


def test_pending_donor_blocks_automatic_preparation_and_preserves_values(parameter_page):
    page,state=parameter_page;state['profile']='pending';page.goto('http://parameter.test/')
    page.get_by_text('Paraméterforrás és donorprofilok',exact=True).click()
    expect(page.get_by_text('A donor felülvizsgálatra vár.',exact=False)).to_be_visible()
    expect(page.get_by_role('button',name='Hiányzó üres helyek előnézete',exact=True)).to_have_count(0)
    expect(page.get_by_role('button',name='Előkészítési jóváhagyás előnézete',exact=True)).to_have_count(0)
    expect(page.locator('.parameter-table').get_by_text('2100',exact=False).first).to_be_visible()
    assert not state['writes']


def test_value_search_paging_error_is_not_empty_list(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Paraméterrészlet: Teljesítmény',exact=True).click()
    region=page.get_by_role('region',name='Megengedett paraméterértékek')
    expect(region.get_by_text('2,1',exact=True)).to_be_visible()
    page.get_by_role('button',name='Következő értékek',exact=True).click()
    expect(region.get_by_text('2,3',exact=True)).to_be_visible()
    state['deny_values']=True
    page.get_by_label('Megengedett érték keresése',exact=True).fill('x')
    expect(region.get_by_role('alert')).to_be_visible()
    expect(page.get_by_text('Ehhez a paraméterhez nincs megengedett értéklista.',exact=True)).to_have_count(0)


def test_alias_is_separate_from_confirmed_rows(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    expect(page.get_by_role('button',name='Alias felülvizsgálata: power',exact=True)).to_have_count(0)
    page.get_by_role('button',name='Alias felülvizsgálata: alias',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Igazolt jelentés és egység alapján')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_text('Tesztadapter által visszaigazolt mentés.',exact=True)).to_be_visible()
    assert state['rows'][2]['match']=='confirmed' and state['rows'][2]['own']['value']['raw']=='7'


def test_bulk_snapshot_partial_job_and_resume_cancel(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Termékkör rögzítése tömeges előnézethez',exact=True).click()
    page.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Rögzített termékkör előkészítése')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    expect(page.get_by_text('1. futás: 50\u00a0000 termék',exact=True)).to_be_visible()
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_text('Részleges siker',exact=False)).to_be_visible()
    expect(page.get_by_text('37% – szerveradat',exact=True)).to_be_visible()
    expect(page.get_by_text('SKU-009: Revízióütközés',exact=True)).to_be_visible()
    page.get_by_role('button',name='Feldolgozás folytatása',exact=True).click()
    expect(page.get_by_text('38% – szerveradat',exact=True)).to_be_visible()
    page.get_by_role('button',name='Hátralévő feldolgozás megszakítása',exact=True).click()
    expect(page.get_by_text('Megszakítva',exact=False)).to_be_visible()
    assert state['writes'][0]['selection']['count']==125000
    assert not any('keys' in r[2] for r in state['requests'])


def test_oversized_run_is_not_a_tenant_cap(parameter_page):
    page,state=parameter_page;state['invalid_run']=True;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Termékkör rögzítése tömeges előnézethez',exact=True).click()
    page.get_by_role('button',name='Tömeges paraméter-előnézet',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Hibás szerverterv ellenőrzése')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('50 000')
    expect(page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True)).to_be_disabled()
    assert not state['writes']


def test_preparation_approval_is_not_ai_launch(parameter_page):
    page,state=parameter_page;state['can_approve']=True;state['rows']=state['rows'][:2];page.goto('http://parameter.test/')
    page.get_by_role('button',name='Előkészítési jóváhagyás előnézete',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Előkészítési revízió jóváhagyása')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_role('heading',name='Paraméteres előkészítés jóváhagyva',exact=True)).to_be_visible()
    assert not any('ai' in r[1] or 'credit' in r[1] for r in state['requests'])
    expect(page.get_by_role('button',name='AI indítása')).to_have_count(0)


def test_tenant_switch_discards_late_read(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/?ignore-abort')
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)
    state['hold']=True
    page.get_by_label('Paraméter keresése',exact=True).fill('Teljesítmény')
    for _ in range(100):
        if state['pending']:break
        page.wait_for_timeout(10)
    assert state['pending']
    page.get_by_role('button',name='Teszt: munkaterület váltása',exact=True).click()
    expect(page.locator('.parameter-table').get_by_text('Másik ügyfél paramétere',exact=True)).to_be_visible()
    for route,result in state['pending']:route.fulfill(json=result)
    page.wait_for_timeout(100)
    expect(page.locator('.parameter-table').get_by_text('Másik ügyfél paramétere',exact=True)).to_be_visible()


def test_read_failure_recovers_without_empty_success(parameter_page):
    page,state=parameter_page;state['fail_read']=True;page.goto('http://parameter.test/')
    expect(page.get_by_role('alert')).to_be_visible()
    expect(page.get_by_text('Nincs a szűrésnek megfelelő paraméter.',exact=False)).to_have_count(0)
    state['fail_read']=False;page.get_by_role('button',name='Paraméterlista újratöltése',exact=True).click()
    expect(page.locator('.parameter-table tbody tr')).to_have_count(4)


def test_optional_integration_into_existing_product_detail(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/?product-integration')
    expect(page.get_by_role('heading',name='Paraméter-összehasonlítás',exact=True)).to_have_count(0)
    page.get_by_role('button',name='Mosógép – paraméterteszt részletei',exact=True).click()
    expect(page.get_by_role('heading',name='Paraméter-összehasonlítás',exact=True)).to_be_visible()


def test_import_workspace_has_optional_job_slot(parameter_page):
    page,state=parameter_page;state['job']['state']='paused';page.goto('http://parameter.test/?import-integration')
    expect(page.get_by_role('heading',name='Beszállítói import',exact=True)).to_be_visible()
    expect(page.get_by_role('heading',name='Paraméter-előkészítés futása',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Feldolgozás folytatása',exact=True)).to_be_visible()


def test_production_bundle_contains_no_mock_transport():
    root=Path(__file__).resolve().parents[2]/'frontend/dist'
    assert root.exists()
    assert not any('__category03b_test__' in f.read_text() for f in root.rglob('*.js'))
    assert not (root/'tests/parameters/index.html').exists()


def test_manual_profile_choice_is_previewed_without_source_changes(parameter_page):
    page,state=parameter_page;original=deepcopy([r['own'] for r in state['rows']]);page.goto('http://parameter.test/')
    page.get_by_text('Paraméterforrás és donorprofilok',exact=True).click()
    page.get_by_role('button',name='Donorprofil felülvizsgálata: Vitatott profil',exact=True).click()
    page.get_by_label('Döntés indoka',exact=True).fill('Kézi profil-felülvizsgálat, nem automatikus kitöltés')
    page.get_by_role('button',name='Paraméterváltozások előnézete',exact=True).click()
    assert not state['writes']
    page.get_by_role('button',name='Előnézet jóváhagyása és alkalmazása',exact=True).click()
    expect(page.get_by_text('Tesztadapter által visszaigazolt mentés.',exact=True)).to_be_visible()
    assert state['profile']=='pending' and original==[r['own'] for r in state['rows']]
    expect(page.get_by_role('button',name='Hiányzó üres helyek előnézete',exact=True)).to_have_count(0)


def test_unsaved_manual_correction_can_be_kept_on_exit(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Paraméterrészlet: Teljesítmény',exact=True).click()
    page.get_by_label('Kézi javított érték',exact=True).fill('2,3')
    page.once('dialog',lambda d:d.dismiss())
    page.get_by_role('button',name='Paraméterrészlet bezárása',exact=True).click()
    expect(page.get_by_label('Kézi javított érték',exact=True)).to_have_value('2,3')
    page.once('dialog',lambda d:d.accept())
    page.get_by_role('button',name='Paraméterrészlet bezárása',exact=True).click()
    expect(page.get_by_label('Kézi javított érték',exact=True)).to_have_count(0)
    assert not state['writes'] and state['rows'][0]['own']['value']['raw']=='2100'


def test_explicit_no_value_list_is_not_load_failure(parameter_page):
    page,state=parameter_page;state['no_values']=True;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Paraméterrészlet: Teljesítmény',exact=True).click()
    expect(page.get_by_text('Ehhez a paraméterhez nincs megengedett értéklista.',exact=True)).to_be_visible()
    expect(page.get_by_role('alert')).to_have_count(0)


def test_import_job_switch_does_not_keep_previous_resumed_state(parameter_page):
    page,state=parameter_page;state['job']={**state['job'],'key':'job-A','state':'paused','message':'Első futás állapota'}
    page.goto('http://parameter.test/?import-integration')
    page.get_by_role('button',name='Feldolgozás folytatása',exact=True).click()
    expect(page.get_by_text('Feldolgozás alatt',exact=False)).to_be_visible()
    state['job']={**state['job'],'key':'job-B','state':'paused','message':'Második futás állapota','canResume':True}
    page.get_by_role('button',name='Teszt: futás váltása',exact=True).click()
    expect(page.get_by_text('Szüneteltetve · Második futás állapota',exact=True)).to_be_visible()
    expect(page.get_by_text('Futás: job-B',exact=True)).to_be_visible()
    expect(page.get_by_text('Futás: job-A',exact=True)).to_have_count(0)


def test_published_extra_slot_states_remain_distinct(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    page.get_by_role('button',name='Következő paraméterek',exact=True).click()
    for label in ('Csak forrásban','Ellenőrzést igényel','Korábbi profilból'):
        expect(page.locator('.parameter-table').get_by_text(label,exact=True)).to_be_visible()
    assert not state['writes']


def test_conflicting_sources_all_remain_visible(parameter_page):
    page,state=parameter_page;page.goto('http://parameter.test/')
    region=page.get_by_role('region',name='További forrás: Másik megőrzött forrásoszlop',exact=True)
    expect(region).to_contain_text('8 kg')
    expect(page.locator('.parameter-table').get_by_text('7 kg',exact=True)).to_be_visible()
    assert state['rows'][2]['own']['value']['raw']=='7'
    assert state['rows'][2]['additionalSources'][0]['value']['raw']=='8'
    assert not state['writes']
