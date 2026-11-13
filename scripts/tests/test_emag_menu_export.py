"""Browser DOM tests use a routed synthetic eMAG page; no live-site requests."""

import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CORE = (ROOT / "scripts/emag_menu/menu_capture.js").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location(
    "emag_menu_export", ROOT / "scripts/export_emag_menu.py"
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        executable = shutil.which("chromium")
        browser = p.chromium.launch(
            headless=True, **({"executable_path": executable} if executable else {})
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1800, "height": 1100})
    page = context.new_page()
    context.route(
        "https://www.emag.hu/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html lang="hu"><body></body></html>'
        ),
    )
    page.goto("https://www.emag.hu/")
    yield page
    context.close()


def fixture(page, count=13, shared=False):
    page.evaluate(CORE)
    labels = page.evaluate("AdatdusitoMenuCapture.expectedRoots")[:count]
    page.evaluate(
        r"""({labels,shared})=>{
      document.body.innerHTML=`<style>body{margin:0}.megamenu{position:relative;width:1400px;height:850px;background:white}nav{position:absolute;width:310px}nav a{display:block;height:45px}.panel{position:absolute;left:330px;top:0;width:900px;height:800px;background:white}.panel a{display:block;padding:10px}</style><div class="megamenu"><nav></nav></div><div id="products"><a href="/not-menu/c/555">Nem menühivatkozás</a></div>`;
      const menu=document.querySelector('.megamenu'),nav=menu.querySelector('nav');
      labels.forEach((name,i)=>{
        const a=document.createElement('a');a.textContent=name;a.href='/root-'+i+'?session=do-not-export';a.setAttribute('aria-controls','panel-'+(shared?0:i));nav.append(a);
        if(!shared||i===0){const panel=document.createElement('section');panel.id='panel-'+i;panel.className='panel';panel.hidden=i!==0;panel.innerHTML=`<section><h3>Alcsoport ${i}</h3><a data-category-id="79" href="/child-${i}/c/79?tracking=private-value">Alkategória ${i}</a><a href="/brand-${i}/b">Brand shop ${i}</a><form><input value="password-must-not-export"></form><script>window.private_value='secret';<\/script><!--private comment--></section>`;menu.append(panel);}
        a.addEventListener('mouseover',()=>{menu.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==a.getAttribute('aria-controls'));});
      });
    }""",
        {"labels": labels, "shared": shared},
    )
    return labels


def capture(page, label):
    page.get_by_role("link", name=label, exact=True).hover()
    return page.evaluate("(label)=>AdatdusitoMenuCapture.capture(label)", label)


def test_all_thirteen_groups_captured_without_canonical_id_inference(page):
    labels = fixture(page)
    for i, label in enumerate(labels):
        group = capture(page, label)
        assert (
            group["name"] == label and group["association_evidence"] == "aria_controls"
        )
        assert group["association_status"] == "needs_review"
        assert [r["name"] for r in group["links"]] == [
            f"Alkategória {i}",
            f"Brand shop {i}",
        ]
        assert (
            group["links"][0]["explicit_source_attributes"]["data-category-id"] == "79"
        )
        assert all(r["canonical_emag_id"] is None for r in group["links"])
        assert group["sections"][0]["name"] == f"Alcsoport {i}"
    report = page.evaluate("AdatdusitoMenuCapture.report()")
    assert report["captured_root_count"] == 13 and not report["missing_roots"]
    assert report["all_expected_panels_captured"]
    assert (
        not report["full_category_tree_verified"]
        and not report["automatic_marketplace_mapping"]
    )
    assert not report["duplicate_panel_contents"]


def test_missing_roots_never_fabricated_and_dom_order_is_preserved(page):
    labels = fixture(page, count=2)
    page.evaluate(
        "document.querySelector('nav').prepend(document.querySelector('nav').lastElementChild)"
    )
    assert page.evaluate("AdatdusitoMenuCapture.discover().map(r=>r.name)") == list(
        reversed(labels)
    )
    capture(page, labels[0])
    report = page.evaluate("AdatdusitoMenuCapture.report()")
    assert len(report["root_groups"]) == 1 and len(report["missing_roots"]) == 12
    assert not report["all_expected_panels_captured"]


def test_duplicate_panels_are_reported_as_unverified(page):
    labels = fixture(page, count=2, shared=True)
    for label in labels:
        capture(page, label)
    report = page.evaluate("AdatdusitoMenuCapture.report()")
    assert report["duplicate_panel_contents"] == [labels]
    assert report["collection_needs_review"]


def test_evidence_excludes_query_values_forms_scripts_comments_and_product_cards(page):
    labels = fixture(page, count=1)
    page.evaluate(
        "document.cookie='session_cookie=do-not-export'; localStorage.setItem('password','do-not-export')"
    )
    group = capture(page, labels[0])
    serialized = json.dumps(group)
    for forbidden in [
        "password-must-not-export",
        "private-value",
        "private comment",
        "window.private_value",
        "do-not-export",
        "Nem menühivatkozás",
    ]:
        assert forbidden not in serialized
    assert group["links"][0]["query_keys"] == ["tracking"]
    assert group["links"][0]["url"] == "https://www.emag.hu/child-0/c/79"
    assert (
        "<form" not in group["html_evidence"]
        and "<script" not in group["html_evidence"]
    )


def test_no_body_fallback_and_capture_is_domain_constrained(page):
    labels = fixture(page, count=1)
    page.evaluate("document.querySelector('.panel').remove()")
    with pytest.raises(Exception, match="Nem azonosítható"):
        capture(page, labels[0])
    page.goto("about:blank")
    page.evaluate(CORE)
    with pytest.raises(Exception, match="emag.hu HTTPS"):
        page.evaluate("AdatdusitoMenuCapture.capture('TV és szórakozás')")


def test_manual_hotkey_and_json_download(page, tmp_path):
    labels = fixture(page, count=1)
    page.get_by_role("link", name=labels[0], exact=True).hover()
    page.keyboard.press("Alt+Shift+m")
    assert page.evaluate("AdatdusitoMenuCapture.report().captured_root_count") == 1
    with page.expect_download() as download:
        page.keyboard.press("Alt+Shift+e")
    target = tmp_path / "browser.json"
    download.value.save_as(target)
    report = json.loads(target.read_text())
    assert len(report["root_groups"]) == 1 and not report["database_writes"]


def test_zip_contains_only_generated_public_evidence(tmp_path):
    report = {
        "root_groups": [
            {"name": "TV és szórakozás", "html_evidence": "<a>Televíziók</a>"}
        ],
        "full_category_tree_verified": False,
    }
    archive = exporter.save_report(tmp_path, report, [], {"status": 200}, "synthetic")
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {
            "01-menu.html",
            "OLVASS_EL.txt",
            "emag-menu-export.json",
        }
        data = json.loads(z.read("emag-menu-export.json"))
        assert len(data["root_groups"][0]["html_sha256"]) == 64
        assert "html_evidence" not in data["root_groups"][0]
        assert (
            data["execution_location"] == "operator_machine"
            and not data["reference_database_writes"]
        )


def test_details_collector_preserves_evidence_not_secret_fields(page):
    spec = importlib.util.spec_from_file_location(
        "menu_details", ROOT / "scripts/collect_emag_menu_details.py"
    )
    details = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(details)
    clean = details.sanitized_payload(
        {
            "data": {
                "id": 79,
                "name": "Kategória",
                "token": "not-exported",
                "user": {"name": "Private"},
                "url": "https://www.emag.hu/category/c?token=secret",
            },
            "password": "not-exported",
        }
    )
    assert "token" not in json.dumps(clean) and "Private" not in json.dumps(clean)
    page.evaluate(
        """()=>{document.body.innerHTML='<script type="application/json">'+JSON.stringify({category:{id:79},user:{id:123,password:'not-exported'}})+'</scr'+'ipt>'; }"""
    )
    evidence = page.evaluate(details.IDENTITY_EVIDENCE)
    assert evidence["identifiers"] == [
        {"json_path": "script[0].category.id", "value": "79", "namespace": "unverified"}
    ]
    assert len(evidence["source_document_hashes"][0]["sha256"]) == 64
    assert not evidence["automatic_marketplace_mapping"]
    page.evaluate(
        """()=>{const s=document.createElement('script');s.type='application/ld+json';s.textContent=JSON.stringify({'@type':'BreadcrumbList',itemListElement:[{name:'Forrás-URL nélkül',position:1}]});document.body.append(s)}"""
    )
    assert (
        page.evaluate(details.IDENTITY_EVIDENCE)["breadcrumbs"][0]["items"][0]["url"]
        is None
    )


def test_clean_html_does_not_rewrite_same_name_different_source_id(page):
    labels = fixture(page, count=1)
    page.evaluate(
        "document.querySelector('.panel a:nth-of-type(2)').textContent='Alkategória 0'"
    )
    group = capture(page, labels[0])
    assert "https://www.emag.hu/child-0/c/79" in group["html_evidence"]
    assert "https://www.emag.hu/brand-0/b" in group["html_evidence"]


def details_module():
    spec = importlib.util.spec_from_file_location(
        "menu_details_recovery", ROOT / "scripts/collect_emag_menu_details.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_details_uses_visible_duplicate_trigger_instead_of_hidden_first(page):
    module = details_module()
    fixture(page, count=2)
    page.evaluate("""()=>{
      document.querySelector('nav').style.display='none';
      const hidden=document.createElement('button');hidden.textContent='Kategóriák';hidden.style.display='none';document.body.prepend(hidden);
      const button=document.createElement('button');button.textContent='Kategóriák';button.style='position:fixed;left:10px;top:920px';
      button.onmouseover=()=>{document.querySelector('nav').style.display='block';document.querySelectorAll('.panel').forEach(p=>{p.classList.add('megamenu-details-department');p.setAttribute('data-id',p.id);p.querySelectorAll('a').forEach(a=>a.classList.add('megamenu-item'))});document.querySelector('.panel').classList.add('megamenu-visible')};document.body.append(button);
    }""")
    page.evaluate(
        "document.querySelectorAll('nav a').forEach(a=>a.addEventListener('mouseover',()=>document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('megamenu-visible',!p.hidden))))"
    )
    result = {"menu_panels": [], "errors": []}
    module.collect_menu(page, result)
    assert len(result["menu_panels"]) == 2 and not result["errors"]
    assert result["diagnostics"]["category_triggers"][0]["visible"] is False


def test_details_menu_failure_does_not_discard_requested_category_evidence(page):
    from urllib.robotparser import RobotFileParser

    module = details_module()
    fixture(page, count=1)
    page.evaluate(
        "document.querySelector('nav').style.display='none';document.body.insertAdjacentHTML('afterbegin','<button style=\"display:none\">Kategóriák</button>')"
    )
    result = {"menu_panels": [], "category_pages": [], "errors": []}
    module.collect_menu(page, result)
    assert result["errors"][0]["phase"] == "menu_open"
    robots = RobotFileParser()
    robots.parse(["User-agent: *", "Allow: /"])
    page.context.route(
        "https://www.emag.hu/televiziok/c",
        lambda route: route.fulfill(
            content_type="text/html",
            body='<script type="application/json">{"category":{"id":79}}</script>',
        ),
    )
    module.collect_category_pages(
        page, ["https://www.emag.hu/televiziok/c"], robots, result
    )
    assert len(result["category_pages"]) == 1
    assert result["category_pages"][0]["identifiers"][0]["value"] == "79"
    assert result["category_pages"][0]["identifiers"][0]["namespace"] == "unverified"
    assert len(result["errors"]) == 1


def test_details_manual_capture_needs_no_hover_trigger(page, monkeypatch):
    module = details_module()
    fixture(page, count=1)
    page.evaluate(
        """()=>{const panel=document.querySelector('.panel');panel.classList.add('megamenu-details-department','megamenu-visible');panel.setAttribute('data-id','114');panel.querySelector('h3').classList.add('megamenu-details-department-title');panel.querySelectorAll('a').forEach(a=>a.classList.add('megamenu-item'));}"""
    )
    monkeypatch.setattr(
        module,
        "visible_text",
        lambda *a: (_ for _ in ()).throw(AssertionError("Manual must not auto-hover")),
    )
    result = {"menu_panels": [], "errors": []}
    module.collect_menu(
        page,
        result,
        manual=True,
        prompt=lambda message: page.keyboard.press("Alt+Shift+m"),
    )
    assert len(result["menu_panels"]) == 1 and not result["errors"]
    assert result["menu_panels"][0]["dom"][0]["department_id"] == "114"


def test_details_one_root_failure_keeps_other_root_data(page, monkeypatch):
    module = details_module()
    labels = fixture(page, count=2)
    page.evaluate(
        "document.querySelectorAll('.panel').forEach(p=>{p.classList.add('megamenu-details-department','megamenu-visible');p.querySelectorAll('a').forEach(a=>a.classList.add('megamenu-item'))})"
    )
    original = module.visible_text

    def visible(page, label):
        if label == labels[0]:
            raise RuntimeError("Synthetic single-root failure")
        return original(page, label)

    monkeypatch.setattr(module, "visible_text", visible)
    result = {"menu_panels": [], "errors": []}
    module.collect_menu(page, result)
    assert [r["name"] for r in result["menu_panels"]] == [labels[1]]
    assert result["errors"][0]["root"] == labels[0]


def test_details_recovers_only_explicit_menu_parent_ids(page):
    module = details_module()
    page.evaluate(
        """()=>{document.body.innerHTML='<div class="megamenu-details-department megamenu-visible" data-id="43"><a class="megamenu-item megamenu-item-heading" data-id="3730">Televíziók</a><div class="megamenu-group megamenu-group-3730"><a class="megamenu-item" data-id="4017">LED TV</a></div><div class="megamenu-group megamenu-group-"><a class="megamenu-item" data-id="999">Ismeretlen csoport</a></div></div>'}"""
    )
    panel = page.evaluate(module.DOM_EVIDENCE)[0]
    assert panel["department_id"] == "43"
    nodes = {n["source_menu_item_id"]: n for n in panel["items"]}
    assert nodes["4017"]["parent_menu_item_id"] == "3730"
    assert nodes["4017"]["identifier_namespace"] == "webshop_menu_not_marketplace"
    assert nodes["4017"]["hierarchy_status"] == "verified_dom"
    assert (
        nodes["999"]["parent_menu_item_id"] is None
        and nodes["999"]["hierarchy_status"] == "needs_review"
    )
    assert module.HOME_URL == "https://www.emag.hu/homepage"
