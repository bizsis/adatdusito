"""Targeted additional evidence: ambiguous menu groups and category identity.

Run on the operator's machine; no database access, no automatic ID mapping.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import zipfile
from playwright.sync_api import sync_playwright

HOME_URL = "https://www.emag.hu/homepage"

SEMANTIC_KEYS = {
    "data_id",
    "parentCategoryId",
    "parent_category_id",
    "parentMenuId",
    "parent_menu_id",
    "section_id",
    "sectionId",
    "group_id",
    "groupId",
    "groups",
    "position",
    "order",
    "label",
    "heading",
    "marketplace_category_id",
    "marketplaceCategoryId",
    "emag_category_id",
    "id",
    "parent_id",
    "parentId",
    "categoryId",
    "category_id",
    "departmentId",
    "department_id",
    "name",
    "title",
    "type",
    "url",
    "href",
    "children",
    "items",
    "departments",
    "sections",
    "categories",
    "links",
    "data",
    "menu",
}


def sanitized_payload(value, depth=0):
    if depth > 20:
        return None
    if isinstance(value, dict):
        return {
            k: sanitized_payload(v, depth + 1)
            for k, v in value.items()
            if k in SEMANTIC_KEYS
        }
    if isinstance(value, list):
        return [sanitized_payload(v, depth + 1) for v in value[:2000]]
    if isinstance(value, str):
        if "<" in value:
            return "[HTML response omitted; live DOM evidence captured separately]"
        if value.startswith(("https://", "http://", "/")):
            p = urlparse(
                value if not value.startswith("/") else "https://www.emag.hu" + value
            )
            if p.hostname and (
                p.hostname == "emag.hu" or p.hostname.endswith(".emag.hu")
            ):
                return "https://" + p.hostname + p.path
            return None
        return value[:1000]
    return value if isinstance(value, (int, float, bool)) or value is None else None


DOM_EVIDENCE = r"""() => {
 const visible=e=>e.getBoundingClientRect().width>0&&getComputedStyle(e).visibility!=='hidden';
 const panels=[...document.querySelectorAll('.megamenu-details-department.megamenu-visible')].filter(visible);
 return panels.map(panel=>({department_id:panel.getAttribute('data-id'),items:[...panel.querySelectorAll('.megamenu-item')].map((e,i)=>{
   const rect=e.getBoundingClientRect();const attrs={};for(const a of e.attributes)if(/^(data-(id|parent-id|parent|category-id|department-id|group-id|menu-id)|aria-controls|aria-labelledby)$/.test(a.name))attrs[a.name]=a.value;
   const parents=[];for(let p=e.parentElement;p&&p!==panel;p=p.parentElement)parents.push({tag:p.tagName.toLowerCase(),classes:p.className,data_id:p.getAttribute('data-id'),data_parent_id:p.getAttribute('data-parent-id')});
   const group=parents.find(p=>String(p.classes).split(/\s+/).includes('megamenu-group'));
   const groupId=group?String(group.classes).split(/\s+/).find(c=>c.startsWith('megamenu-group-'))?.slice('megamenu-group-'.length):null;
   const heading=groupId?[...panel.querySelectorAll('.megamenu-item-heading[data-id]')].find(h=>h.getAttribute('data-id')===groupId):null;
   return {name:(e.innerText||e.textContent||'').trim(),source_menu_item_id:attrs['data-id']||null,parent_menu_item_id:heading?groupId:null,
     identifier_namespace:'webshop_menu_not_marketplace',hierarchy_status:!group||heading?'verified_dom':'needs_review',
     parent_evidence:heading?'explicit_group_class_to_heading_data_id':group?'unresolved_group':'department_containment',
     source_attributes:attrs,classes:e.className,dom_order:i,visible:visible(e),rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},ancestors:parents};
 })}));
}"""
IDENTITY_EVIDENCE = r"""async () => {
 const ids=[],crumbs=[],hashInputs=[];
 const cleanUrl=v=>{if(!v||typeof v!=='string')return null;try{const u=new URL(v,location.href);return u.protocol==='https:'&&!u.username&&!u.password&&(u.hostname==='emag.hu'||u.hostname.endsWith('.emag.hu'))?u.origin+u.pathname:null}catch{return null}};
 let visited=0;
 for(const [scriptIndex,s] of [...document.querySelectorAll('script[type="application/json"],script[type="application/ld+json"]')].entries()){
  if(!s.textContent||s.textContent.length>2000000)continue;
  let data;try{data=JSON.parse(s.textContent)}catch{continue}
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s.textContent)))].map(x=>x.toString(16).padStart(2,'0')).join('');hashInputs.push({script_index:scriptIndex,sha256:hash});
  const stack=[{v:data,path:'script['+scriptIndex+']',depth:0}];
  while(stack.length&&visited++<50000){const {v,path,depth}=stack.pop();if(depth>35||!v||typeof v!=='object')continue;
   if(v['@type']==='BreadcrumbList')crumbs.push({json_path:path,items:(v.itemListElement||[]).slice(0,50).map(x=>({name:x.name||x.item?.name||null,url:cleanUrl(typeof x.item==='string'?x.item:x.item?.['@id']||''),position:x.position}))});
   for(const [key,value] of Object.entries(v)){
    if((/^(?:(?:marketplace|emag)_?)?category_?id$/i.test(key)||(key==='id'&&/categor/i.test(path)))&&['number','string'].includes(typeof value))ids.push({json_path:path+'.'+key,value:String(value).slice(0,200),namespace:'unverified'});
    if(value&&typeof value==='object')stack.push({v:value,path:path+'.'+key,depth:depth+1});
   }
  }
 }
 return {identifiers:ids,breadcrumbs:crumbs,source_document_hashes:hashInputs,automatic_marketplace_mapping:false};
}"""


def visible_text(page, text):
    """Do not pick the first (often hidden/mobile) duplicate text node."""
    for candidate in page.get_by_text(text, exact=True).all():
        if candidate.is_visible():
            return candidate
    return None


def diagnostics(page):
    return page.evaluate("""() => ({
      page_url:location.origin+location.pathname,
      category_triggers:[...document.querySelectorAll('a,button,span')].filter(e=>(e.textContent||'').trim()==='Kategóriák').slice(0,20).map(e=>({tag:e.tagName,classes:typeof e.className==='string'?e.className:'',visible:e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0})),
      active_department_ids:[...document.querySelectorAll('.megamenu-details-department.megamenu-visible')].map(e=>e.getAttribute('data-id'))
    })""")


def install_manual_recorder(page):
    page.evaluate(
        """() => {
      const collect="""
        + DOM_EVIDENCE
        + """;
      const panels=new Map();
      const capture=()=>{
        for(const panel of collect()){
          if(!panel.department_id||!panel.items.length)continue;
          const heading=[...document.querySelectorAll('.megamenu-details-department')].find(e=>e.getAttribute('data-id')===panel.department_id)?.querySelector('.megamenu-details-department-title');
          panels.set(panel.department_id,{name:(heading?.textContent||'').trim(),dom:[panel]});
        }
        console.info('Adatdúsító részletes panelek:',panels.size);
      };
      document.addEventListener('keydown',event=>{
        if(event.key==='F8'||(event.altKey&&event.shiftKey&&event.code==='KeyM')){event.preventDefault();capture();}
      },true);
      window.AdatdusitoDetailsCapture={capture,read:()=>[...panels.values()]};
    }"""
    )


def collect_menu(page, result, manual=False, prompt=input):
    core = Path(__file__).with_name("emag_menu") / "menu_capture.js"
    page.evaluate(core.read_text(encoding="utf-8"))
    if manual:
        install_manual_recorder(page)
        print(
            "Nyisd meg a Kategóriák menüt. Minden főcsoport fölött várd meg az almenüt, majd Alt+Shift+M (vagy F8)."
        )
        prompt("Ha kész a kézi rögzítés, Enter itt a terminálban. ")
        result["menu_panels"] = page.evaluate("AdatdusitoDetailsCapture.read()")
        if not result["menu_panels"]:
            result["errors"].append(
                {
                    "phase": "menu_manual",
                    "error": "Nem rögzült panel; a gyorsbillentyűt az oldalra fókuszálva nyomd meg.",
                }
            )
        return
    try:
        if not page.evaluate("AdatdusitoMenuCapture.discover().length"):
            page.get_by_text("Kategóriák", exact=True).first.wait_for(
                state="attached", timeout=6000
            )
            trigger = visible_text(page, "Kategóriák")
            if trigger is None:
                raise RuntimeError(
                    "Nincs látható Kategóriák kapcsoló; használd a --manual módot."
                )
            trigger.hover(timeout=6000)
            page.wait_for_timeout(400)
            if not page.evaluate("AdatdusitoMenuCapture.discover().length"):
                trigger.click(timeout=6000)
            page.wait_for_function(
                "AdatdusitoMenuCapture.discover().length>0", timeout=6000
            )
        roots = page.evaluate("AdatdusitoMenuCapture.discover()")
    except Exception as error:
        result["errors"].append(
            {"phase": "menu_open", "error": str(error).splitlines()[0][:300]}
        )
        result["diagnostics"] = diagnostics(page)
        return
    for root in roots:
        try:
            target = visible_text(page, root["name"])
            if target is None:
                raise RuntimeError("A főcsoport nem látható.")
            expected_department = target.evaluate(
                "e=>e.closest('.megamenu-list-department')?.getAttribute('data-id')||null"
            )
            target.hover(timeout=6000)
            if expected_department:
                page.wait_for_function(
                    "id=>[...document.querySelectorAll('.megamenu-details-department.megamenu-visible')].some(p=>p.getAttribute('data-id')===id&&p.getBoundingClientRect().width>0)",
                    arg=expected_department,
                    timeout=6000,
                )
            page.wait_for_timeout(1300)
            dom = page.evaluate(DOM_EVIDENCE)
            if expected_department:
                dom = [p for p in dom if p["department_id"] == expected_department]
            if not any(panel["items"] for panel in dom):
                raise RuntimeError("A megnyitott almenü üres vagy nem azonosítható.")
            result["menu_panels"].append({"name": root["name"], "dom": dom})
        except Exception as error:
            result["errors"].append(
                {
                    "phase": "menu_root",
                    "root": root["name"],
                    "error": str(error).splitlines()[0][:300],
                }
            )
    result["diagnostics"] = diagnostics(page)


def collect_category_pages(page, urls, robots, result, prompt=None):
    for url in urls:
        try:
            if not robots.can_fetch("AdatdusitoMenuExport", url):
                result["errors"].append(
                    {"phase": "category", "url": url, "error": "robots_disallowed"}
                )
                continue
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if prompt:
                prompt("A kategóriaoldalon kezeld a sütikérdést, majd Enter itt. ")
                prompt = None
            page.wait_for_timeout(1500)
            identity = page.evaluate(IDENTITY_EVIDENCE)
            final = urlparse(page.url)
            status = response.status if response else None
            result["category_pages"].append(
                {
                    "url": url,
                    "final_url": final.scheme
                    + "://"
                    + (final.hostname or "")
                    + final.path,
                    "status": status,
                    "evidence_status": "identifiers_observed"
                    if identity["identifiers"]
                    else "no_category_identifier_found",
                    **identity,
                }
            )
            if status is None or status >= 400:
                result["errors"].append(
                    {"phase": "category", "url": url, "error": "http_" + str(status)}
                )
        except Exception as error:
            result["errors"].append(
                {
                    "phase": "category",
                    "url": url,
                    "error": str(error).splitlines()[0][:300],
                }
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=["chrome", "msedge"], default="chrome")
    parser.add_argument("--output", type=Path, default=Path.home() / "Desktop")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Kézi menünyitás és Alt+Shift+M/F8; nem függ a Kategóriák hover működésétől.",
    )
    parser.add_argument(
        "--only-categories",
        action="store_true",
        help="A menüt kihagyva csak a megadott kategóriaoldalakat vizsgálja.",
    )
    parser.add_argument("--category-url", action="append", default=[])
    args = parser.parse_args()
    if args.only_categories and not args.category_url:
        parser.error("--only-categories mellé --category-url is kell.")
    if len(args.category_url) > 10:
        parser.error("Legfeljebb 10 célzott kategóriaoldal gyűjthető.")
    for url in args.category_url:
        p = urlparse(url)
        if (
            p.scheme != "https"
            or p.hostname != "www.emag.hu"
            or p.username
            or p.password
            or p.port not in (None, 443)
            or p.query
            or p.fragment
            or not p.path.endswith("/c")
        ):
            parser.error("Közvetlen, query nélküli emag.hu kategória-URL kell.")
    out = args.output / (
        "emag-details-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    out.mkdir(parents=True, exist_ok=False)
    result = {
        "format": "adatdusito.menu-details.v2",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "requested_homepage": HOME_URL,
        "mode": "only_categories"
        if args.only_categories
        else "manual"
        if args.manual
        else "automatic",
        "menu_panels": [],
        "network_menu_evidence": [],
        "category_pages": [],
        "errors": [],
        "automatic_marketplace_mapping": False,
        "database_writes": False,
    }
    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.launch(channel=args.channel, headless=False)
            context = browser.new_context(
                viewport={"width": 1800, "height": 1100}, locale="hu-HU"
            )
            page = context.new_page()
            responses = []
            page.on(
                "response",
                lambda r: responses.append(r)
                if re.search(
                    r"/(?:[^/]*megamenu|navigation|departments?)(?:[/?_-]|$)",
                    urlparse(r.url).path,
                    re.I,
                )
                and r.request.resource_type in ("xhr", "fetch")
                else None,
            )
            r = context.request.get("https://www.emag.hu/robots.txt", timeout=20000)
            robots_text = r.text().lstrip("\ufeff")
            if r.status != 200 or robots_text.lstrip().startswith("<"):
                raise RuntimeError(
                    "A robots.txt nem ellenőrizhető; automatizált gyűjtés leállt."
                )
            robots = RobotFileParser()
            robots.parse(robots_text.splitlines())
            if not args.only_categories:
                try:
                    if not robots.can_fetch("AdatdusitoMenuExport", HOME_URL):
                        raise RuntimeError("A robots szabály nem engedi a kezdőlapot.")
                    page.goto(
                        HOME_URL,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    result["homepage_loaded_url"] = page.evaluate(
                        "location.origin+location.pathname"
                    )
                    print(
                        "Kért menüoldal:",
                        HOME_URL,
                        "; betöltött oldal:",
                        result["homepage_loaded_url"],
                    )
                    input(
                        "Kezeld a sütikérdést. Ha akciós oldalt látsz, nyisd meg a böngészőben a https://www.emag.hu/homepage címet, majd Enter itt. Nem kell bejelentkezni. "
                    )
                    result["homepage_after_operator_url"] = page.evaluate(
                        "location.origin+location.pathname"
                    )
                    collect_menu(page, result, manual=args.manual)
                except Exception as error:
                    result["errors"].append(
                        {"phase": "menu", "error": str(error).splitlines()[0][:400]}
                    )
            # This is deliberately independent: menu failure must not discard the
            # separately requested category-page identity evidence.
            collect_category_pages(
                page,
                args.category_url,
                robots,
                result,
                prompt=input if args.only_categories else None,
            )
            for response in responses:
                try:
                    u = urlparse(response.url)
                    if u.hostname not in ("www.emag.hu", "emag.hu"):
                        continue
                    content = response.body()
                    if len(content) > 2000000:
                        continue
                    result["network_menu_evidence"].append(
                        {
                            "url": "https://" + u.hostname + u.path,
                            "status": response.status,
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "semantic_payload": sanitized_payload(json.loads(content)),
                            "id_namespace": "unverified_source_identifiers",
                        }
                    )
                except Exception:
                    continue
        except KeyboardInterrupt:
            result["errors"].append(
                {
                    "phase": "operator",
                    "error": "A gyűjtés megszakítva; a már rögzített adatokat megőriztük.",
                }
            )
        except Exception as error:
            result["errors"].append(
                {"phase": "setup", "error": str(error).splitlines()[0][:400]}
            )
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
    result["menu_complete"] = len(result["menu_panels"]) == 13
    result["requested_category_count"] = len(args.category_url)
    result["category_pages_complete"] = len(result["category_pages"]) == len(
        args.category_url
    )
    raw = json.dumps(result, ensure_ascii=False, indent=2).encode()
    (out / "menu-details.json").write_bytes(raw)
    (out / "SHA256.txt").write_text(
        hashlib.sha256(raw).hexdigest() + "  menu-details.json\n"
    )
    with zipfile.ZipFile(out / "emag-menu-details.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out / "menu-details.json", "menu-details.json")
        z.write(out / "SHA256.txt", "SHA256.txt")
    print("Kiegészítő csomag:", out / "emag-menu-details.zip")
    print(
        "Panelek:",
        len(result["menu_panels"]),
        "menü-JSON:",
        len(result["network_menu_evidence"]),
        "kategóriaoldalak:",
        len(result["category_pages"]),
    )
    if result["errors"]:
        print("A csomag részleges. Hibák:", len(result["errors"]))
    print(
        "Minden új azonosító ellenőrzendő; automatikus Marketplace-kapcsolat nem készült."
    )
    return (
        0
        if (args.only_categories or result["menu_complete"])
        and result["category_pages_complete"]
        and not result["errors"]
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
