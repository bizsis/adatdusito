"""HELP-01: real production bundle + native FastAPI/SQLite, synthetic data only.

HELP_SCREENSHOTS=1 refreshes the versioned guide images from actual UI controls.
It never uses a VPS, reference database or customer data.
"""
import os
import json
from pathlib import Path
import pytest
from playwright.sync_api import expect
from sqlalchemy.orm import Session
from app.models import User, Tenant
from app.access_models import PermissionException
from app.import_engine import advance
from test_category02d_browser import app_browser
from test_category03d_integration_browser import (
    full_catalog, environment, password_hash, extra_reference_categories,
    extra_reference_parameters, extra_reference_values, overview, snapshot, preview,
)
from test_parameter_api_browser import open_product, apply_preview
from test_classification_api_integration_browser import _fixtures

ROOT = Path(__file__).resolve().parents[2]
ARTICLE_FILES = list((ROOT / "frontend/src/support/articles").glob("*.json"))
ARTICLE_COUNT = len(ARTICLE_FILES)
IMPORT_COUNT = sum(json.loads(p.read_text())["topic"] == "import" for p in ARTICLE_FILES)

@pytest.fixture
def help_catalog(full_catalog):
    f=full_catalog
    me=f.client.get('/api/v1/auth/me').json()
    with Session(f.engine) as db:
        db.get(User,me['user']['id']).name='Segédlet teszt'
        db.get(Tenant,me['tenant_id']).name='Segédlet demó'
        db.commit()
    return f


def open_help(p, keyboard=False):
    menu=p.locator('.sidebar .support-menu summary')
    if keyboard:
        menu.focus();p.keyboard.press('Enter')
    else:menu.click()
    p.locator('.sidebar').get_by_role('link',name='Segédlet',exact=True).click()
    expect(p.get_by_role('heading',name='Segédlet',exact=True)).to_be_visible()
    expect(p.get_by_role('searchbox',name='Keresés a segédletben',exact=True)).to_be_visible()

@pytest.mark.parametrize('width',[390,1440])
def test_help_navigation_search_history_images_and_missing_article(help_catalog,width):
    with app_browser(help_catalog,width=width) as ui:
        p=ui.page
        assert not p.evaluate("performance.getEntriesByType('resource').some(r => r.name.includes('/HelpPage-'))")
        open_help(p,keyboard=width==1440)
        assert p.evaluate("performance.getEntriesByType('resource').some(r => r.name.includes('/HelpPage-'))")
        if width==1440:
            expect(p.get_by_role('navigation',name='Segédlet témakörök').get_by_role('link')).to_have_count(9)
        else:
            expect(p.get_by_role('combobox',name='Témakör',exact=True).locator('option')).to_have_count(9)
        expect(p.locator('.help-article-list li')).to_have_count(ARTICLE_COUNT)
        before=len(ui.calls)
        search=p.get_by_role('searchbox',name='Keresés a segédletben',exact=True)
        search.fill('fejlec elvalaszto')
        expect(p.locator('.help-results')).to_contain_text('CSV/XLSX feltöltése')
        assert not [c for c in ui.calls[before:] if c['path']!='/api/v1/auth/me']
        search.fill('nem-letezo-978943')
        expect(p.get_by_role('heading',name='Nincs találat',exact=True)).to_be_visible()
        p.get_by_role('link',name='Keresés és témakörszűrés törlése',exact=True).click()
        if width==1440:
            p.get_by_role('navigation',name='Segédlet témakörök').get_by_role('link',name='Beszállítók és importálás',exact=True).click()
        else:
            p.get_by_role('combobox',name='Témakör',exact=True).select_option('import')
        expect(p.locator('.help-article-list li')).to_have_count(IMPORT_COUNT)
        p.get_by_role('link',name='CSV/XLSX feltöltése',exact=False).last.click()
        expect(p.get_by_role('heading',name='CSV/XLSX feltöltése',exact=True)).to_be_visible()
        assert p.url.endswith('/segedlet/csv-xlsx-feltoltes?tema=import')
        image=p.get_by_role('button',name='Kép nagyítása:',exact=False).first
        image.click()
        expect(p.get_by_role('dialog',name='Képernyőkép nagyítása')).to_be_visible()
        p.keyboard.press('Escape')
        expect(p.get_by_role('dialog')).to_have_count(0)
        expect(image).to_be_focused()
        p.reload()
        expect(p.get_by_role('heading',name='CSV/XLSX feltöltése',exact=True)).to_be_visible()
        p.get_by_role('navigation',name='Kapcsolódó útmutatók').get_by_role('link',name='Oszlopok megfeleltetése',exact=False).click()
        expect(p.get_by_role('heading',name='Oszlopok megfeleltetése',exact=True)).to_be_visible()
        p.go_back()
        expect(p.get_by_role('heading',name='CSV/XLSX feltöltése',exact=True)).to_be_visible()
        assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
        p.goto('http://category02d.test/#/segedlet/nem-letezo-cikk')
        expect(p.get_by_role('heading',name='A cikk nem található')).to_be_visible()
        p.get_by_role('link',name='Vissza a témakörökhöz',exact=True).click()
        expect(p.locator('.help-article-list li')).to_have_count(ARTICLE_COUNT)
        p.locator('.sidebar nav').get_by_role('button',name='Termékadatok',exact=True).click()
        expect(p.get_by_role('heading',name='Termékadatok',exact=True)).to_be_visible()
        assert '#/segedlet' not in p.url
        assert not [c for c in ui.calls[before:] if c['method'] not in ('GET','HEAD')]


def test_help_available_to_readonly_user_and_preserves_auth_boundary(help_catalog):
    _fixtures.login(help_catalog.client,'processor@example.hu')
    me=help_catalog.client.get('/api/v1/auth/me').json()
    with Session(help_catalog.engine) as db:
        for permission in me['permissions']:
            db.add(PermissionException(user_id=me['user']['id'],context=f"tenant:{me['tenant_id']}",permission=permission,allowed=False))
        db.commit()
    assert help_catalog.client.get('/api/v1/auth/me').json()['permissions']==[]
    with app_browser(help_catalog,width=390) as ui:
        open_help(ui.page)
        expect(ui.page.locator('.help-article-list li')).to_have_count(ARTICLE_COUNT)
        ui.page.goto('http://category02d.test/#/segedlet/jogosultsagok')
        expect(ui.page.get_by_role('heading',name='Felhasználók és jogosultságok',exact=True)).to_be_visible()
        assert not [c for c in ui.calls if c['method'] not in ('GET','HEAD')]
    help_catalog.client.post('/api/v1/auth/logout')
    with app_browser(help_catalog) as ui:
        ui.page.goto('http://category02d.test/#/segedlet/belepes-munkaterulet')
        expect(ui.page.get_by_role('button',name='Bejelentkezés →',exact=True)).to_be_visible()
        expect(ui.page.locator('.help-page')).to_have_count(0)


def test_record_current_ui_screenshots_and_existing_workflows(help_catalog):
    """Also a regression smoke: import/classification/parameters/bulk/export still open."""
    f=help_catalog
    def shot(locator,name):
        expect(locator).to_be_visible()
        if os.environ.get('HELP_SCREENSHOTS')=='1':
            locator.screenshot(path=str(ROOT/f'frontend/public/help/images/{name}.png'),animations='disabled')
    with app_browser(f,width=1440) as ui:
        p=ui.page
        expect(p.get_by_label('Munkaterület',exact=True)).to_contain_text('Segédlet demó')
        shot(p.locator('.workspace'),'munkaterulet')
        p.locator('.sidebar nav').get_by_role('button',name='Beszállítói import',exact=True).click()
        p.get_by_label('Új beszállító neve',exact=True).fill('Segédlet demóbeszállító')
        shot(p.locator('main > section.card').first,'beszallito')
        with p.expect_response(lambda r: r.url.endswith('/api/v1/imports/suppliers') and r.request.method == 'POST') as created:
            p.get_by_role('button',name='Beszállító létrehozása',exact=True).click()
        expect(p.locator('main > section.card').first.locator('select').first).to_have_value(str(created.value.json()['id']))
        shot(p.locator('main > section.card').first,'feltoltes')
        with p.expect_response(lambda r: r.url.endswith('/api/v1/imports/runs') and r.request.method == 'POST') as uploaded:
            p.get_by_label('CSV/XLSX fájl',exact=True).set_input_files({'name':'segedlet-demo.csv','mimeType':'text/csv','buffer':'Cikkszám;Terméknév;Kategória;EAN\nDEMO-001;Demó mosógép;Háztartás / Mosógépek;5901234123457\n'.encode()})
        # Actual worker function on isolated synthetic rows, with the real UI polling it.
        run=uploaded.value.json()['id']
        with Session(f.engine) as db:advance(db,run)
        expect(p.get_by_role('button',name='Megfeleltetés jóváhagyása és feldolgozás',exact=True)).to_be_visible(timeout=15000)
        table=p.locator('table').filter(has_text='Eredeti oszlop')
        shot(table,'oszlopok')
        approval=p.locator('form').filter(has=p.get_by_role('button',name='Megfeleltetés jóváhagyása és feldolgozás',exact=True))
        shot(approval,'import-jovahagyas')
        p.locator('.sidebar nav').get_by_role('button',name='Termékadatok',exact=True).click()
        p.get_by_role('button',name='Mosógép A részletei',exact=True).click()
        p.get_by_role('button',name='Besorolás szerkesztése',exact=True).click()
        with p.expect_response(lambda r: '/workspace/internal-categories?' in r.url and 'q=El' in r.url):
            p.get_by_label('Kategória keresése',exact=True).fill('Elöltöltős')
        expect(p.get_by_role('button',name='Kiválasztás: Elöltöltős mosógépek',exact=True)).to_be_visible()
        p.get_by_role('button',name='Kiválasztás: Elöltöltős mosógépek',exact=True).click()
        p.get_by_label('Módosítás indoka',exact=True).fill('Ellenőrzött demótermék besorolása.')
        panel=p.locator('section.card').filter(has=p.get_by_role('heading',name='Belső besorolás módosítása',exact=True))
        shot(panel,'kategorizalas')
        # Leave unsaved category edit; navigate using the already implemented parameter flow.
        p.locator('.sidebar nav').get_by_role('button',name='Beszállítói import',exact=True).click()
        open_product(ui);apply_preview(p)
        p.get_by_role('button',name='Paraméterrészlet: Teljesítmény (kW)',exact=True).click()
        shot(p.get_by_role('region',name='Valódi paraméterhely szerkesztése',exact=True),'kezi-parameter')
        p.locator('.sidebar nav').get_by_role('button',name='Beszállítói import',exact=True).click()
        overview(ui);snapshot(p);preview(f,p)
        shot(p.get_by_role('region',name='Rögzített termékkör és előkészítési jóváhagyás',exact=True),'tomeges')
        p.locator('.sidebar nav').get_by_role('button',name='Export',exact=True).click()
        expect(p.get_by_role('heading',name='Webáruházmotorok → Exportmezők',exact=True)).to_be_visible()
        for i,(key,label,internal) in enumerate([('cikkszam','Cikkszám','sku'),('nev','Terméknév','name')]):
            p.get_by_role('button',name='Mező hozzáadása',exact=True).click()
            p.get_by_label(f'key {i}',exact=True).fill(key)
            p.get_by_label(f'label {i}',exact=True).fill(label)
            p.get_by_label(f'internal_field {i}',exact=True).fill(internal)
        shot(p.locator('main > section.card').first,'exportprofil')


def test_mobile_topic_and_search_use_current_url_when_hashchange_is_delayed(help_catalog):
    """Deterministic regression: native hash navigation precedes its event/React render.

    Chromium can dispatch select/change before the queued hashchange handler.
    Hold that handler to reproduce the timing without altering any response data.
    """
    with app_browser(help_catalog,width=390) as ui:
        p=ui.page
        p.add_init_script("""window.__holdHelpHash = false;
            window.addEventListener('hashchange', event => {
                if (window.__holdHelpHash) event.stopImmediatePropagation();
            }, true);""")
        p.reload()
        open_help(p)
        search=p.get_by_role('searchbox',name='Keresés a segédletben',exact=True)
        search.fill('nem-letezo-978943')
        expect(p.get_by_role('heading',name='Nincs találat',exact=True)).to_be_visible()
        p.evaluate('window.__holdHelpHash = true')
        p.get_by_role('link',name='Keresés és témakörszűrés törlése',exact=True).click()
        assert p.url.endswith('#/segedlet')
        topic=p.get_by_role('combobox',name='Témakör',exact=True)
        topic.select_option('import')
        expect(p.locator('.help-article-list li')).to_have_count(IMPORT_COUNT)
        expect(search).to_have_value('')
        expect(topic).to_have_value('import')
        assert p.url.endswith('#/segedlet?tema=import')
        # Reverse direction: the URL clears the topic before React sees the event.
        p.evaluate("location.hash = '#/segedlet'")
        search.fill('zárolás')
        expect(p.locator('.help-results')).to_contain_text('Paraméterek kézi javítása és zárolása')
        expect(topic).to_have_value('')
        assert 'tema=' not in p.url
        p.evaluate("window.__holdHelpHash = false; window.dispatchEvent(new HashChangeEvent('hashchange'))")
        expect(p.locator('.help-results')).to_contain_text('Paraméterek kézi javítása és zárolása')
