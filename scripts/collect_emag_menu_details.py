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
 const panels=[...document.querySelectorAll('.megamenu-details-department.megamenu-visible')];
 return panels.map(panel=>({department_id:panel.getAttribute('data-id'),items:[...panel.querySelectorAll('.megamenu-item')].map((e,i)=>{
   const rect=e.getBoundingClientRect();const attrs={};for(const a of e.attributes)if(/^(data-(id|parent-id|parent|category-id|department-id|group-id|menu-id)|aria-controls|aria-labelledby)$/.test(a.name))attrs[a.name]=a.value;
   const parents=[];for(let p=e.parentElement;p&&p!==panel;p=p.parentElement)parents.push({tag:p.tagName.toLowerCase(),classes:p.className,data_id:p.getAttribute('data-id'),data_parent_id:p.getAttribute('data-parent-id')});
   return {name:(e.innerText||e.textContent||'').trim(),source_attributes:attrs,classes:e.className,dom_order:i,visible:visible(e),rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},ancestors:parents};
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=["chrome", "msedge"], default="chrome")
    parser.add_argument("--output", type=Path, default=Path.home() / "Desktop")
    parser.add_argument(
        "--category-url",
        action="append",
        default=[],
        help="Konkrét kategóriaoldal; legfeljebb 10. Példa: https://www.emag.hu/televiziok/c",
    )
    args = parser.parse_args()
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
        "emag-details-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    out.mkdir(parents=True, exist_ok=False)
    result = {
        "format": "adatdusito.menu-details.v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "menu_panels": [],
        "network_menu_evidence": [],
        "category_pages": [],
        "errors": [],
        "automatic_marketplace_mapping": False,
        "database_writes": False,
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel, headless=False)
        context = browser.new_context(
            viewport={"width": 1800, "height": 1100}, locale="hu-HU"
        )
        page = context.new_page()
        responses = []
        page.on(
            "response",
            lambda response: responses.append(response)
            if re.search(
                r"/(?:[^/]*megamenu|navigation|departments?)(?:[/?_-]|$)",
                urlparse(response.url).path,
                re.I,
            )
            and response.request.resource_type in ("xhr", "fetch")
            else None,
        )
        try:
            r = context.request.get("https://www.emag.hu/robots.txt", timeout=20000)
            if r.status != 200 or r.text().lstrip().startswith("<"):
                raise RuntimeError(
                    "A robots.txt nem ellenőrizhető; automatizált gyűjtés leállt."
                )
            robots = RobotFileParser()
            robots.parse(r.text().splitlines())
            if not robots.can_fetch(
                "AdatdusitoMenuExport", "https://www.emag.hu/homepage"
            ):
                raise RuntimeError("A robots szabály nem engedi a kezdőlapot.")
            page.goto(
                "https://www.emag.hu/homepage",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            input(
                "Kezeld a sütikérdést, majd Enter a terminálban. Nem szükséges bejelentkezni. "
            )
            trigger = page.get_by_text("Kategóriák", exact=True).first
            trigger.hover()
            page.wait_for_timeout(500)
            core = Path(__file__).with_name("emag_menu") / "menu_capture.js"
            page.evaluate(core.read_text(encoding="utf-8"))
            if not page.evaluate("AdatdusitoMenuCapture.discover().length"):
                trigger.click()
                page.wait_for_timeout(500)
            roots = page.evaluate("AdatdusitoMenuCapture.discover()")
            for root in roots:
                page.get_by_text(root["name"], exact=True).first.hover()
                page.wait_for_timeout(1300)
                result["menu_panels"].append(
                    {"name": root["name"], "dom": page.evaluate(DOM_EVIDENCE)}
                )
            for response in responses:
                try:
                    u = urlparse(response.url)
                    if u.hostname not in ("www.emag.hu", "emag.hu"):
                        continue
                    content = response.body()
                    if len(content) > 2000000:
                        continue
                    payload = json.loads(content)
                    result["network_menu_evidence"].append(
                        {
                            "url": "https://" + u.hostname + u.path,
                            "status": response.status,
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "semantic_payload": sanitized_payload(payload),
                            "id_namespace": "unverified_source_identifiers",
                        }
                    )
                except Exception:
                    continue
            for url in args.category_url:
                if not robots.can_fetch("AdatdusitoMenuExport", url):
                    result["errors"].append({"url": url, "error": "robots_disallowed"})
                    continue
                response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                identity = page.evaluate(IDENTITY_EVIDENCE)
                final = urlparse(page.url)
                result["category_pages"].append(
                    {
                        "url": url,
                        "final_url": final.scheme
                        + "://"
                        + (final.hostname or "")
                        + final.path,
                        "status": response.status if response else None,
                        "evidence_status": "identifiers_observed"
                        if identity["identifiers"]
                        else "no_category_identifier_found",
                        **identity,
                    }
                )
        except Exception as e:
            result["errors"].append({"error": str(e).splitlines()[0][:400]})
        finally:
            context.close()
            browser.close()
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
        "menü-hálózati válaszok:",
        len(result["network_menu_evidence"]),
        "kategóriaoldalak:",
        len(result["category_pages"]),
    )
    print(
        "Minden új azonosító ellenőrzendő; automatikus Marketplace-kapcsolat nem készült."
    )
    return 0 if len(result["menu_panels"]) == 13 and not result["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
