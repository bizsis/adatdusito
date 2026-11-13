# CODEX 02 – ellenőrzési jegyzőkönyv

Dátum: 2026-11-13 (Europe/Budapest). Helyszín: izolált Codex felhőkörnyezet; **VPS-telepítés nem történt**.

## Eredmények

| Ellenőrzés | Eredmény |
| --- | --- |
| Backend pytest | **31 sikeres teszt**, 1 Starlette/AnyIO deprecation warning |
| Eredeti CODEX 01 tesztek | Továbbra is sikeresek |
| TypeScript + Vite build | Sikeres |
| Ruff alapellenőrzés (E9/F) az új backend-/tesztkódon | Sikeres |
| Docker Compose build, TLS-ellenőrzés és ideiglenesen mountolt CA | Sikeres backend-, migrátor-, worker- és frontend-image |
| MySQL 8.0 Alembic upgrade | **0002**, sikeres; ismételt upgrade is sikeres |
| Migráció és ORM-metaadat összevetése MySQL-en | Nincs eltérés |
| Szintetikus referenciafelhasználó SHOW GRANTS | USAGE és SELECT a három referencia-táblára |
| MySQL-alapú API-integráció | Belépés, CSRF, tenantizoláció, adminjogok, napló, kategóriafa, belső ID-kapcsolatok és kurzoros értéklapozás sikeres |
| Interaktív Superadmin-bootstrap | Docker TTY-val sikeres; jelszó nem szerepel argumentumban vagy kimenetben |
| Böngészőpróba Chromiumon | Asztali 1440×1000 és mobil 390×844 sikeres; nincs JavaScript-hiba vagy vízszintes oldal-túlcsordulás |
| Backend/Redis/worker/referencia readiness + Celery ping | Sikeres |
| GitHub Actions | Workflow hozzáadva backendteszthez, frontendbuildhez és Docker-buildekhez; távoli futás eredményét ez a jegyzőkönyv nem állítja |
| Valódi dev.pinfo.hu / VPS | Nem telepítettük és nem ellenőriztük újra |

## Tesztelt határok

- Hibás, ismeretlen és inaktív felhasználó belépése elutasított; a hiba nem árulja el a fiók létezését.
- HttpOnly/Secure/SameSite cookie, hash-elt sessiontoken, lejárat, logout, jelszócsere és visszavonás ellenőrzött.
- CSRF nélküli, nem ASCII CSRF-tokenes és idegen Originről érkező módosítás elutasított.
- Tenantadmin másik ügyfél listáját nem olvashatja/módosíthatja; Superadmin-jogot nem oszthat ki; megosztott fiók globális jelszavát nem írhatja át.
- Az utolsó aktív Superadmin és ügyféladmin védett; a szerep változása a következő kérésre érvényes.
- Adatfeldolgozó és ellenőrző referenciaadatot olvashat, adminfunkciót nem hívhat.
- A kategóriák külső eMAG-szülőazonosítója különbözik a belső ID-tól; hiányzó szülő belső-ID-ütközés esetén sem kapcsolódik tévesen. Ciklus és hiányzó szülő jelzett.
- Egy paraméter eMAG-ID-ja több kategóriában is előfordul: az értékek mindig a belső paraméter-ID szerint kerülnek lekérdezésre.
- 125 mesterséges paraméterérték lapozása tesztelt, ismétlés/kimaradás nélkül; az API legfeljebb 100 elemet enged kérni.
- A referencia API csak SELECT SQL-t ad ki; az engine megtagadja az író/DDL utasítást, az alkalmazás-migráció metadata-ja nem tartalmaz referencia-táblát.
- A kezdeti tesztfixture MySQL-klienskódolását javítottuk (`SET NAMES utf8mb4`); a javítás után az ékezetes felület és adatmegnevezések böngészőben is sikeresen ellenőrzöttek.

## Ismétlés

```bash
cd /workspace/adatdusito
bash scripts/cloud-install.sh
bash scripts/cloud-start.sh
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
```

A böngésző és az API-integrációs tesztekhez az izolált cloud adatbázisban létrehozott **teszt** Superadmin szükséges. Első alkalommal:

```bash
docker compose -f compose.yaml -f compose.cloud.yaml exec backend python -m app.bootstrap --email SAJAT_TESZT_EMAIL --name "Teszt admin"
.venv/bin/pip install -r scripts/browser-requirements.txt
```

Az integrációs eszköz kizárólag a helyi 18080-as portot használja. A tesztbelépési adatok egy checkouton kívüli, 0600 jogosultságú JSON-fájlban legyenek (`email`, `password` mezők); ne használj valódi VPS-belépést. Ez csak a teszteszköz inputja, nem alkalmazásbeállítás vagy alapértelmezett fiók.

```bash
.venv/bin/python scripts/verify_integration.py --credentials /BIZTONSAGOS_UTVONAL/test.json
.venv/bin/python scripts/browser_smoke.py --credentials /BIZTONSAGOS_UTVONAL/test.json
```

A böngészőteszt `/usr/bin/chromium` böngészőt használ; más gépen ezt az elérési utat szükség szerint módosítani kell. A tesztadatok az izolált cloud DB-ben megmaradnak, minden integrációs futás egyedi tesztügyfélneveket készít. A belépési limit a teszteszközökre is vonatkozik; sok ismételt futás után várd meg a 15 perces ablak végét, vagy használj külön tesztfiókot.

A jelen futás képernyőképei: `/tmp/adatdusito-codex02-browser/`. A repo nem tartalmaz jelszófájlt, `.env`-et, helyi DB-állapotot vagy képernyőképen rögzített valódi ügyféladatot.

## Átadás

A `compose.yaml` a megadott, működő VPS-konfigurációból csak az external `adatdusito-dev-net` blokkot emeli be a korábbi GitHub-verzióhoz. Meglévő szolgáltatás, port és VPS-hálózati paraméter nincs átírva. A felhőbeli teszthez kizárólag a külön `compose.cloud.yaml` indít szintetikus MySQL-t, másik Compose-projekttel és helyi porttal.

A 0001 migráció változatlan. Az új 0002 csak az `adatdusito_dev` adatbázist érintheti. A valódi referenciaadatbázis sémáját és a parent_id jelentését az üzemeltető adta át; a valós 2,8 milliós adathalmazon teljesítménymérést nem végeztünk. Értékszöveg részszavas keresésénél a meglévő indexek miatt nagy paraméterhalmazon lassabb lekérdezés előfordulhat; referenciaindex-módosítás nem történt.

A kézi VPS-frissítés, mentés, inicializálás és utóellenőrzés parancsai: [deployment.md](deployment.md). A GitHub-kód átadása nem telepítés, és nem igazolja a távoli HTTPS-működést.

## CODEX 02 javítás – aktív kategóriák és bejelentkezési felirat

Dátum: 2026-11-13. A normál referenciafelület minden kategóriaútvonala backendoldalon `is_allowed = 1` feltételt alkalmaz. Ez a listára, keresésre, lapozott összesítésre, adatlapra, szülőválasztásra és szülőláncra is vonatkozik. Az inaktív kategória paraméter- és értékútvonala sem használható kerülőútként. Inaktív vagy hiányzó szülő alatt az aktív kategória önálló gyökérelemként elérhető marad, az aktív leszármazottakkal együtt. A szülőkapcsolat továbbra is külső eMAG-azonosító szerint oldódik fel.

- **46 sikeres backendteszt**, ebből 15 új regressziós eset. A korábbi 31 teszt továbbra is sikeres; 1 meglévő függőségi deprecation warning maradt.
- Új esetek: 0/NULL állapotok kizárása; keresés név/eMAG-ID szerint; aktív román nevű és aktív Deleted nevű kategóriák megtartása; inaktív szülő alatti aktív gyermek/leszármazott; szűrt lapozási elemszám; közvetlen inaktív kategória-/paraméter-hozzáférés elutasítása.
- TypeScript/Vite build, Compose-build és MySQL-alapú API-integráció sikeres a külön, szintetikus cloud környezetben.
- Chromium-próba asztali és 390 pixeles mobil méretben sikeres, JavaScript-hiba nélkül. Az új bejelentkezési felirat pontos szövege külön böngészőasserttel ellenőrzött.
- A `.env`, a Compose external hálózat, az adatbázisséma és a migrációk változatlanok. A valódi `pinfo_db` adatbázishoz nem nyúltunk, VPS-telepítés nem történt.

A VPS-en kizárólag kézi kód-/image-frissítés szükséges, a korábbi üzemeltetési felmérés és esetleges helyi Git-eltérések rendezése után:

```bash
cd /opt/adatdusito
git status -sb
git pull --ff-only origin main
docker compose build
docker compose up -d --no-build
bash scripts/smoke.sh https://dev.pinfo.hu
```

Ellenőrizd böngészőből a bejelentkezési feliratot, az aktív kategóriák keresését és az inaktív szülő alatti aktív kategóriák elérhetőségét. A teljes gyökérlista darabszáma nem azonos az összes aktív kategória számával: a teljes aktív lista `roots=false` szűréssel kérhető. Ne futtass referenciaadatot módosító SQL-t, és ne másold felül a működő `.env` fájlt.

## CODEX 03A – egységes fa, strukturális kategóriák, forrásbizonyíték

2026-11-13, izolált felhőbeli fejlesztés. **50 sikeres backendteszt**, egy meglévő Starlette/AnyIO deprecation warning. A korábbi aktív-only üzleti szabály tesztjeit az új követelménynek megfelelően pontosítottuk; a jogosultság-, session-, tenantizolációs és olvasási védelmi tesztek továbbra is sikeresek.

- Külön teszt a 1496 strukturális szülő → 79 besorolható televízió kategóriára, 46 közvetlen paraméterrel.
- Hiányzó 2661 külső szülő nem keveredik az azonos számú belső ID-val; nincs kitalált kapcsolat.
- Ciklus felismerése és jelzett, véges megjelenítése; Deleted jelölésű rekordok alapértelmezett kizárása.
- Strukturális kategória navigálható és paraméterei olvashatók, de a besorolási végpont 409-et ad. Nincs szülőparaméter-öröklés.
- Teljes strukturális szülőút keresési találatban és adatlapon; gyermekszám és közvetlen paraméterszámok ellenőrzöttek.
- 10 000 szintű gráf iteratív feldolgozása tesztelt; 1 000 szintű API-szülőút és gyökérlista kérésenként pontosan két referencia-SELECT-tel készül. A gyökérlista kimenete korlátos, az értéktáblát nem tölti be.
- Forrásmegfigyelés auditált és csak Superadmin írhatja. Pending webshop-ID nem lesz kategória, névegyezés és numerikus URL sem hoz létre automatikus megfeleltetést. Szintetikus JSON-LD-minták ellenőrzöttek.
- MySQL 8-on az új 0003 migráció sikeres; a séma egyezik az ORM-metaadattal. A valós VPS-migrációt nem futtattuk.
- A MySQL-integráció a forrásregisztert és a pending megfigyelést is ellenőrzi; ezek nem változtatják meg a kanonikus kategóriaszámot.
- TypeScript/Vite- és Compose-build sikeres. A Chromium-próba asztali és mobil méretben ellenőrzi a meglévő adminfunkciókat, az új teljes útvonalat, kijelölést, felfelé/lefelé navigációt, fa-szűrőt és forrásregisztert.

Az üzemeltető által ellenőrzött valós adatok: 2669 kategória, 4 igazolt gyökérszint, 2565 gyökérből elérhető rekord; 1807 kategória paraméterkészlettel, 862 paraméter nélkül; 29398 definíció, 2847054 megengedett érték. Ezek nem a háromkategóriás cloud fixture eredményei. A runtime jelentés mindig a ténylegesen csatlakoztatott adatbázist méri.

Forrásvizsgálat: robots, sitemap és dokumentációs belépési cím kezdeti kérései a környezeti proxy CONNECT 403 tiltásába ütköztek. A megismételhető kutatóeszköz robots-ellenőrzés nélkül nem tölti a webshopot. Nincs sikeres új webshopfa-letöltés vagy bizonyított teljes magyar webshop-lefedettség. A forrás- és architektúrajelentés: [codex03a.md](codex03a.md).

A `.env`, a Docker Compose-fájlok, a 0001/0002 migrációk és a VPS szolgáltatásbeállításai változatlanok. A referenciaadatbázishoz nem adtunk író jogosultságot. VPS-telepítés nem történt; termékimport, AI-kutatás és rendszeres szinkron nem készült.

## Valós emag.hu menüexport feldolgozása

Forrás: a felhasználó által feltöltött, Windowsos `emag-menu-export.zip`, `https://www.emag.hu/homepage`. A feldolgozás offline történt, a csatolmány tartalma adatként, nem utasításként kezelve. A feldolgozott, nyilvános navigációs metaadat a `backend/reference_data/web_navigation.json` állományban verziózott; az eredeti ZIP nem került a repositoryba.

- 13 főcsoport eredeti DOM-sorrendben; 609 JSON-menühivatkozás. A 420 kategóriaoldal-hivatkozás nem 420 igazolt Marketplace-kategória.
- 79 szekciókapcsolat továbbra is ellenőrzendő, nincs kitalált szülő.
- 18 HTML/JSON URL-eltérésnél az adott panelen belüli egyedi menü-ID-val azonosított, közvetlen JSON-link az elsődleges. A gyűjtő névalapú href-visszaállítási hibája javított; az eredeti bizonyítékok hash-ei megmaradtak.
- Windows CRLF/LF hash-eltérés csak a pontos, dokumentált sorvégtranszformációval fogadható el; a bájthash és a manifesthash is tárolt. Más tartalommódosítást elutasítunk. Az új gyűjtő bájtazonosan ír HTML-t.
- **59 sikeres backendteszt**: köztük valódi menü-snapshot, 13 főcsoport sorrendje, ID-névterek, szekció–gyermek kapcsolat, kapcsolódó márka-/szűrőlinkek, igazolt és visszavont, forrásverzióhoz kötött paraméterkapcsolat, explicit belső FK és tenantjogosultságok. 1 meglévő függőségi deprecation warning.
- **9 sikeres exportáló-/kiegészítőgyűjtő-teszt**, szintetikus Chromium DOM-on; nincs élő eMAG-gyűjtés állítva.
- TypeScript/Vite-build, Compose-build és MySQL-alapú API-integráció sikeres.
- Asztali és 390 pixeles mobil böngészőpróba sikeres, 13 valódi magyar gyökérrel; útvonal, fel/le navigáció, keresés, pending kapcsolat miatti paramétertiltás és a korábbi adminfunkciók ellenőrzöttek. Nincs JavaScript-hiba vagy oldal-túlcsordulás.
- Kezdeti automatikus Marketplace-megfeleltetés: **0**. A menü 79-es azonosítója Könyvek főcsoport, a Marketplace 79 Televíziók: ezeket nem tévesztjük össze.

A bizonyított rész már egyetlen közös böngészőben jelenik meg. A 79 hiányos szekciókapcsolathoz és az egyelőre igazolatlan Marketplace-azonosságokhoz külön `scripts/collect_emag_menu_details.py` készült; a gyűjtött általános category.id mező önmagában továbbra sem Marketplace-azonosító. [Részletes feldolgozási jegyzőkönyv és futtatási parancs](verified-webshop-navigation.md).

A pinfo_db, `.env`, Docker Compose external hálózat és a migrációk változatlanok. Új adatbázis-migráció és VPS-telepítés nem történt.
