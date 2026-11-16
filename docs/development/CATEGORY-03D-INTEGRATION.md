# CATEGORY-03D – teljes közös integráció

Feladat: [#32](https://github.com/bizsis/adatdusito/issues/32). Gazda: Codex
(integráció, frontendadapterek, integrációs tesztek); üzleti és merge-döntés: Vezér/Tulajdonos.
Ág: `codex/category-03d-full-integration`. PR: [#37](https://github.com/bizsis/adatdusito/pull/37). **Draft integrációs PR; nem automatikusan
merge-elhető és nem telepítendő a VPS-re.**

A tulajdonos a feladat közbeni pontosításban kifejezetten a meglévő 03B felület
03C-bekötését is az integrációhoz sorolta. Ezért a tesztág az inputok összevezetése
mellett az implementált 03C-szerződést is beköti. Nincs új üzleti paraméter-, donor-,
kategória-, import-, kutatási, fizetési vagy exportszabály.

## Reprodukálható bemenet és integrációs sorrend

Az induláskor frissen lekért main: **`80b0dce5b5270eb5de1ccecbfef5427ce35aa2c3`**.
Az eredeti main worktree-t és a forrás-PR-ek ágait nem módosítottuk.
A PR-headeket a `refs/pull/{n}/head` refekről rögzítettük, nem ágnevükből vagy
korábbi dokumentációs SHA-ból feltételeztük őket.

| Sorrend | Input | Rögzített head SHA | Integrációs merge commit |
|---:|---|---|---|
| 1 | #18, CATEGORY-02A, worker-bekötéssel | `e946b93a0428f485a7131c157ced4a6f81773f13` | `dd397a8b16401967c7322783cc9c39ac9b1e6fb4` |
| 2 | #25, CATEGORY-02C audit | `47d0cc66490c1cb7a0301bdf342e4a12a06159e6` | `1581bb869c3721249771f96e0d5886904e42f37b` |
| 3 | #26, CATEGORY-03A | `c05746d3b34cb2f0638dc6ece19988d6a9c37483` | `a5e75e8e73cc6ff2343027d60fbc9898695869d9` |
| 4 | #29, CATEGORY-03C és közös AGENTS | `369fc989804a7c94964e93a9e73d53e84d1f3df5` | `343c65cfc388cd05cab31833915ac3552fd42518` |
| 5 | #22, CATEGORY-02D frontend/integráció | `a780c65d95f42d258a012139376d89dd2c343c48` | `7387dd7cc52230e2d89d33f3c21a37bfcb47b7b5` |
| 6 | #27, CATEGORY-03B, TOTP-diagnózissal | `9babde51262fc8e3376ed58acc86b08579cd932f` | `29364f3acf07cf8cceb7042fb37cd149aedc3eac` |
| 7 | #31, AUTH-09 determinisztikus teszt | `4ffcfb22a2a476948dc322839a65a558ce04ad9f` | `f948441c64ceba3fc1d44cbc428b61a117e6c2ed` |
| 8 | #36, RELEASE-02 MySQL downgrade, a #37 kiegészítő feltétele | `3df4b20afbd8be6c4ab019ac245d3bf2e1071eed` | `d39ae88b3144daf6087d2d0f544e9276e10f7ee1` |

Minden lépés normál `git merge --no-ff`; **nem volt szöveges merge-konfliktus**.
Nem kellett Claude-fájlt önállóan javítani vagy felülírni. A 03D saját javításai
frontend-, böngészőteszt-, általános integrációsteszt-, dokumentációs és CI-trigger
fájlokra korlátozódnak. A #36-ot a #37-ben előírt kiegészítő feltételként, Claude
eredeti commitjaival integráltuk. A három migráció downgrade-javítása kizárólag
ebből az inputból származik; a 03D nem ír saját backendmódosítást. AST-összevetés
igazolja, hogy a 0009/0010/0011 `upgrade`, `revision` és `down_revision` része
a #29 állapotához képest változatlan.

A #25 és #26 párhuzamos ág: mindkettőt explicit integráltuk. A #29 ancestry-je
önmagában nem számított a #25 auditjának bizonyítékául. A #22/#27 régebbi #18-alapja
nem írta vissza a legfrissebb #18 worker- és háttérfeladat-változásait.

Ellenőrzés a teljes klónban (a GitHub CI sekély checkoutján a bemeneti refek nem
feltétlenül állnak rendelkezésre):

```bash
for input in e946b93 47d0cc6 c05746d 369fc98 a780c65 9babde5 4ffcfb2 3df4b20; do
  git merge-base --is-ancestor "$input" codex/category-03d-full-integration || exit 1
done
git diff d39ae88..codex/category-03d-full-integration -- backend
```

Az utolsó parancs nem mutathat 03D által írt backendmódosítást.

## A közös működés és saját integrációs javítások

### 02A/02C: kategória és donor

- A jóváhagyott fa megmaradt: 13 gyökér, 457 besorolható kategória. Nincs új forrásfa.
- A három kétes csomópont–donor kapcsolat változatlanul `pending_review`:
  `web-item-114-3492` / 385; `web-item-114-3820` / 58; `web-item-83-4339` / 63.
- A többprofilos kategóriához explicit profilválasztás kell. Ez nem donorjóváhagyás.
- A donoraudit fájlja a 03C jóváhagyási séma-lenyomat része. A közös teszt a
  tényleges `donor_review.json`-t és a két szabályfájl fingerprintjét ellenőrzi.
- **Javított integrációs eltérés:** a kategóriatérkép 2000 termék felett háttérben
  sorol újra. Ilyenkor a mentés `products_changed` és `locked_skipped` mezője `null`,
  a `reapply` adja a jobazonosítót és a teljes darabszámot. A korábbi #22 validator
  csak számokat fogadott. A 03D szigorú, külön queued alakot fogad és külön szöveggel
  jelzi a háttérmunkát; ismeretlen darabszámból nem csinál 0-t vagy mentési hibát.
  A szinkron válasz és annak korábbi feliratai megmaradnak. Natív teszt: 2001
  tényleges tárolt termék, workerfeldolgozás, a kézi besorolási lock megőrzésével.

### 03A: változatlan revíziós út

Az egytermékes `preview/apply` és a hatókörös `parameter-runs` megmaradt.
Az apply csak `expected_revision`-t kap; **nem** 03C preview tokent és nem egy
korábbi számítás snapshotját alkalmazza. 409 után nincs vak újramentés.
A 03A `has_more` / `next_start_after_product_id` következő futása külön felhasználói
indítás, változatlan hatókörrel. Az 50 000 futáskorlátot nem keverjük a 2000-es
kategóriatérkép-küszöbbel vagy a teljes tárolt termékállománnyal.

A korábbi 50 002-es böngészőteszt egy időzítési hibáját javítottuk: a második
POST-választ meg kell várni az enqueue-lista olvasása előtt. A korábbi teszt a
kattintás után rögtön a még előző jobot olvashatta. Az ellenőrzés továbbra is
eltérő második jobot, 50 000 + 2 feldolgozott terméket és valódi folytatást vár;
az elvárást nem gyengítettük és backendkódot nem módosítottunk.

### 03C: a meglévő frontend bekötése

A `ParameterOverview` oldalnyi checkboxos vagy teljes szűrt kijelölést ad át a
szervernek. Nincs az összes termék-ID letöltése, név szerinti helyi megfeleltetés
vagy kliensoldali termék-batching. A teljes szűrt halmaz szerveres snapshot,
a kifejezett kijelölés legfeljebb egy oldal (a szerződés maximuma 100).

A `bulkApi.ts` a meglévő session/CSRF/tenant kliensre épül. Az új DTO-kat, nullokat,
sparse számlálókat, kindokat, állapotokat, azonosítókat és időpontokat futásidőben
ellenőrzi. A 03A és 03C jobalakját külön kezeli. A kiválasztás maximuma 250 000,
a futás maximuma 50 000; a teljes termékállomány ennél nagyobb is lehet.

A már meglévő `ParameterJobPanel` a 03C valódi műveletadatait is megjeleníti:
ismert snapshot-total, feldolgozott szám, futások száma, kihagyások, hibák,
megszakítás/folytatás, tételes és szűrhető/lapozható eredmények. Folytatás csak
`pending` vagy elakadt futásnál kérhető; a `cancelled` állapot nem folytatható. Az `outcomes`
ritka szótár, a hiányzó kulcs 0. `stale`, `changed_since_preview` vagy `error`
eredménnyel a kész alkalmazás **részleges siker**, nem „minden mentve”.

A tömeges alkalmazás a befejezett 03C előnézet tokenjét, a felhasználó által
látott pontos `expected_eligible` értéket, explicit megerősítést, indokot és
idempotenciakulcsot küld. A termék- vagy számítási revízió megváltozását a
szerver újra ellenőrzi. A source-overwrite számláló nem fedhető el 0-ként.

Az előkészítési ellenőrzés és jóváhagyás külön művelet. A kötelező, de üres
kutatandó hely önmagában nem tiltja; a bizonytalan jelentés/egység vagy donor
viszont blokkol. A jóváhagyások listája utolsó mérési számlálókat mutat;
a részlet élő érvényességet kér le. A termékrészlet is külön kijelzi az aktív
jóváhagyást és revízió-érvényességét. Újramérés és verziózott visszavonás is a
valódi API-t használja; egyik sem indít AI-kutatást és nem hagy jóvá donort.

Új tenant-jogok: `products.bulk` és `products.prepare.approve`. Az alkalmazáshoz
**products.parameters ÉS products.bulk** kell, a jóváhagyás önálló jog.
A Me-jogok változása a vezérlőkön is érvényesül; a backend minden kérést ellenőriz.

### Tokenek, lejárat, hiba és védelem

A selection/preview/check token csak az adott nézet memóriájában marad. Nincs
URL-ben, naplóban, DOM-ban, localStorage-ban vagy sessionStorage-ban. Tenant-
vagy terméknézetváltás után nem kerül át másik munkaterülethez. A kiválasztás
2 órás; az előnézet és ellenőrzés ugyanakkor jár le. A már megerősített futás
folytatódhat ezután is. A kliens az időpontot ellenőrzi, de a végső döntés a szerveré.

A JSON-válasz sérülése nem válik hamis sikerüzenetté. Ismeretlen kimenetelű
alkalmazásnál a felhasználó kifejezetten az **azonos tartalmú és azonos kulcsú**
kérést ismételheti; nincs automatikus retry vagy új kulccsal rejtett újraművelet.
Valódi 4xx validálási/revíziós/jogosultsági hibánál ez a helyreállító vezérlő sem
jelenik meg: új kijelölés/előnézet vagy friss jogosultság kell.

A nyers beszállítói forrásérték és a kézi paraméterlock megmarad. Az integrációs
életciklusban a 03C jóváhagyás után a 03A kézi szerkesztése növeli a revíziót,
és a korábbi jóváhagyás érvénytelen lesz. Ezután az újramérés nem érvényesíti vissza.

## Ellenőrzés és a bizonyíték határa

A normál böngészős válaszokat valódi FastAPI/SQLite szolgálja ki a produkciós
frontend bundle-nek. Az enqueue a tesztben helyettesített, az igazi
`product_jobs.advance_parameters` / `bulk_operations.advance` / reapply worker
függvény fut. Ez nem Redis/Celery infrastruktúra- vagy VPS-teszt.
A külön worker-only subprocess az API előzetes importja nélkül is ellenőrzi:
`infra.ping`, `supplier.import`, `products.reapply_category_map`,
`products.parameter_run`, `products.operation` regisztrációját.

Az első teljes integrációs csomag (`7d39f12`) helyi eredményei:

- Teljes backend/eszköz: **437 sikeres**.
- Korábbi böngészős regresszió: **113 sikeres** (14 backend-browser, 74 script-browser,
  25 CATEGORY-02D).
- 03A natív API-regresszió: **21 sikeres** (20 az első csomagban, a javított
  aszinkron enqueue-várakozású 50 002-es teszt külön is sikeres).
- 03D natív integráció: **17 sikeres**, a végső bundle-lel 205,24 s. Összes
  böngészőteszt: **151 sikeres** (113 korábbi + 21 03A + 17 03D).
- Menüexport: **14 sikeres**.
- Frontend lint/TS/build és Node 22 lint/TS: sikeres; **3 lintkonfigurációs teszt**.
- Backend/frontend Docker build: sikeres; runtime-only csomagok, `pip check`,
  appimport és worker-task regisztráció az image-ben is sikeres.
- Lock-resolver ellenőrzés: 49 runtime + 4 test-only pin egyezik; npm audit: **0**.

A 03D tesztek lefedik a mobil/asztali teljes jóváhagyási életciklust, a 03A kézi
javítása utáni érvénytelenséget, mindhárom pending_review donort, explicit profilt,
lockot/forrást, a szerveres kijelölést, idempotens helyreállítást, partial/stale
végkimenetelt, a két új jog együttes követelményét, CSRF-t, 409/422/503-at és
malformed DTO-t. A 401/404 és a tenantváltás/izoláció korábbi natív regressziója
és a 03C backendtesztjei is megmaradnak. Nincs biztonsági gate vagy teszt kihagyva.
A tesztekben szándékosan rontott transport-válaszok külön vannak megjelölve,
nem nevezzük őket backend-bizonyítéknak.

A tényleges SQLite-minta 250 001 tárolt terméket hoz létre: a teljes kijelölés
422, rejtett csonkolás és részleges snapshot nélkül. 250 000-nél sikeres, az
adatbázisban is ennyi snapshot-tétel van; a lejárat a válasz időpontjai alapján
2 óra (a két időpontfelvétel mikroszekundumos eltérését megengedve).
Egy 50 002-es szűrt részhalmaz 03C előnézete ugyanazon jobon **50 000 + 2**
terméket, **2 futásban** dolgoz fel, paraméterérték-írás nélkül. Ez valós SQLite
adat, nem mock számláló; **nem 250 000-es MySQL mérés**.

A RELEASE-02 beemelése után ugyanez a teljes backend- és böngészőcsomag
újrafut; a végső commit hosted CI-je külön ellenőrzi az összes jobot.
Az átadás a végső futás tényleges eredményét adja meg.

### RELEASE-02: saját MySQL migrációs újrateszt

A #36 integrálása után **saját, eldobható, helyi MySQL 8.0.46** konténeren futott
a `scripts/mysql_release02_downgrade_check.py --rounds 3`. Az üres loopback
adatbázist a script külön ellenőrizte; 2000 szintetikus terméket és importsorokat,
felhasználókat, tagságot és szerepköröket készített a 0008-as szinten.

- **56 ellenőrzés, 0 hiba**, exit 0; 16,96 s a teljes script.
- Három teljes `0011 → 0010 → 0009 → 0008 → 0011` kör és az egyes
  revíziópárok ismételt vissza/előrelépése.
- Minden szinten egyezik a teljes oszlop-/index-/idegenkulcs-séma, a kulcsszabályok,
  a megőrzött adatok és a jogkatalógus lenyomata.
- A jóváhagyás, paraméteralias és kategóriatérkép külön-külön megakadályozta
  a megfelelő downgrade-et; a megtagadás nem változtatta a sémát/adatokat.
- A migrációs lánc végül 0011-en állt. A tesztkonténer kizárólag helyi, szintetikus
  adatot tartalmazott; a VPS-re és a `pinfo_db`-re nem kapcsolódott.

Ez migrációs regresszió, **nem 250 000-es MySQL-teljesítménymérés**.
A #25/#26/#29 dokumentumokban szereplő további MySQL-eredmények Claude külön
mérései; nem keverjük a saját bizonyítékba. Éles adatokon nem teszteltünk.

### Futtatási parancsok

A projekt Python 3.12 runtime+test lockjai és a browser-requirements szükségesek;
a frontend Node 22 (Docker build stage-ben is ellenőrizve).

```bash
PYTHONPATH=backend .venv/bin/pytest -q -ra backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py
.venv/bin/pytest -q scripts/tests/test_emag_menu_export.py
(cd frontend && npm run lint && npm run test:lint && npm run build)
python backend/scripts/check_requirements.py --resolve
docker build -t adatdusito-ci-backend backend
docker build -t adatdusito-ci-frontend frontend
```

A Cloud buildhez szükséges CA a meglévő BuildKit `proxy_ca` secretként van átadva;
nem kerül image-rétegbe vagy Gitbe. A backend image runtime-only csomagellenőrzést
és alkalmazásimportot is kap. Nincs új függőség vagy lockmódosítás.

## Migrációs lánc, adatvédelem és rollback

Egyetlen, az eredeti backend-PR-ekből származó lánc: **0009 → 0010 → 0011**.
A migrációs regressziók az előző állapot meglévő termékeit/jobkurzorát és új jogait
is ellenőrzik. Új 03D migráció nincs; 0001/0002 és az összes upgrade változatlan.
A #36 kizárólag a 0009–0011 downgrade-jeit javítja MySQL-biztos sorrendre,
a döntésvédelmek megtartásával; részletek: [RELEASE-02-DOWNGRADE.md](RELEASE-02-DOWNGRADE.md).

- 0009: kategóriabesorolási app-táblák és kiegészítések.
- 0010: paraméterhelyek, aliasok, paraméteres műveletek.
- 0011: kiválasztás/tételek, műveleti eredmények, előkészítési jóváhagyások/tételek,
  plusz jobmezők és `products.bulk` / `products.prepare.approve`.
- A `pinfo_db` nem migrációs célpont. A 2 847 054 eredeti paraméterérték nincs újraimportálva.
- A 0011 downgrade **bármilyen meglévő jóváhagyásnál** megtagadott (a visszavont is
  előzmény). Jóváhagyás nélkül is elveszíti az új műveleti előzményeket.
  Éles adaton nincs automatikus downgrade: egyeztetett mentés-visszaállítás kell.
- Korábbi revíziók visszalépése további alkalmazásadatokat érinthet; nem ajánlunk
  általános, feltétel nélküli `alembic downgrade` parancsot.
- Félbeszakadt MySQL upgrade esetén a DDL nem tranzakciós. A RELEASE-02
  downgrade-javítása nem teszi automatikusan újraindíthatóvá a részleges upgrade-et;
  ilyenkor az ellenőrzött mentés visszaállítása szükséges.
- Verziókeveredés előtt rendezni kell a futó workerfeladatokat. A már alkalmazott
  rész megmarad megszakításkor is; egy rollback nem vonja vissza ezeket magától.

## Tulajdonos által külön jóváhagyandó merge-sorrend

A tesztág nem írja át a forráságakat. Ajánlott normál merge-sorrend (nem squash,
nem rebase és nem automatika):

1. #31 (main alapú determinisztikus AUTH-teszt).
2. #18 (friss worker/pending védelem).
3. #25 (02C audit), majd #26 (03A), majd #29 (03C).
4. #36 RELEASE-02, a #29 után és a migrációk első telepítése előtt.
5. #22 frontend/integráció, majd #27 frontend.
6. A jelen 03D draft PR a bekötési javításokkal, a friss mainre ellenőrizve és
   újrafuttatott CI-vel; csak a Tulajdonos külön jóváhagyása után.

A függő PR-ek base-ét az elődjük mainbe kerülése után a Tulajdonos/Vezér állítsa
át mainre, és nézze újra az effektív diffet. A #22/#27 eredeti commitjai a 03D
ancestry-jében benne vannak; normál merge esetén a Git már közös előzményként
kezeli őket, és a végső PR-ben a 03D javításai maradnak. Nem cherry-pickeljük vagy
másoljuk újra a frontend fájlokat mainbe. Squash/rebase választásakor ez az
ancestry-garancia megváltozik, külön integrációs döntés és újratesztelés kell.

A kibővített kiadási sorrendet külön detached worktree-ben végigpróbáltuk:
**#31 → #18 → #25 → #26 → #29 → #36 → #22 → #27**, utána a 03D
`217b23e` implementáció és `7d39f12` jelentés. Mindegyik merge konfliktusmentes;
a kapott fa bitre azonos a `d39ae88` integrációs állapot fájával.
A helyi próba commitja `4ced858cb40232dde6330e27e02fe1b57d1c32a0`;
ez nem main-merge. Ha main vagy bármely input a pinelt SHA-hoz képest elmozdul,
a jelen bizonyíték nem jelent automatikus jóváhagyást az új kombinációra.
A RELEASE-01 #34 külön audit/runbook PR; ez a tesztág nem írja felül és nem
állítja, hogy annak mainbe kerülése megtörtént.

## Staging/VPS előfeltételek (nem végrehajtott lépések)

Tulajdonosi jóváhagyás; mentés és visszaállítási terv; az app-adatbázis migrációinak
ellenőrzése 0011-ig; kompatibilis backend/worker/frontend image; a worker új taskjainak
regisztrációja; Redis/broker elérhetőség és szerepkörök/új jogok ellenőrzése.
Az újraméréshez és futásfolytatáshoz megfelelő tenant-jog szükséges.

A `.env`, az external `adatdusito-dev-net`, a MySQL-, Nginx-, UFW-, HTTPS- és
`pinfo.hu` beállítások változatlanok. Nincs VPS-parancsfuttatás vagy élesítés.
A terhelési határokat saját staging/adatbázis-méret mellett kell ellenőrizni;
az itt dokumentált SQLite tesztek nem ígérnek MySQL SLA-t.

## Hosted CI és draft PR

A workflow csak a **jelen integrációs branchre** kapott plusz push-triggert, hogy
az ellenőrzés a GitHub API aktuális hozzáférési korlátja mellett is elinduljon.
A main és a PR workflow működése megmarad; installlépést vagy biztonsági gate-et
nem változtattunk. A kötelező hosted eredményt külön, a tényleges run linkjével
ellenőrizzük, nem nevezzük a helyi zöldet GitHub-zöldnek. Az aktuális tesztág
futásai: https://github.com/bizsis/adatdusito/actions?query=branch%3Acodex%2Fcategory-03d-full-integration .
A `7d39f12` előző kombináció [43897116075](https://github.com/bizsis/adatdusito/actions/runs/43897116075)
futása mind a hat jobon sikeres lett (backend, browser, menu-export, frontend,
docker, ci-ok). Ez még nem a RELEASE-02-t tartalmazó változat bizonyítéka.
A végső átadás a kibővített kombináció konkrét futáslinkjét és megfigyelt állapotát adja meg.

A Tulajdonos létrehozta a [#37 draft PR-t](https://github.com/bizsis/adatdusito/pull/37),
main base-szel. A tesztág feltöltése ezt a PR-t frissíti. A GitHub API HTTP 403
hozzáférési korlátja miatt külön PR-kommentet vagy leírásfrissítést nem tudunk
közzétenni; az eredmények ebben a verziózott jelentésben szerepelnek.
A draft állapot és a zöld CI nem jelent main-merge engedélyt.
