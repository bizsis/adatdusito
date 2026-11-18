"""HELP-02: user-manual evidence from the real UI and isolated synthetic APIs.

HELP_SCREENSHOTS=1 records pictures; normal CI asserts the same states without
writing images. Never records TOTP setup, recovery codes or external OAuth.
"""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from sqlalchemy.orm import Session
from app.models import User
from test_help_browser import (
    help_catalog, full_catalog, environment, password_hash,
    extra_reference_categories, extra_reference_parameters, extra_reference_values,
    open_help,
)
from test_category02d_browser import app_browser
from test_classification_api_integration_browser import _fixtures
from test_category03d_integration_browser import overview, snapshot, preview, finish, apply_bulk
from test_parameter_api_browser import open_product, apply_preview, manual

ROOT=Path(__file__).resolve().parents[2]

def shot(locator,name):
    expect(locator).to_be_visible()
    if os.environ.get('HELP_SCREENSHOTS')=='1':
        locator.evaluate("e => e.scrollIntoView({block:'start'})")
        box=locator.bounding_box()
        assert box
        scroll=locator.page.evaluate('({x:scrollX,y:scrollY})')
        locator.page.screenshot(path=str(ROOT/f'frontend/public/help/images/{name}.png'),
            full_page=True, clip={'x':box['x']+scroll['x'],'y':box['y']+scroll['y'],
                                  'width':box['width'],'height':min(box['height'],1400)},animations='disabled')

def nav(p,name):
    p.locator('.sidebar nav').get_by_role('button',name=name,exact=True).click()
    expect(p.locator('main h1')).to_have_text(name)

def panel(p,title):
    return p.locator('section.card').filter(has=p.get_by_role('heading',name=title,exact=True))

@pytest.mark.parametrize('width',[390,1440])
def test_long_manual_contents_tables_focus_zoom_and_search(help_catalog,width):
    with app_browser(help_catalog,width=width) as ui:
        p=ui.page;open_help(p)
        p.get_by_role('searchbox',name='Keresés a segédletben',exact=True).fill('cp1250')
        p.get_by_role('link',name='CSV/XLSX feltöltése',exact=False).last.click()
        title=p.get_by_role('heading',name='CSV/XLSX feltöltése',exact=True)
        expect(title).to_be_focused()
        assert title.evaluate("e => getComputedStyle(e).outlineStyle")=='none'
        assert title.evaluate("e => getComputedStyle(e).boxShadow")=='none'
        url=p.url
        p.get_by_role('navigation',name='A cikk tartalma',exact=True).get_by_role('button',name='Mezők, állapotok és gombok',exact=True).click()
        expect(p.get_by_role('heading',name='Mezők, állapotok és gombok',exact=True)).to_be_focused()
        assert p.url==url
        expect(p.get_by_role('table')).to_contain_text('cp1250')
        assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
        pic=p.get_by_role('button',name='Kép nagyítása:',exact=False).first
        pic.click();expect(p.get_by_role('dialog')).to_be_visible()
        p.keyboard.press('Escape');expect(pic).to_be_focused()
        if width==390:shot(p.locator('.help-article'),'manual-mobil')
        else:shot(p.locator('.help-article'),'manual-asztali')
        assert not [c for c in ui.calls if c['method'] not in ('GET','HEAD')]


def test_admin_manual_real_screens_without_secrets(help_catalog):
    f=help_catalog
    _fixtures.login(f.client)
    me=f.client.get('/api/v1/auth/me').json()
    with Session(f.engine) as db:
        db.get(User,me['user']['id']).name='Demó rendszeradmin'
        db.commit()
    with app_browser(f) as ui:
        p=ui.page
        shot(p.locator('main'),'attekintes')
        nav(p,'Ügyfelek');expect(p.locator('.tenant-grid h2').first).to_be_visible()
        shot(p.locator('main'),'ugyfelek')
        p.get_by_role('button',name='+ Új ügyfél',exact=True).click()
        expect(p.get_by_role('heading',name='Új ügyfél',exact=True)).to_be_visible()
        p.get_by_label('Ügyfél neve',exact=True).fill('Segédlet próbaügyfél')
        shot(p.get_by_role('dialog'),'ugyfel-letrehozas')
        p.get_by_role('button',name='Bezárás',exact=True).click()
        nav(p,'Rendszerbeállítások')
        for tab,name,heading in [
            ('Általános','beallitas-altalanos','Általános'),
            ('SMTP / Levelezés','beallitas-smtp','SMTP / Levelezés'),
            ('Hitelesítés és bejelentkezés','beallitas-auth','Hitelesítés és bejelentkezés'),
            ('Kétfaktoros hitelesítés','beallitas-mfa','Kétfaktoros hitelesítés'),
            ('Biztonsági szabályok','beallitas-biztonsag','Biztonsági szabályok'),
            ('Kategóriabesorolás','beallitas-kuszob','Kategóriabesorolás'),
        ]:
            p.get_by_role('tab',name=tab,exact=True).click()
            expect(p.get_by_role('tab',name=tab,exact=True)).to_have_attribute('aria-selected','true')
            expect(p.locator('main section.card')).to_be_visible()
            assert not p.locator('main input[type=password]').evaluate_all('(nodes)=>nodes.some(n=>n.value)')
            shot(p.locator('main'),'beallitas-'+name.removeprefix('beallitas-'))
        nav(p,'Rendszerhozzáférések')
        expect(p.locator('.account-create summary')).to_be_visible()
        shot(p.locator('main'),'rendszerfelhasznalok')
        p.get_by_role('button',name='Szerepkörök',exact=True).click()
        expect(p.get_by_role('button',name='Új szerepkör',exact=True)).to_be_visible()
        shot(p.locator('main .table-wrap').first,'szerepkorok')
        p.get_by_role('button',name='Új szerepkör',exact=True).click()
        shot(p.locator('main'),'szerepkor-szerkeszto')
        p.get_by_role('button',name='Jogosultsági katalógus',exact=True).click()
        expect(p.locator('main details summary').filter(has_text='Import').first).to_be_visible()
        shot(p.locator('main details').filter(has=p.locator('summary').filter(has_text='Import')).first,'jogkatalogus')
        p.get_by_role('button',name='Meghívások',exact=True).click()
        expect(p.get_by_role('button',name='Meghívás küldése',exact=True)).to_be_visible()
        shot(p.locator('main'),'meghivo-urlap')
        p.get_by_role('button',name='Biztonság',exact=True).click()
        expect(p.get_by_role('heading',name='Hitelesítés és 2FA',exact=True)).to_be_visible()
        expect(panel(p,'TOTP és helyreállítási kódok')).to_contain_text('Nincs aktív TOTP-eszköz')
        shot(panel(p,'Saját fiók és újraazonosítás'),'sajat-fiok')
        shot(panel(p,'TOTP és helyreállítási kódok'),'totp-allapot')
        shot(panel(p,'Passkey hitelesítőeszközök'),'passkey-allapot')
        shot(panel(p,'Google-fiók összekapcsolása'),'google-allapot')
        expect(panel(p,'Aktív munkamenetek').locator('tbody tr').first).to_be_visible()
        shot(panel(p,'Aktív munkamenetek'),'munkamenetek')
        # No setup click: QR, secret, recovery and approval tokens are never generated.
        shot(panel(p,'Felügyelt TOTP-helyreállítás'),'admin-helyreallitas')
        p.get_by_role('button',name='Jelszó',exact=True).click()
        shot(p.get_by_role('dialog'),'jelszocsere')
        p.get_by_role('button',name='Bezárás',exact=True).click()
        nav(p,'Napló / Audit');expect(p.get_by_role('heading',name='Adminisztrációs napló',exact=True)).to_be_visible()
        shot(p.locator('main'),'audit')
        assert not [c for c in ui.calls if c['method'] not in ('GET','HEAD')]


def test_tenant_manual_parameters_bulk_and_approval_evidence(help_catalog):
    f=help_catalog
    with app_browser(f) as ui:
        p=ui.page
        nav(p,'Munkatársak és hozzáférések')
        expect(p.get_by_role('button',name='Munkatársak',exact=True)).to_be_visible()
        shot(p.locator('main'),'munkatarsak')
        p.get_by_role('button',name='Cégek és webáruházak',exact=True).click()
        expect(p.get_by_role('heading',name='Cégek',exact=True)).to_be_visible()
        shot(p.locator('main'),'cegek-webaruhazak')
        nav(p,'Import')
        p.get_by_label('Webshopmotor',exact=True).select_option('unas')
        expect(p.get_by_role('heading',name='Beszállító és fájl')).to_be_visible()
        expect(p.get_by_role('region',name='UNAS-célmezők')).to_have_count(0)
        nav(p,'Termékadatok');expect(p.get_by_role('button',name='Mosógép A részletei',exact=True)).to_be_visible()
        shot(p.locator('main'),'termeklista')
        p.get_by_role('tab',name='Saját kategóriatérkép és profilok',exact=True).click()
        shot(p.locator('main'),'kategoriameterkep')
        p.get_by_role('tab',name='Terméklista',exact=True).click()
        open_product(ui);apply_preview(p)
        shot(p.locator('.parameter-table'),'parameterallapotok')
        p.get_by_text('Tenant- és globális aliasszabályok',exact=True).click()
        shot(p.get_by_role('region',name='Aliasszabályok',exact=True),'aliasok')
        shot(p.get_by_role('region',name='Valódi paraméterfutások',exact=True),'parameter-futas')
        overview(ui);snapshot(p,page=True)
        shot(p.get_by_role('region',name='Rögzített termékkör és előkészítési jóváhagyás',exact=True),'tomeges-kijeloles')
        preview(f,p)
        p.get_by_role('button',name='Előkészítési ellenőrzés',exact=True).click()
        expect(p.get_by_text('Sorban áll',exact=False)).to_be_visible();finish(f,p)
        shot(p.get_by_role('region',name='Rögzített termékkör és előkészítési jóváhagyás',exact=True),'elokeszitesi-ellenorzes')
        p.get_by_label('Tömeges döntés indoka',exact=True).fill('Demó előkészítés hiányainak rögzítése')
        p.get_by_role('button',name='Előkészítési jóváhagyás áttekintése',exact=True).click()
        shot(p.get_by_role('region',name='Rögzített termékkör és előkészítési jóváhagyás',exact=True),'elokeszitesi-megerosites')
        p.get_by_role('button',name='Tömeges döntés megerősítése',exact=True).click()
        expect(p.get_by_role('heading',name='Előkészítési jóváhagyás #1',exact=True)).to_be_visible()
        shot(p.get_by_role('region',name='Jóváhagyás 1 részletei',exact=True),'elokeszitesi-jovahagyas')

def test_reference_tree_and_parameter_manual_evidence(environment):
    # Import only the tiny synthetic SQLite reference fixture, never a real source.
    from types import SimpleNamespace
    from app.catalog_import import SourceReader, import_catalog, activate
    client, target, source, statements = environment
    version=import_catalog(target, SourceReader(source), pause_ms=0)
    activate(target, version)
    _fixtures.login(client)
    f=SimpleNamespace(client=client,engine=target,statements=statements)
    with app_browser(f) as ui:
        p=ui.page
        nav(p,'Kategóriák')
        expect(p.locator('.tree-row').filter(has_text='Főcsoport')).to_have_count(13)
        shot(p.locator('main'),'kozos-kategoriafa')
        with p.expect_response(lambda r:'/reference/navigation?' in r.url and 'q=' in r.url):
            p.get_by_label('Kategóriakeresés',exact=True).fill('Elöltöltős')
        expect(p.locator('.tree-name').filter(has_text='Elöltöltős').first).to_be_visible()
        p.locator('.tree-name').filter(has_text='Elöltöltős').first.click()
        expect(p.get_by_role('heading',name='Elöltöltős mosógépek',exact=True)).to_be_visible()
        shot(p.locator('main .detail'),'kategoria-parameterek')
        nav(p,'Paraméterkereső')
        expect(p.locator('main tbody tr').first).to_be_visible()
        shot(p.locator('main'),'parameterkereso')
        p.get_by_role('button',name='Megnyitás →',exact=True).first.click()
        expect(p.get_by_label('Keresés az értékekben',exact=True)).to_be_visible()
        shot(p.locator('main section.card').last,'megengedett-ertekek')


def test_follow_written_demo_supplier_import_classification_missing_and_grants(help_catalog):
    """Execute the documented path, using UI writes and real worker functions."""
    from app.import_engine import advance
    f=help_catalog
    # Classification starts with an existing product. The Import UI now ends at
    # template save, so create the guide's demo product through the retained API.
    source = 'Cikkszám;Terméknév;Kategória;EAN\nDEMO-001;Demó mosógép;Háztartás / Mosógépek;5901234123457\n'.encode()
    created = f.client.post('/api/v1/imports/runs', data={'supplier_id': f.supplier},
                            files={'file': ('segedlet-demo.csv', source)})
    assert created.status_code == 200
    run = created.json()['id']
    with Session(f.engine) as db:advance(db,run)
    approved = f.client.post(f'/api/v1/imports/runs/{run}/approve', json={
        'name':'Segédlet CSV v1', 'identity_field':'sku',
        'mapping':{'0':'sku','1':'name','2':'category','3':'gtin'},
    })
    assert approved.status_code==200, approved.text
    with Session(f.engine) as db:advance(db,run)
    assert f.client.get(f'/api/v1/imports/runs/{run}').json()['state']=='completed'
    with app_browser(f) as ui:
        p=ui.page
        nav(p,'Termékadatok')
        p.get_by_label('Termék keresése',exact=True).fill('DEMO-001')
        p.get_by_role('button',name='Demó mosógép részletei',exact=True).click()
        p.get_by_role('button',name='Besorolás szerkesztése',exact=True).click()
        p.get_by_label('Kategória keresése',exact=True).fill('Elöltöltős')
        p.get_by_role('button',name='Kiválasztás: Elöltöltős mosógépek',exact=True).click()
        p.get_by_label('Módosítás indoka',exact=True).fill('Ellenőrzött demótermék besorolása.')
        p.get_by_role('button',name='Módosítások előnézete',exact=True).click()
        p.get_by_role('button',name='Módosítás mentése',exact=True).click()
        expect(p.get_by_text('A kézi besorolás mentve és zárolva.',exact=True)).to_be_visible()
        # Reopen after refreshed product list, as the manual instructs.
        open_product(ui,name='Demó mosógép')
        apply_preview(p)
        expect(p.locator('.parameter-table')).to_contain_text('Hiányzó hely')
        shot(p.locator('.parameter-table'),'hianyzo-parameterek')
        original=f.client.get('/api/v1/workspace/products').json()['items']
        demo=next(row for row in original if row['fields']['sku']=='DEMO-001')
        assert demo['source_category']['path']=='Háztartás / Mosógépek'
        assert demo['classification']['locked']
        assert any(s["mandatory"] and s["state"]=="missing" for s in f.client.get(f"/api/v1/workspace/products/{demo['id']}/parameters").json()["slots"])
    # Same manual, lower grant set: no apply/approve buttons should be offered.
    _fixtures.login(f.client,'processor@example.hu')
    with app_browser(f) as ui:
        overview(ui);p=ui.page;snapshot(p);preview(f,p)
        expect(p.get_by_role('button',name='Tömeges alkalmazás áttekintése',exact=True)).to_have_count(0)
        expect(p.get_by_role('button',name='Előkészítési jóváhagyás áttekintése',exact=True)).to_have_count(0)
        shot(p.get_by_role('region',name='Rögzített termékkör és előkészítési jóváhagyás',exact=True),'tomeges-olvasasi-jog')


def test_manual_real_revision_conflict_and_recovery_evidence(help_catalog):
    f=help_catalog
    with app_browser(f) as ui:
        p=ui.page;open_product(ui);apply_preview(p)
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        p.get_by_label('Kézi művelet',exact=True).select_option('set')
        p.get_by_label('Új kézi érték',exact=True).fill('2100')
        p.get_by_label('Kézi döntés indoka',exact=True).fill('Demó revízióütközés vizsgálata')
        p.get_by_role('button',name='Kézi döntés áttekintése',exact=True).click()
        current=f.client.get(f'/api/v1/workspace/products/{f.pid}').json()
        r=f.client.patch(f'/api/v1/workspace/products/{f.pid}/classification',json={
            'expected_revision':current['revision'],'action':'set',
            'navigation_node_id':f.helper.WASHER,'reason':'Másik admin időközbeni döntése'})
        assert r.status_code==200,r.text
        with p.expect_response(lambda r:'/parameters/' in r.url and r.request.method=='PATCH') as failed:
            p.get_by_role('button',name='Kézi döntés mentése',exact=True).click()
        assert failed.value.status==409
        expect(p.get_by_role('button',name='Friss helyadatok betöltése',exact=True)).to_be_visible()
        shot(p.get_by_role('region',name='Valódi paraméterhely szerkesztése',exact=True),'revizio-utkozes')
        assert len([c for c in ui.calls if '/parameters/' in c['path'] and c['method']=='PATCH'])==1
