/* Public menu DOM evidence only. No cookies, storage, accounts or DB writes.
 * Can be pasted into DevTools, or loaded by export_emag_menu.py.
 */
(() => {
  "use strict";
  const expectedRoots = [
    "Háztartási gépek és klíma", "TV és szórakozás", "Telefon, Tablet, Laptop",
    "Számítástechnika", "Fotó-Videó, Okos eszközök", "Szupermarket",
    "Otthon, barkács, kert", "Játékok, Baba, Mama", "Divat, ékszerek és kiegészítők",
    "Szépségápolás", "Sport és utazás", "Könyvek, Filmek és Irodaszerek",
    "Autó- és motor felszerelések"
  ];
  const normalize = s => (s || "").normalize("NFKC").replace(/\u00ad/g, "")
    .replace(/[\u2010-\u2015]/g, "-").replace(/\s+/g, " ").trim().toLocaleLowerCase("hu-HU");
  const text = el => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const visible = el => {
    if (!el || !el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return false;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" &&
      style.display !== "none" && rect.bottom > 0 && rect.top < innerHeight &&
      rect.right > 0 && rect.left < innerWidth;
  };
  const exposed = el => {
    if (!visible(el)) return false;
    const r = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(innerWidth - 1, r.left + r.width / 2));
    const y = Math.max(0, Math.min(innerHeight - 1, r.top + r.height / 2));
    const hit = document.elementFromPoint(x, y);
    return !!hit && (el.contains(hit) || hit === el);
  };
  const publicUrl = value => {
    if (!value) return null;
    try {
      const u = new URL(value, location.href);
      if (u.protocol !== "https:" || !(u.hostname === "emag.hu" || u.hostname.endsWith(".emag.hu")) || u.username || u.password) return null;
      // Avoid persisting tracking/session query values. Paths are source evidence,
      // never interpreted as Marketplace IDs.
      return {url: u.origin + u.pathname, query_keys: [...new Set(u.searchParams.keys())], fragment_present: !!u.hash};
    } catch { return null; }
  };
  function identities(el) {
    const out = {};
    for (const a of el.attributes) {
      if (/^data-(?:id|category-id|category|submenu-id|menu-id|parent-id)$/.test(a.name) && a.value.length <= 200) out[a.name] = a.value;
    }
    return out;
  }
  const labelIndex = label => expectedRoots.findIndex(name => normalize(name) === normalize(label));
  function rootElements() {
    const found = new Map();
    for (const el of document.querySelectorAll('a, button, [role="menuitem"], .megamenu-item-name, .megamenu-item-text, .megamenu-item-link')) {
      if (!visible(el)) continue;
      const index = labelIndex(text(el));
      if (index < 0 || found.has(index)) continue;
      found.set(index, el);
    }
    // Map insertion order follows the observed DOM, not the expected label list.
    return [...found].map(([index, element]) => ({expected: expectedRoots[index], element}));
  }
  function discover() {
    return rootElements().map(({expected, element}, order) => ({
      name: text(element), expected_label: expected, observed_order: order,
      source_url: publicUrl(element.getAttribute("href"))?.url || null,
      explicit_source_attributes: identities(element),
      canonical_emag_id: null, mapping_status: "pending"
    }));
  }
  function linkRecords(scope, rootLabels) {
    return [...scope.querySelectorAll("a[href]")].filter(el => exposed(el) && !rootLabels.has(normalize(text(el))))
      .map(el => {
        const href = publicUrl(el.getAttribute("href"));
        return href && text(el) ? {element: el, name: text(el), ...href,
          explicit_source_attributes: identities(el), canonical_emag_id: null,
          mapping_status: "pending", link_kind: "unclassified_menu_link"} : null;
      }).filter(Boolean);
  }
  function cleanHtml(scope) {
    const clone = scope.cloneNode(true);
    const originals=[...scope.querySelectorAll('a')], copies=[...clone.querySelectorAll('a')];
    // Pair exact cloned elements BEFORE pruning. Names/IDs need not be unique.
    const hrefs=new Map(copies.map((element,i)=>[element,publicUrl(originals[i].getAttribute('href'))?.url]));
    clone.querySelectorAll('script,style,iframe,form,input,textarea,select,svg,img,video,canvas').forEach(el=>el.remove());
    for(const el of [clone,...clone.querySelectorAll('*')]) for(const a of [...el.attributes]){
      if(!['class','id','role','aria-label','data-id','data-category-id','data-submenu-id'].includes(a.name))el.removeAttribute(a.name);
    }
    const comments=[],walker=document.createTreeWalker(clone,NodeFilter.SHOW_COMMENT);
    while(walker.nextNode())comments.push(walker.currentNode);comments.forEach(n=>n.remove());
    for(const element of clone.querySelectorAll('a'))if(hrefs.get(element))element.setAttribute('href',hrefs.get(element));
    return clone.outerHTML;
  }
  const exports = new Map();
  let lastPanel = null;
  let defaultPanelSelector = null;
  function capture(label, options = {}) {
    options = {panelSelector: defaultPanelSelector, ...options};
    if (location.protocol !== "https:" || !(location.hostname === "emag.hu" || location.hostname.endsWith(".emag.hu"))) throw new Error("Az exportot az emag.hu HTTPS-oldalán futtasd.");
    const roots = rootElements();
    const match = roots.find(r => normalize(r.expected) === normalize(label));
    if (!match) throw new Error("A főcsoport nem látható a DOM-ban: " + label);
    const root = match.element, rootLabels = new Set(expectedRoots.map(normalize));
    let panel = options.panelSelector ? document.querySelector(options.panelSelector) : null;
    let method = panel ? "operator_panel_selector" : null;
    if (!panel) {
      const controlled = root.getAttribute("aria-controls") || root.closest("[aria-controls]")?.getAttribute("aria-controls");
      if (controlled) { panel = document.getElementById(controlled); method = "aria_controls"; }
    }
    if (!panel || !visible(panel) || !linkRecords(panel, rootLabels).length) {
      panel = null;
      // A nested submenu gives an explicit DOM containment relationship.
      const li = root.closest('li,[role="menuitem"]');
      if (li && linkRecords(li, rootLabels).length) { panel = li; method = "nested_dom"; }
    }
    if (!panel) {
      // Prefer a visible megamenu overlay; do not export the page body or product cards.
      const candidates = [...document.querySelectorAll(
        ".megamenu-dropdown, .megamenu-submenu, .megamenu-content, #emg-megamenu, .megamenu, [role='menu']"
      )].filter(el => visible(el) && ![document.body, document.documentElement].includes(el));
      const right = root.getBoundingClientRect().right;
      const scored = candidates.map(el => ({el, links: linkRecords(el, rootLabels).filter(l => l.element.getBoundingClientRect().left >= right - 20)}))
        .filter(c => c.links.length).sort((a,b) => b.links.length - a.links.length || a.el.querySelectorAll('*').length - b.el.querySelectorAll('*').length);
      if (scored.length) { panel = scored[0].el; method = "visible_menu_after_hover_needs_review"; }
    }
    if (!panel || [document.body, document.documentElement].includes(panel)) throw new Error("Nem azonosítható a látható almenü. Használd a kézi F8 módot --panel-selector megadással.");
    const records = linkRecords(panel, rootLabels);
    if (!records.length) throw new Error("A panelen nem látható exportálható menühivatkozás.");
    const nodes = [], byElement = new Map();
    for (const record of records) {
      const {element, ...data} = record;
      const id = "link-" + nodes.length;
      byElement.set(element, id);
      nodes.push({observation_id: id, ...data, observed_order: nodes.length});
    }
    // Preserve only actual DOM section containment, never infer category parents
    // from matching names, URLs or visual proximity.
    const sections = [];
    for (const heading of panel.querySelectorAll('h2,h3,h4,h5,.megamenu-list-heading,.megamenu-column-title')) {
      if (!visible(heading) || !text(heading)) continue;
      const container = heading.closest('section,li,.megamenu-list,.megamenu-column') || heading.parentElement;
      const childIds = [...container.querySelectorAll('a[href]')].map(a => byElement.get(a)).filter(Boolean);
      if (childIds.length) sections.push({name: text(heading), relation: "dom_section_contains_links", observation_ids: [...new Set(childIds)]});
    }
    const group = {
      name: text(root), expected_label: match.expected,
      source_url: publicUrl(root.getAttribute('href'))?.url || null,
      explicit_source_attributes: identities(root),
      canonical_emag_id: null, mapping_status: "pending", observed_at: new Date().toISOString(),
      association_evidence: method, association_status: "needs_review",
      links: nodes, sections, html_evidence: cleanHtml(panel)
    };
    exports.set(match.expected, group); lastPanel = panel;
    console.info("Adatdúsító menü mentve:", group.name, nodes.length, "hivatkozás");
    return group;
  }
  function diagnostics() {
    const describe = el => ({tag:el.tagName.toLowerCase(),id:el.id.slice(0,200),classes:typeof el.className==='string'?el.className.slice(0,300):''});
    return rootElements().map(({expected,element})=>{
      const ancestors=[];let el=element;
      for(let i=0;el&&i<6;i++,el=el.parentElement) ancestors.push(describe(el));
      return {root:expected,ancestors};
    });
  }
  function report() {
    const roots = discover();
    const missing = expectedRoots.filter(name => !exports.has(name));
    const duplicates = [];
    const signatures = new Map();
    for (const group of exports.values()) {
      const signature = JSON.stringify(group.links.map(l=>[l.name,l.url]));
      if (signatures.has(signature)) duplicates.push([signatures.get(signature),group.name]);
      else signatures.set(signature,group.name);
    }
    return {format: "adatdusito.emag-menu-evidence.v1", observed_at: new Date().toISOString(),
      page: publicUrl(location.href)?.url || null, expected_root_count: expectedRoots.length,
      discovered_roots: roots, dom_diagnostics: diagnostics(), root_groups: [...exports.values()], missing_roots: missing,
      captured_root_count: exports.size, all_expected_panels_captured: !missing.length,
      duplicate_panel_contents: duplicates, collection_needs_review: true,
      full_category_tree_verified: false, automatic_marketplace_mapping: false,
      database_writes: false,
      notes: ["A menü vásárlói navigáció: brand shopok, keresők és kampánylinkek is lehetnek benne.",
        "Az összes panel mentése nem bizonyít teljes kategóriafát vagy Marketplace-azonosságot."]};
  }
  function download() {
    const data = report(), blob = new Blob([JSON.stringify(data,null,2)],{type:"application/json;charset=utf-8"});
    const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;
    a.download="emag-menu-export-"+new Date().toISOString().replace(/[:.]/g,'-')+".json";
    a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);return data;
  }
  function currentRoot() {
    const roots = rootElements();
    return roots.find(({element}) => element.matches(':hover') || element.closest('li')?.matches(':hover'))?.expected;
  }
  const previous = window.AdatdusitoMenuCapture;
  if (previous?.hotkey) document.removeEventListener('keydown', previous.hotkey, true);
  function hotkey(event) {
    if (event.key==='F8' || (event.altKey && event.shiftKey && event.code==='KeyM')) { event.preventDefault(); try { const label=currentRoot(); if(!label) throw new Error('Vidd az egeret a bal oldali főcsoport nevére, majd F8.');capture(label); } catch(e) { console.error(e.message); } }
    if (event.key==='F9' || (event.altKey && event.shiftKey && event.code==='KeyE')) { event.preventDefault(); download(); }
  }
  document.addEventListener('keydown',hotkey,true);
  window.AdatdusitoMenuCapture={expectedRoots,discover,capture,report,download,hotkey,diagnostics,setPanelSelector(selector){defaultPanelSelector=selector;},get lastPanel(){return lastPanel;}};
  console.info('Adatdúsító menüexport kész. Főcsoport fölé egér → F8; minden csoport után F9: JSON-letöltés.');
})();
