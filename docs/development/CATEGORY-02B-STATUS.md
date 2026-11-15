# CATEGORY-02B — API-független frontend és integrációs készültség

Feladat: [#17](https://github.com/bizsis/adatdusito/issues/17).
Alap: `main` @ `80b0dce5b5270eb5de1ccecbfef5427ce35aa2c3`.
Branch: `codex/category-02b-frontend`.

**Nem kész, integrált CATEGORY-02 funkció.** A koordinátor megerősítette, hogy
Claude CATEGORY-02A végleges API/DTO-szerződése még nincs publikálva. A folytatás
engedélyezett köre az API-tól független komponensek és a mockolt válaszokkal futó
tesztek. Nem implementálunk vagy állítunk késznek végleges endpointot, backend-
DTO-t, adatmentést vagy szerveres kategóriabesorolást.

## 1. Elkészült, frontendként ellenőrizhető részek

| Rész | Megvalósult UI | Valódi API-integráció |
| --- | --- | --- |
| Terméklista | A meglévő `ProductData` opcionális bővítése: eredeti/saját kategória, külön belső kategória, pontosan „Automatikusan besorolt” / „Ellenőrzést igényel”, eredet és kézi védelem. Az automatikus tétel is szerkeszthető. | Várja a terméklista és részlet DTO-t. A produkciós `App` továbbra is a régi, működő listát hívja. |
| Szűrés és lapozás | Keresés debounce-szal; státusz/kategória/forrás; átlátszatlan lapozási jel; csak egy kapott oldal renderelődik. Nincs teljes állományt letöltő vagy lokálisan végigszűrő kód. | A UI a paramétereket a frontend portnak adja át; a valódi szerveres filter/cursor adapter hiányzik. |
| Bizonytalan tétel | Indok, szervertől származóként kezelendő megbízhatósági adat, maximum három alternatíva; alternatíva egy kattintással előválasztható, de ettől nem mentődik. | A pontszám skálája/jelentése, állapotenum és alternatíva-DTO egyeztetendő. |
| Jóváhagyott kategóriaválasztó | Kereshető, lapozható, lefelé/felfelé navigálható választó; strukturális csoport nem választható terméknek. | Nem másoljuk be vagy találjuk ki a 412 kategóriát; a végleges backend szolgáltatja a jóváhagyott elemeket és kiválaszthatóságukat. |
| Saját kategóriatérkép/profil | Külön nézet, saját kategória és belső kapcsolat, profil, jóváhagyás, audit-/lock-jelzés; öröklődésre/érintett termékekre vonatkozó előnézeti szándék. | A valódi mapping létrehozás/jóváhagyás, öröklődés és adattartósítás backendfüggő. |
| Kézi javítás | Indok, kategóriaválasztás, előnézet; mentés csak ténylegesen megadott aszinkron callback után jelez sikert. Saját kategória/érték nem szerepel a belső besorolás módosítási szándékában. | Revízió, lock, audit és újraimporttal szembeni valódi védelem CATEGORY-02A feladata, még nem integrációtesztelt. |
| Tömeges művelet | Oldalnyi kijelölés vagy szerveres snapshotot képviselő átlátszatlan handle; előnézet, érintettség, védett/kihagyott és konfliktusos tételek; ütközés mellett nincs alkalmazás. | Token, lejárat, részleges siker, futásokra bontás, job-DTO és backendjogok nincsenek feltételezve. |
| Admin küszöbkomponens | A kijelzett érték betöltő callbackből jön, mentésnél a visszakapott érték látszik. 98% csak a tesztadapter egyik válasza; nincs helyi 98-as default vagy besorolási döntés. | Végleges beállítás-API, százalék/arány mérték, jogosultság és normál adminfelületbe bekötés függőben. |
| Importáttekintés | `ImportWorkspace` opcionális összegző komponense, eredményszámlálókkal; nem új uploader. | Valódi eredményszámlálók, veszteségmentes sajátparaméter-import és feldolgozási határ a backendhez tartoznak. |
| Mobil/asztali nézet | Cloud & Teal; asztalon táblázat, keskeny nézetben címkézett termékkártyák; a státusz és kategória nem csak vízszintes görgetéssel olvasható. | Valós adathosszakkal és végleges DTO-val ismét ellenőrizendő. |

A belső eMAG-paraméterdonor csak lenyitható technikai metaadat. Nem írjuk át az
eredeti saját kategóriát. A két státusz kért megnevezése marad; kézi jóváhagyás
eredete külön metaadat, nem új harmadik státusz és nem helyi automatikus döntés.

## 2. Pontos technikai határ

- `frontend/src/classification/presentation.ts`: **frontend megjelenítési propsok
  és callback-portok**, nem wire DTO-k. A `ProductCard`, `MappingCard`, UI-szűrők,
  `EditIntent`, `ChangePreview`, `PresentationAccess` nevei/mezei nem a backend
  mezőneveire tett javaslatok. Az adapter később teljesen eltérő backend-sémából
  is előállíthatja őket. `editContext` tartalmát a UI nem értelmezi.
- E rétegben nincs `fetch`, végleges URL, szerveres szerepkód, helyi besorolási
  algoritmus, referenciaadatbázis-írás vagy alapértelmezett sikeres mentő callback.
- A `ProductData` csak kifejezetten átadott `classification` prezentációs
  szolgáltatásokkal kapcsol az új megjelenítésre. Enélkül az eredeti API/nézet
  változatlanul fut. Az új munkafelület külön lazy chunk, nem töltődik be a régi
  lista használatához. Az éles `main.tsx` nincs módosítva/bekötve.
- A `ClassificationWorkspace` `workspaceKey` kontextusváltáskor újramountol;
  késői olvasások és kijelölési/mentési visszajelzések nem kerülhetnek át másik
  munkaterületre. A portpéldány legyen stabil egy kontextusban, ne jöjjön létre
  új objektum minden szülő-renderben.
- Az írási vezérlők UI-jog és ténylegesen megadott choices/preview/apply callback
  nélkül nem jelennek meg. Ez nem helyettesíti a szerveres RBAC/scope ellenőrzést.
- Előnézet változtatásakor a korábbi előnézet érvényét veszti. A 409-et jelző
  prezentációs konfliktus megszünteti a menthetőséget, és új betöltést kér.
  Mentés/visszatöltés után a régi lapozási snapshot és kijelölés nem használódik újra.
- Megbízhatóság és küszöb puszta megjelenítési értékek. A frontend nem számol
  státuszt pontszámból, és nem ad automatikusan jóváhagyást a küszöb átállításakor.

**50 000 csak futásonkénti maximum.** A mock-lista 125 000 összes találatot és
lapnyi terméket ad; ezt a UI nem vágja 50 000-re. Nagy teljes kijelölésnél a mock
előnézet több futásra bontás szükségét jelzi, az alkalmazás pedig tiltott marad.
A frontend nem talál ki saját batch-darabolást vagy tenant-kvótát. A végleges
futásellenőrzés és ütemezés CATEGORY-02A szerződésére vár.

## 3. Tesztadapter, nem produkciós API

`frontend/tests/classification/` egy önálló Vite teszt-entry. Kizárólag a tesztekben
használja a `/__category02_test__/…` szintetikus útvonalakat és JSON-válaszokat.
Ezek **nem endpoint-javaslatok és nem CATEGORY-02A DTO-k**. A produkciós Vite build
nem használja ezt az entryt, a frontend Docker build inputjából a `tests/` kizárt.
Külön teszt ellenőrzi, hogy az éles bundle nem tartalmazza a tesztadapter URL-jeit.

Az új böngészőtesztek (`scripts/tests/test_classification_presentation_browser.py`):

1. A két státusz, külön saját/belső kategória, nulla megbízhatósági érték és
   maximum három alternatíva; 1440 és 390 px.
2. Lapozás és adapternek átadott keresés/státusz/kategória/forrás, nem lokális
   teljesállomány-szűrés. A cursor új filterhez nem vihető át.
3. Automatikus termék kézi javítása, kötelező előnézet, visszaigazolt mentés,
   visszakapott lock/audit/eredet, változatlan saját kategória.
4. Mock HTTP 409 → prezentációs konfliktus: nincs hamis siker vagy régi előnézettel
   új mentés; friss adatot kell kérni.
5. Saját kategóriatérkép előnézete/jóváhagyása és az öröklődési szándék átadása,
   védett rekordokra figyelmeztetés. Ez nem bizonyít backend cascade-ot.
6. Írási jog vagy tényleges mentő callback nélkül nincs szerkesztési/bulk vezérlő.
7. Teljes szűrt kijelölés átlátszatlan handle-lel, 125 000-es összesített számmal;
   a futáskorlát miatti, szerver által jelzett bontási igényt nem kerüli meg.
8. 98%-os **mock-válasz** megjelenítése; mentett új érték visszaolvasása; a termék
   besorolási státusza ettől nem változik frontend-logikával.
9. Tenantváltás, kijelölés törlése, későn visszatérő régi válasz eldobása akkor is,
   ha egy tesztadapter a transport abortot nem támogatja.
10. Strukturális csoport nem választható; mock 403 nem vezet mentéshez.
11. Ütközéses előnézet nem alkalmazható; API-olvasási hiba nem üres sikerlista.
12. Alternatíva kiválasztása nem automatikus mentés. Produkciós bundle-ben nincs mock.

Ezek UI/controller regressziók. A valódi API jogosultságát, újraimport-védelmet,
adattartósítást, globális 412-es lefedettséget és százzezres MySQL-skálázást nem
állítjuk velük ellenőrzöttnek.

## 4. A végleges szerződés után bekötendő részek

| Kérdés CATEGORY-02A-hoz | Szükséges integráció |
| --- | --- |
| Terméklista/részlet útvonala és DTO-ja, pontos státuszenum, saját/eredeti/belső kategória és donor mezői | A valódi válasz → prezentációs modell adaptere a meglévő `ProductData` számára. |
| Szűrők jelentése, kurzor/lapméret, kategória saját vagy belső jelentése, forrásválaszték, összesítések | Tényleges szerveres keresés/filterezés; százzezres tárolt készlet mellett oldalméretű payload. |
| Jóváhagyott 412 kategória és strukturális elemek keresése, részleges fa / kiválaszthatóság | Valódi kategóriaválasztó adapter. Nem a 2 669 donorforrás-csomópont automatikus átvétele. |
| Saját kategóriatérkép/profil jóváhagyása, érintett kör, öröklődés és kézi lock szabálya | Valódi mapping- és jóváhagyásadapter, pontos hatáselőnézettel. |
| Revízió/ETag, 409 válasz, idempotencia, bulk snapshot, preview, apply és részleges siker/job | Valódi, jogosultságot ellenőrző írás. A konfliktus a HTTP-státuszból érkezzen, ne hibaszöveg-felismerésből. |
| Adminbeállítás olvasás/mentés, százalék vagy arány skála, scope/jog, default 98% | Beállításadapter és elhelyezés a meglévő adminbeállítás-folyamatban; nincs párhuzamos frontend-lokális beállítástár. |
| Importeredmények és a futásonkénti 50 000-es validált maximum hibaválasza | Meglévő `ImportWorkspace` összegzőjének valós adatbekötése; nincs kliensoldali csendes levágás. |

A valódi adapter a meglévő session/CSRF/Origin és magyar API-hibakezelő megoldást
használja majd; ezek mellé most nem készült második produkciós fetch/auth kliens.
A közös helper jelenleg általános `Error`-t ad vissza: a 409-es státusz megőrzésének
frontend transport-illesztését a szerződéssel együtt kell megoldani és tesztelni.
A reference globális assignment végpontja nem használható termékmentésre.

Bekötés utáni kötelező tesztek: valós API-n termék- és mappingmentés/újraolvasás,
jog- és tenant-izoláció, audit és reimport utáni lock, valós 409, öröklődés,
98%-os backenddefault, 50k futáshatár és >50k tárolt állomány. Ezek jelenleg
**integrációra várnak**. A CATEGORY-02A publikációja nélkül nem aktiváljuk az új
szolgáltatásokat az éles `App`-ban, és nem jelentjük késznek az I. fázist.

## 5. Ellenőrzés és kiadás

```bash
cd frontend
npm ci
npm run lint
npm run test:lint
npm run build
cd ..
PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
PYTHONPATH=backend python -m pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py \
  scripts/tests/test_emag_menu_export.py
```

A pytest böngésző-fixture saját ideiglenes könyvtárba építi a teszt-entryt;
`CATEGORY02_TEST_DIST` csak ehhez a tesztbuildhez tartozik, nem új alkalmazásbeállítás.
Az új `*_browser.py` fájlt a meglévő CI automatikusan felveszi. Backend, migráció,
dependency-lock, `.env`, CI-szabály vagy VPS-konfiguráció nem változott. A normál
alkalmazás régi működésének regresszióit is futtatni kell.

Ez a változás API-integrációra váró frontend-előkészítésként, külön PR-ben adható
át. Nem deploy és nem main-merge; a végleges szerződés után új adapter- és valós
integrációs commitok szükségesek.
