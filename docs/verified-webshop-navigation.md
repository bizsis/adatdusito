# A valódi magyar eMAG-menü beépítése

## Feldolgozott forrás és bizonyíték

Az üzemeltető Windowsos gépéről átadott `emag-menu-export.zip`, forrás: `https://www.emag.hu/homepage`. A teljes ZIP SHA-256 lenyomata és a 13 HTML-fájl bájthash-e a verziózott `backend/reference_data/web_navigation.json` állományban szerepel. A ZIP-et nem hajtjuk végre, nem csomagoljuk ki tetszőleges útvonalra. A parser méret-, mélység-, egyedi azonosító- és hash-ellenőrzést végez.

A Windowsos exportáló `write_text` művelete az eredeti HTML LF sorvégeit CRLF-re változtatta; a JSON-hash az eredeti szöveghez tartozik. Minden állománynál ellenőriztük, hogy kizárólag a CRLF→LF transzformáció után egyezik az elvárt hash. A tényleges fájlhash és a manifesthash is megmaradt. Más tartalmi eltérést a parser elutasít. A gyűjtő írását `write_bytes`-ra javítottuk, így új exportnál ez a platformeltérés nem jelentkezik.

A mentett HTML egy időben több, részben rejtett panelt is tartalmaz. Nem a fájlban található összes linket kapcsoljuk az éppen vizsgált főcsoporthoz:

1. A főcsoportok eredeti sorrendje a `li.megamenu-list-department[data-id]` elemekből származik.
2. A főcsoport és panel kapcsolata az azonos `data-id`: például `43` → TV és szórakozás panel.
3. A rögzített csoporthoz tartozó aktív panelt a `megamenu-visible` állapot, a panelazonosító és a rögzített név együtt igazolja.
4. A szekció–gyermek kapcsolatot a `megamenu-group-3487` osztály és az azonos panelen lévő `data-id=3487` fejléc bizonyítja.
5. Üres `megamenu-group-` vagy feloldhatatlan fejléc esetén csak a főcsoporthoz tartozás biztos: a link ott elérhető marad, `needs_review` jelzéssel. A vizuális oszlopközelségből nem találunk ki szülőt.

A régi HTML-szanitizáló azonos feliratú linkek href-jét név alapján állította vissza. **18 eltérést** találtunk a HTML és a közvetlenül mentett JSON-link között. Az érintett linkeknél a JSON URL-je az elsődleges, kizárólag az adott panelen belüli egyedi `data-id` szerint egyeztetve; nem név alapján. A jövőbeli exportban az eredeti DOM-elem pontos klónjához rendeljük vissza a href-et, így ez a hiba javított. Külön regressziós teszt ellenőrzi az azonos nevű, különböző URL-ű linkeket.

## Tényleges menülefedettség

- **13 főcsoport**, az eredeti magyar sorrendben.
- **609** JSON-ban rögzített menühivatkozás.
- **420 közvetlen kategóriaoldal-hivatkozás**, 99 strukturális szekció, 47 paraméterszűrő.
- 13 márkaoldal, 10 termékkereső, 16 gyűjtőoldal, 6 kampány, 1 keresés, 1 ismeretlen link és 9 kizárólag kapcsolódó linkeket tartalmazó fejléc.
- További 1, csak HTML-ben jelen lévő főcsoport-hivatkozás megőrizve a kapcsolódó linkek között.
- Összesen 636 megfigyelt navigációs elem, a 13 gyökérrel és a link nélküli fejlécekkel együtt.
- **79 belső szekciókapcsolat ellenőrzendő.** Nem állítjuk, hogy a teljes webshop-kategóriafa helyreállt.

A 420 kategóriahivatkozás nem 420 külön Marketplace-kategória: menüelőfordulások, esetleges aliasok és még nem azonosított kapcsolatok is vannak köztük. A szűrt URL-ek (`/filter/`) nem lesznek új termékkategóriák. A `/shop/`, `/lps/`, `/label/`, `/shopping-assistant/` stb. útvonalakat külön típusként kezeljük. A márka-, kampány-, szűrő- és keresőlinkek az adatlapon „Kapcsolódó linkek” alatt jelennek meg, nem besorolható kategóriaként a fában.

## Egyetlen közös böngésző, megőrzött Marketplace-katalógus

A kategóriaböngésző első szintje kizárólag a 13 valódi főcsoport. Nincs mellette második Marketplace-fa vagy választható, párhuzamos kategóriarendszer. A menüadatok minden tenant számára azonos, verziózott, központi alkalmazásadatok. A fájl nem másolja a pinfo_db kategóriáit vagy paramétereit: a webshop-navigációs réteget tárolja.

A `web-dept-43` és `web-item-43-3730` belső navigációs kulcsok megfigyelt menüazonosítókból állnak; **nem eMAG Marketplace-azonosítók**. A termékazonosság és a paraméter-FK továbbra is az eredeti Marketplace-ID-hoz és a MySQL belső `id`-hoz kötődik. Több igazolt navigációs előfordulás hivatkozhat ugyanarra az egy kanonikus kategóriára, paramétermásolat nélkül.

Kritikus bizonyíték az eltérő névterekre: a „Könyvek, Filmek és Irodaszerek” menü főcsoportjának forrás-ID-ja **79**, míg a meglévő Marketplace **79** a Televíziók kategória. A webshop Televíziók menüelemének saját ID-ja **3730**. Ezeket sem számegyezésből, sem névegyezésből nem lehet automatikusan összekapcsolni.

**Kezdetben nincs automatikusan igazoltnak nyilvánított paramétermegfeleltetés.** Nem mutatunk nulla paramétert olyan elemnél, amelynek a paraméterkészlete valójában még nem ismert. A felület ezt „Még nem ellenőrzött” állapottal jelzi.

## Megfeleltetés és termékbesorolás

A már meglévő `reference_observations` tábla használatos; új migráció nem szükséges, az elvárt meglévő Alembic-verzió 0003. A megerősítés Superadmin-művelet, auditált, forrás-URL-lel, bizonyítéktípussal, SHA-256 lenyomattal és indoklással. Az adatlap erre külön űrlapot ad. Az operátori bizonyíték hitelességét nem helyettesíti névkeresés vagy egy kitöltött számmező.

Az API `source_category_id` bemenete a navigációs kulcs, például `web-item-43-3730`. A szerver a tároláskor automatikusan hozzáfűzi az eredeti ZIP teljes hash-ét (`kulcs@archive_sha256`): az igazolás csak az adott forrásverzióhoz érvényes. Új menüexport esetén egy újrahasznosított menü-ID nem örökli automatikusan a régi jóváhagyást. A `canonical_emag_id` kizárólag igazolt külső Marketplace-ID. A backend ellenőrzi, hogy ez a kanonikus rekord valóban létezik, és a forráselem egyáltalán megfeleltethető-e: főcsoport, márka, kampány, szűrő nem léptethető elő termékkategóriává. Újabb `pending` megfigyeléssel a korábbi megfeleltetés visszavonható; minden tenant a legutolsó állapotot látja.

Paramétervégpont csak igazolt megfeleltetés után ad adatot, az eredeti belső kategória-ID szerinti kapcsolatból. A besorolási végpont még ekkor is újra ellenőrzi az aktuális `is_allowed` és Deleted állapotot. Szülőparaméter-öröklés nincs. A paraméterértékek továbbra is lapozottak.

Új végpontok:

- `GET /api/v1/reference/navigation` – 13 gyökér, vagy parent_id/q szerinti, lapozott gyermekek.
- `GET /api/v1/reference/navigation/coverage` – az importált menü tényleges lefedettsége.
- `GET /api/v1/reference/navigation/{kulcs}` – adatlap, útvonal, kapcsolódó linkek, megfeleltetési állapot.
- `GET /api/v1/reference/navigation/{kulcs}/parameters` – csak igazolt kanonikus kapcsolatra.
- `GET /api/v1/reference/navigation/{kulcs}/selection` – későbbi import számára, csak ténylegesen besorolható kategóriára.

A korábbi `/reference/categories` útvonalak az eredeti kanonikus referenciafeloldás kompatibilitási API-jai, nem egy második felhasználói kategóriaböngésző. A következő termékimportnak a navigációs snapshotot, kulcsot, megfeleltetési bizonyíték ID-ját és a kanonikus kategória-ID-t együtt kell tárolnia és mentéskor újra ellenőriznie.

## Konkrét hiányzó adatok és kiegészítő gyűjtő

A ZIP elegendő a 13 főcsoport és az explicit szekciókapcsolatok beépítéséhez. **Nem elegendő** a 79 üres/feloldhatatlan csoport pontos szülőjéhez és a webshop→Marketplace azonosságok igazolásához.

Ehhez készült a `scripts/collect_emag_menu_details.py`. Csak a hiányzó bizonyítékot gyűjti:

1. Aktív panelenként az eredeti DOM-rendet, fejléc-/csoportosító osztályokat, explicit `data-parent-*` / `aria-*` mezőket és koordinátákat. A koordinátából nem állít elő automatikus szülőt.
2. A normál menünyitás során érkező menü-/departmentspecifikus JSON-válaszok szűkített taxonómiai mezőit és hash-eit. Nem ment sütit, profilt vagy bejelentkezési adatot.
3. Külön megadott kategóriaoldalakon a strukturált category-ID-ket, JSON-útvonalukat, dokumentumhash-t és breadcrumbokat. Egy általános `category.id` továbbra is **ismeretlen névterű** adat; nem automatikus Marketplace-ID.

A saját Windows gépen, friss projektmásolatban, a korábban telepített `.menu-venv` környezettel:

```powershell
git pull --ff-only origin main
.\.menu-venv\Scripts\python.exe scripts/collect_emag_menu_details.py --channel chrome --manual --category-url https://www.emag.hu/televiziok/c --output "$env:USERPROFILE\Desktop"
```

Kezeld a sütikérdést, majd Enter a terminálban. A program a menüt járja be és a megadott egy kategóriaoldalról kér célzott adatot. További `--category-url` legfeljebb tízszer adható meg, nem indít teljes katalógus-crawlert. A végén az `emag-menu-details.zip` fájlt kell átadni. A robots-ellenőrzés és a normál hozzáférés megmarad; tiltás esetén nem kerül meg védelmet. Az élő oldalon a kiegészítő gyűjtő sem ellenőrzött ebből a felhőből, DOM- és JSON-mintákon tesztelt.

## Frissítés a VPS-en – csak kézzel

Tiszta Git-állapot és az alkalmazás-adatbázis szokásos mentése után:

```bash
cd /opt/adatdusito
git status -sb
git pull --ff-only origin main
docker compose build
docker compose up -d --no-build
bash scripts/smoke.sh https://dev.pinfo.hu
```

Ha a VPS még nem 0003-on van, előbb a korábbi dokumentált alkalmazásmigráció szükséges. E kiadás önmagában nem igényel új táblát, pinfo_db-írást, `.env`-, external hálózat-, MySQL-, Nginx- vagy HTTPS-módosítást. Frissítés után az első szinten a 13 magyar főcsoportnak kell látszania, eredeti sorrendben; a korábbi „AC & Heating” stb. nem jelenik meg külön, párhuzamos gyökérként.


## Kiegészítő export hibajavítás: üres, hover-időtúllépéses csomag

Az üzemeltető következő `emag-menu-details.zip` csomagja érvényes hash-sel, de csak 332 bájtos JSON-nal érkezett. A tartalma 0 menüpanel, 0 hálózati menüválasz, 0 kategóriaoldal és `Locator.hover: Timeout 30000ms exceeded.` hiba volt. Ez nem új kategóriabizonyíték és nem az eMAG kategóriáinak hiányát jelenti; a gyűjtés állt le. Ebből nem módosítottunk kategóriakapcsolatot.

A gyűjtő v2 változata a `https://www.emag.hu/homepage` oldalról indul, és külön naplózza a betöltött, valamint az operátori beavatkozás utáni címet. Black Friday-átirányítás esetén a böngészőben újra megnyitható a `/homepage`, még a rögzítés elindítása előtt. Csak látható szövegegyezést választ, gyökérenként külön kezeli a hibát, és a kategóriaoldalak gyűjtését a menühibától függetlenül végrehajtja. A már rögzített részadatokat megtartja, a hiba fázisát és a menükapcsolók személyes adatok nélküli technikai állapotát is naplózza.

**Ajánlott új futtatás PowerShellben, a saját projektkönyvtárban:**

```powershell
git pull --ff-only origin main
.\.menu-venv\Scripts\python.exe scripts/collect_emag_menu_details.py --channel chrome --manual --category-url https://www.emag.hu/televiziok/c --output "$env:USERPROFILE\Desktop"
```

1. Kezeld a sütikérdést, majd Enter a terminálban.
2. A böngészőben nyisd meg a Kategóriák menüt. Minden főcsoport fölött várd meg az almenüt, és az oldalra fókuszálva nyomj **Alt+Shift+M**-et (vagy F8-at). Ez a kézi mód nem próbálja automatikusan hoverelni a hibás kapcsolót.
3. Ha kész a 13 panel, Enter a terminálban. A televízió kategóriaoldal ezt követően külön feldolgozódik.
4. Az új `emag-menu-details.zip` csomagot add át akkor is, ha valamelyik rész hiányos; a részadatok megmaradnak.

Ha most csak a kategóriaazonosító bizonyítéka szükséges, a menü teljesen kihagyható:

```powershell
.\.menu-venv\Scripts\python.exe scripts/collect_emag_menu_details.py --channel chrome --only-categories --category-url https://www.emag.hu/televiziok/c --output "$env:USERPROFILE\Desktop"
```

Az új `mode`, `menu_complete`, `requested_category_count`, `category_pages_complete` és fázisonkénti hibamezők segítik az ellenőrzést. A részleges csomag nem lesz teljesnek vagy Marketplace-azonosságot igazolónak minősítve. Automatikus megfeleltetés és adatbázisírás továbbra sincs.
