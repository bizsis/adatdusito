# CATEGORY-02B – frontend és CATEGORY-02A integráció

Feladat: [#17](https://github.com/bizsis/adatdusito/issues/17). Ág:
`codex/category-02b-frontend`. Nincs main-merge vagy VPS-telepítés.

## Szerződés és függőség

A produkciós adapter a [PR #18](https://github.com/bizsis/adatdusito/pull/18)
`8c5db11c091668188ea4ddcd6e1195ea8cc29af2` commitjában publikált
`docs/design/CATEGORY-02A-API.md` és az ottani implementáció alapján készült.
Ez a frontend PR nem tartalmazza Claude backendváltoztatásait. A backend előtti
telepítésnél a régi, additív mezők nélküli terméklista továbbra is működik;
a besorolási nézet az új `status_counts` válaszmezővel kapcsol be, üres listánál is.

A [koordinációs döntés](https://github.com/bizsis/adatdusito/issues/17#issuecomment-6900517240)
szerint nincs új általános bulk/preview API ebben a körben. Claude `8c5db11`
kiegészítése már dokumentálja és megvalósítja a `GET /workspace/products?q=...`
név/SKU/EAN (GTIN) keresést; a frontend ezt aktiválja, 120 karakteres mezővel,
300 ms késleltetéssel és keresésváltáskor törölt kurzorral. A keresés szűrőkkel és
lapozással együtt szerveroldali, nincs kliensoldali teljesállomány-szűrés.
A kategóriatérképekhez sincs szöveges keresési
paraméter a jelenlegi szerződésben, ezért ott csak a lapozás aktív.

## Elkészült

- A meglévő `ProductData` bővítése, külön saját és belső kategóriával; pontosan
  két státusz: **Automatikusan besorolt / Ellenőrzést igényel**. A kézi eredet és
  zár külön metaadat. Nincs frontend besorolási algoritmus vagy kitalált százalék.
- Szerveroldali státusz-, belsőkategória- és eredetszűrés, kulcskészletes lapozás.
  A kliens nem tölti le az egész termékállományt. Az összesített darabszámokat a
  `status_counts` szolgáltatja; 50 000-nél nagyobb tárolt állomány megjeleníthető.
- Igény szerint kért termékrészlet, eredeti mezők és meg nem feleltetett
  forrásoszlopok (hiányzott-legutóbbi-fájlból jelzéssel), maximum három alternatíva,
  revízió, eredet, döntési indok, audit/előzmények. Donor csak technikai részlet.
- Belső kategóriák szerveres útvonalkeresése és 100-as oldalakban betöltése;
  kizárólag a backend jóváhagyott, besorolható elemei választhatók. Több donor
  esetén külön profilválasztó, az eredeti külső ID-k változatlanok.
- A termék írási gombja a részlet `capabilities.classify` mezőjét is figyelembe
  veszi. Meglévő session/CSRF/Origin kliens, szerveres RBAC minden mentésnél.
  Nincs új token- vagy jogosultságtár, és tenant-ID nincs a kérésekben.
- Kézi besorolás `PATCH .../classification`, `expected_revision`, `set/reset`.
  A reset szándékosan feloldja a kézi védelmet és szerveres újraértékelést kér.
  Mentés csak megerősítés után; HTTP 409 esetén nincs automatikus újrapróbálás,
  nincs sikert jelző felirat: új adatot és új előnézetet kell kérni.
- Saját kategóriatérképek lapozása, jóváhagyása/elutasítása/törlése. A jóváhagyás
  **mindig** az összes nem zárolt termékre érvényesül. Nincs hamis opcionális
  „örökítés” kapcsoló. A mentési válasz tényleges `products_changed` és
  `locked_skipped` számai megjelennek.
- **Helyi, korlátozott előnézet:** csak a kliens által ismert kategóriaváltást,
  változatlan saját adatokat és érintett termékszám felső becslését mutatja.
  Külön figyelmeztet, hogy ez nem szerveroldali dry run vagy a teljes állomány
  hiteles eredménye. A zárolt és konfliktusos darabszám előre ismeretlen; nem 0.
  A revíziót/jogosultságot véglegesen a mentés ellenőrzi. Nincs kitalált preview
  végpont vagy szervernek küldött kliensoldali megerősítési token.
- A központi `SystemSettings` új besorolási lapja a meglévő GET-et és a dokumentált
  PUT-ot használja; a 98% a backend 0,98 válaszából jön. 50–100% ↔ 0,5–1 skála,
  kezelési jog és szerveres friss újraazonosítás. A küszöb nem számol új státuszt
  a frontendben. Régi backendnél nincs nem működő beállításlap.
- Az `ImportWorkspace` a szerver `analysis.data_rows/run_product_limit` mezőit
  megjeleníti, ha rendelkezésre állnak. A futáskorlát nem tenantkvóta, nincs
  csendes terméklevágás. Nincs új uploader vagy importbackend.
- Cloud & Teal, magyar felület; asztali táblázat és mobilon címkézett kártyák.
  Munkaterületváltáskor állapot/kijelölés törlődik, késői válasz nem kerül át.

## Tudatosan nem aktív / külön fázis

- Tetszőleges termékhalmaz és összes szűrt találat tömeges írása: nincs API;
  produkcióban nincs aktív vezérlő. A kategóriatérkép szerveres újrabesorolása működik.
- Teljes termékállományra érvényes szerveroldali előnézet és paraméter-diff:
  későbbi backendfázis. Nem helyettesítjük kitalált kliensoldali eredménnyel.
- A saját paraméterprofil/helyettesítés jövőbeli műveleteit nem keverjük össze
  a most elérhető belső kategória és paraméterdonor kiválasztásával.

## Tesztek és reprodukálás

A `presentation.ts` belső frontend-port, nem wire DTO. A valódi HTTP típusok a
`category02Contract.ts`, adapterük a `category02Api.ts` fájlban találhatók.
A `frontend/tests/classification` külön, produkcióba nem fordított Vite-entry.
A tesztadapter URL-jei és szintetikus sikerválaszai nem kerülnek az éles bundle-be.

- `test_classification_presentation_browser.py`: 16 izolált UI-regresszió;
  két státusz, mobil/asztal, callback-szűrés, lapozás, előnézet, 409, csak olvasás,
  késői tenantválasz, callback nélküli írás tiltása, alternatívák, mock küszöb.
- `test_classification_contract_browser.py`: 8 böngészőteszt a publikált wire DTO-val;
  valódi produkciós adapter, exact PATCH/revízió/donor payload, 409, capability,
  helyi előnézet és térképválasz pontos darabszámai. Ez HTTP-mock, nem backendbizonyíték.
- `test_classification_api_integration_browser.py`: 2 reszponzív teszt **valódi
  FastAPI/SQLite API-val**; import, kézi mentés, donor 385, saját adatmegőrzés,
  kategóriatérkép-öröklődés, zár megmaradása újraimportkor, audit, valódi konkurens
  409 és központi küszöbmentés. A frontend ág önmagában ezeket kifejezetten skipeli,
  amíg PR #18 backendje nincs jelen; az elkülönített integrációs munkafában futnak.
  Nincs élő MySQL/VPS-teszt vagy százezres MySQL-terhelésmérés állítva.

```bash
cd frontend
npm ci
npm run lint
npm run test:lint
npm run build
npm audit --omit=dev --audit-level=high
cd ..
PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
PYTHONPATH=backend python -m pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py \
  scripts/tests/test_emag_menu_export.py
```

Izolált backend-integráció: külön detached worktree PR #18 commitján, abba csak
ennek az ágnak a frontend-, docs- és scripts/tests változásai másolva, majd build
és a fenti tesztek. Ez nem backend-merge ebbe az ágba vagy a mainbe.

Backend, migráció, függőséglock, `.env`, Docker Compose/external hálózat és
VPS-konfiguráció nem változik. A teszteket a meglévő CI fájlmintái felveszik.
Kiadás: PR #18 backendje és 0009 migrációja szükséges az új funkciókhoz; ehhez a
frontendhez nincs saját migráció. Visszaállítás: a frontend PR visszavonható, a
backend additív válasza a korábbi terméklista mezőit is megőrzi. A régi termékek
kereshetőségéhez a PR #18 saját `product_backfill` előkészítése szükséges; ezt a
frontend nem indítja el és nem helyettesíti. MySQL-terhelésmérés nem történt.

## Helyi ellenőrzési eredmények

- Frontendág backend/eszközteszt-csomag: **364 sikeres**.
- Teljes böngészős/eszközregresszió a keresés előtti állapoton: **66 sikeres,
  2 kihagyott** (a két valódi API-esethez még hiányzó backend); azóta a kibővített
  keresős adaptercsomag külön újrafuttatva.
- PR #18 `8c5db11` + frontend izolált backend/eszközteszt-csomag: **389 sikeres**.
- Teljes integrált böngészős/eszközregresszió `8c5db11` + frontend mellett:
  **70 sikeres, 0 kihagyott**, beleértve a valódi API-eseteket és az összes
  meglévő hitelesítési, munkaterület-, import-, kategória- és navigációs tesztet.
- Produkciós API-adapter HTTP-mock böngészőtesztek: **8 sikeres**.
- Valódi API-integráció `8c5db11`-gyel: **2 sikeres**, 390 és 1440 px;
  névkereséssel és a visszakapott szűrt termékek ellenőrzésével. A sima frontendágon a backendfüggőség miatt kifejezetten skip.
- ESLint, TypeScript és Vite build; lintszabályok **3 sikeres** tesztje.
- Backend és frontend Docker build sikeres; runtime `pip check` sikeres.
- `npm audit --audit-level=high`: **0 sérülékenység**, fejlesztői függőségekkel együtt.
- Két meglévő Starlette/httpx/AnyIO deprecation figyelmeztetés; nincs új runtimefüggőség.

A GitHub Actions állapotát a helyi eredmények nem helyettesítik; csak a ténylegesen
lefutott távoli futás tekinthető annak.

A fejlesztési ág feltöltve: `codex/category-02b-frontend`. A PR létrehozási kísérlet
`POST https://api.github.com/graphql: Forbidden` (HTTP 403) hibával blokkolt;
automatikus PR-létrehozás és távoli GitHub Actions-ellenőrzés nem történt.
[PR megnyitása](https://github.com/bizsis/adatdusito/pull/new/codex/category-02b-frontend).
A helyi eredmény nem állít távoli CI-sikert. Main-merge és VPS-telepítés nem történt.
