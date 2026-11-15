# CATEGORY-01B — a jelenlegi UI és API tételes felmérése

**Állapot:** kód alapján ellenőrzött felmérés, nem új funkciólista.
**Alap:** `main` — `80b0dce5b5270eb5de1ccecbfef5427ce35aa2c3`, FRONTEND-02 és SECURITY-02 után.
**Feladat:** [#13](https://github.com/bizsis/adatdusito/issues/13).
**Kapcsolódó javaslat:** [képernyő-, API- és tesztterv](CATEGORY-01B-UX.md).

Az ellenőrzés tárgya a repo és a helyben épített alkalmazás szintetikus adatokkal
futó regressziós tesztjei. A VPS aktuális adatait, katalógusverzióját, darabszámait
és válaszidejét nem mértük; a merged kód nem bizonyítja a telepített állapotot.

## 1. Képernyők és komponensek

| Meglévő elem | Tényleges képesség | Korlát / újrahasznosítás |
| --- | --- | --- |
| [`main.tsx`: `App`](../../frontend/src/main.tsx#L1620) | Munkaterület-választó/kereső, effektív jogosultságok szerinti menü, session-frissítés, CSRF, kijelentkezés. A fő tartalom tenant/jogosultság/erőforrás változásakor új kulcsot kap. | Megtartandó. A termékfolyamat tenant-környezetben működjön, ne rendszerszinten. Új auth nem szükséges. |
| [`ImportWorkspace`](../../frontend/src/ImportWorkspace.tsx#L52) | Beszállító, CSV/XLSX feltöltés, mentett importprofil; lap/fejléc/kódolás/elválasztó; oszlopjavaslat, kézi megfeleltetés, eredeti és értelmezett előnézet; kulcs/pénzügyi jóváhagyás; futáselőzmény és feldolgozásfigyelés. | Ez marad az import belépési pontja. Nem ismeri fel önálló modellként az ügyfél kategóriafáját vagy paraméterdefinícióit. |
| Importprofil-választó | Verziózott beszállítói oszlopmegfeleltetést és beállításokat használ. Az engine engedélyezett, eltérésmentes profilnál automatikusan feldolgozhat. | Az importprofil **nem** kategória-paraméterprofil. Ne nevezzük át vagy használjuk a kettő azonosítására. |
| Importelőnézet | Eredeti oszlopok/minták, nem használt oszlopok, normalizálási problémák, előnézeti lapozás; a megfeleltetés előnézete nem ír terméket. | Megtartandó. Több saját paraméteroszlop strukturált bekötése új képesség; a jelenlegi belső mezőtérkép egy célmezőhöz egy forrásoszlopot enged. |
| [`ProductData`](../../frontend/src/ProductData.tsx#L10) | Tenant terméklista, cikkszám/név/gyártó/beszállító; 25 termékes kurzoros lapozás; egy termék mezői és forrássora megnyitható. | Ez bővítendő. Nincs kategóriaoszlop, státusz, termékkereső, paraméter-diff, kategóriaszerkesztés, kijelölés vagy tömeges művelet. A részlet jelenleg a már letöltött sorból nyílik. |
| [`Categories`, `ShopNode`, `ShopDetails`](../../frontend/src/main.tsx#L634) | Közös fix fa, 13 főcsoport; lusta gyermekbetöltés, keresés, útvonal, kategóriarészlet, profilok, megengedett értékek. | A donorválasztóhoz újrahasznosítható. Jelenleg referencia-kategóriát böngész, nem terméket kategorizál. A globális `CategoryReview` nem termékszintű javítóűrlap. |
| [`Parameters`, `ValueBrowser`](../../frontend/src/main.tsx#L443) | Paraméternév/azonosító keresés, kötelezőség, profil; értékkeresés és kurzoros értéklapozás; típus és újérték-szabály látható. | Beágyazható a donor részleteibe. Nincs saját termékérték–referenciamező összehasonlítás vagy termékmező mentés. |
| [`CategoryReview`](../../frontend/src/main.tsx#L722) | Adminisztrátori közös kategória–paraméterforrás hozzárendelés; kézi forrásválasztás és visszaállítás. | Központi művelet, minden ügyfelet érinthet. Nem szabad vele egyetlen ügyfél termékének donorát javítani. A UI `system.manage`, a backend `reference.manage` jogot ellenőriz; ez meglévő különbség, itt nem változik. |
| [`ExportAdmin`](../../frontend/src/ImportWorkspace.tsx#L860) | Webáruházmotor meződefiníciói, referencia-XLSX-ből javaslatok, ügyfél exportprofilja. | Megőrzendő; nem kategória-paraméterprofil, nem kész termékexport vagy UNAS API-integráció. |
| [`ui.tsx`](../../frontend/src/ui.tsx) | `Panel`, `Help`, `FieldTitle`, `IconButton`, jogosultságtáblák, időzóna szerinti időformátum. | Új képernyők ezekkel készüljenek. `main.tsx`-ben lévő `Modal`, `Pager`, `ErrorBox`, `useLoad`, `useDebounce` még nem általánosan exportált komponensek; későbbi kisméretű kiemelésük tervezhető. |
| [`AccessWorkspace`](../../frontend/src/AccessWorkspace.tsx), Audit menü | Műveleti jogok, explicit tiltások és scope; auditmegtekintés. | Új szereprendszer helyett bővítendő. Meglévő auditesemények nem helyettesítik az új termékszintű kézi döntések eredetét/revízióját. |

## 2. Meglévő API-k — nem jövőbeli végpontok

Minden alábbi útvonal az `/api/v1` előtaghoz tartozik. A táblázat célzott
felmérés; a pontos mezősémát a router/Pydantic definíció és a hitelesített
OpenAPI adja, nem ez a dokumentum.

| API | Jog és jelenlegi forma | UI / korlát |
| --- | --- | --- |
| `GET /auth/me`, `POST /auth/tenant` | Meglévő session és CSRF; effektív jogok, tenant- és erőforráskör. | Munkaterületcsere marad a jelenlegi művelet. Nincs új tenant-bejelentkezés. |
| `GET /imports/fields` | `imports.read`; belső `key,label` lista. | Többek között `category` = „Beszállítói kategória”, `attributes` = „Műszaki attribútum”. Nem paraméterdefiníció-séma. |
| `GET /imports/suppliers`; `POST /imports/suppliers` | Olvasás: `imports.read`; létrehozás: `imports.manage`. | A beszállítólista jelenleg nem lapozott. Nagy beszállítóállománynál külön keresési bővítés kellhet. |
| `GET /imports/profiles?supplier_id=…` | `imports.read`; profil, verzió, config, jóváhagyó, utolsó sikeres feldolgozás. | Beszállítói importprofil, nem donorprofil; lista jelenleg nem lapozott. |
| `POST /imports/runs` | `imports.create`; multipart: fájl, beszállító, opcionális profil és parserbeállítás. CSV/XLSX; alapértelmezett korlát 50 000 000 bájt. | Feltöltés és háttérelemzés. A HTML 413-ra már van magyar hibakezelés; nem kell új uploader. |
| `GET /imports/runs?offset=…`; `GET /imports/runs/{id}` | `imports.read`; előzmény legfeljebb 25 elem; futás állapota/config/analysis/counters. | Az aktív futást a UI 2 másodpercenként frissíti. Ez importállapot, nem termékbesorolási státusz. |
| `GET /imports/runs/{id}/rows` | `imports.read`; `offset`, `limit` alap 25, maximum 100; `items,total,offset,limit`. | Tartós eredeti/értelmezett importsorok, hibák. Nem kész termékparaméter-diff. |
| `GET /imports/runs/{id}/source-preview`; `POST /imports/runs/{id}/preview` | `imports.read`; az utóbbi `mapping,offset` alapján 25 forrássort értelmez, írás nélkül. | Megfeleltetés előnézete. Nagy offsethez a forrás bejárása történhet; nem általános 10 000 soros interaktív grid API. |
| `PUT /imports/runs/{id}/settings` | `imports.manage`; parser javítása meghatározott, még jóvá nem hagyott állapotokban. | Megmarad, nem kategóriakonfiguráció mentése. |
| `POST /imports/runs/{id}/approve` | `imports.approve`; név, mezőtérkép, kulcs, feed és jóváhagyott pénzügyi beállítások; profilverziót készít, feldolgozást indít. | Nem jelent kategória-, paraméterkiegészítés- vagy AI-jóváhagyást. Pénzügyi mezők meglévő kifejezett jóváhagyását nem szabad megkerülni. |
| `GET /imports/runs/{id}/join-suggestions` | `imports.read`; minták pontos egyezése legfeljebb 100 meglévő beszállítói termékkel, `requires_approval`. | Termékazonosítási kulcsjavaslat; nem teljes katalógus-egyeztetés vagy szemantikus kategóriabesorolás. |
| `POST /imports/runs/{id}/actions/{action}` | `cancel`: `imports.cancel`; többi támogatott művelet: `imports.manage`; állapotellenőrzéssel. | Szünet, folytatás, elemzés, megszakítás, hibás sorok újrapróbálása. Nem szabad donor-egyeztetésre új jelentést adni nekik. |
| `GET /imports/runs/{id}/file`, `/errors.csv` | `imports.read`, tenant-ellenőrzés. | Forrás és hibajegyzék; a megőrzési idő lejárata kezelendő. |
| `GET /workspace/products?cursor=…` | `products.read`; `items,next_cursor,field_labels`; szerver 26-ot kér, legfeljebb 25-öt ad vissza. | Jelenlegi `ProductData` forrása. Nincs `q`, kategória/státusz szűrés, rendezésválasztás vagy összesített darabszám. |
| `GET /imports/products?supplier_id=…&offset=…` | `products.read`; fix 25 beszállítói termék. | Meglévő alternatív lista, nem indok második termékkezelő képernyőre. |
| `GET /imports/products/{id}/changes?offset=…` | `products.read`; legfeljebb 25 `run_id,line,delta`. | Importváltozások meglévő alapja. Nincs benne önálló kézi kategória-/paraméterdöntés. |
| `GET /reference/navigation` | `reference.read`; `parent_id,q,scope,offset,limit`, legfeljebb 100 elem. | Közös kategóriakereső és igény szerinti gyermeklista; a fa szerkezetét az import nem módosíthatja. |
| `GET /reference/navigation/{node_id}`; `…/selection` | `reference.read`; részlet, kiválaszthatóság, katalógus-/forrásazonosítók, profiligény; a selection olvasás, nem termékmentés. | Donorválasztás ellenőrzéséhez újrahasznosítható. A selection régi fallback és aktív saját katalógus esetén eltérő azonosítókat adhat. |
| `GET /reference/navigation/{node_id}/parameters` | `reference.read`; `profile_emag_id,q,mandatory,offset,limit`; kötelezőségi és kategóriamegkötési annotációk. | Profilonként használható; szülőparaméter-öröklést nem szabad feltételezni. |
| `GET /reference/parameters/{id}/values` | `reference.read`; `q,after,view,limit`; alap 50, maximum 100; `has_more,next_cursor`. | Milliós értékállományt nem tölt egyszerre. Új termékértéket nem ment. |
| `POST /reference/navigation/{node_id}/assignment` | `reference.manage`; közös kategória hozzárendelése/reset. | Nem normál termékkezelési API; a leendő termékdonor-mentés nem hívhatja. |

Források: [`import_api.py`](../../backend/app/import_api.py),
[`workspace_views.py`](../../backend/app/workspace_views.py),
[`web_navigation.py`](../../backend/app/web_navigation.py),
[`reference.py`](../../backend/app/reference.py),
[`security.py`](../../backend/app/security.py).

## 3. Mit őriz meg ma az import, és mit nem szabad már késznek tekinteni?

- A [`FIELDS`](../../backend/app/import_parser.py#L12) által ismert `category`
  szöveg megfeleltethető, és a termék `data` JSON-jába kerülhet. Ez nem idegen
  kulcs saját kategóriatáblához, nem az eMAG donorazonosítója és nem garantált fa.
- `ImportChunk` megőrzi a fájlbájtokat a forrásmegőrzési szabályokig;
  `ImportRow.raw` az eredeti sort, a normalizálási metaadat a forráshelyet.
  A [`row_envelope`](../../backend/app/import_api.py#L50) az ismeretlen oszlopokat
  `unmapped_attributes` listaként is visszaadja. Megőrzés van, általános strukturált
  sajátparaméter-import nincs. A forrásfájlhoz később nem mindig lehet visszatérni.
- A jelenlegi `Approval.mapping` ugyanahhoz a belső mezőhöz nem enged több
  oszlopot. A „Szín”, „Teljesítmény”, „Kapacitás” három külön paraméterének
  támogatása nem oldható meg három `attributes` mezőbekötéssel.
- [`SupplierProduct`](../../backend/app/import_models.py#L71) tenant/beszállító/
  `identity_key` szerint egyedi, mezői JSON-ban vannak. Nincs benne önálló
  termékkategória-donor kapcsolat, paraméterhelymodell, kézi zárolás, revízió
  vagy a kért két besorolási státusz.
- Az engine [`advance`](../../backend/app/import_engine.py) pontos jóváhagyott
  kulccsal kapcsol; kulcs hiányában futás/sor szerinti külön tétel marad.
  Azonos névből nem szabad azonosságot vagy importokon átívelő védelmet ígérni.
- Az engine a részleges feed nem hiányzó, megfeleltetett mezőit a korábbi adatokra
  ráírja (`product.data = {**previous, **values}`), és `ImportChange.delta`-t ment.
  Ez **nem kézi javításvédelem**. Az új kézi értékeket külön eredettel/zárolással
  kell majd megőrizni; ennek backendmodelljét CATEGORY-01A tervezi.
- A közös katalógus és donorprofilok verziózottak, az eredeti `pinfo_db` csak
  olvasható. Saját kategória importja nem alakíthatja át a fix 13-as közös fát,
  és az `is_allowed` nem írhatja felül a jóváhagyott fa láthatóságát.

## 4. Jogosultsági és biztonsági következmények

Az [`access_control.py`](../../backend/app/access_control.py) jelenlegi katalógusában
van `products.read`, `imports.read/create/approve/manage/cancel`, `reference.read/manage`;
nincs termékkategória- vagy termékparaméter-szerkesztési/tömeges jóváhagyási jog.
Ezek bővítési javaslatok lehetnek, automatikus kiosztásuk nem része ennek a tervnek.

A [`security.require`](../../backend/app/security.py#L545) és az
[`import_api.tenant`](../../backend/app/import_api.py#L32) szerint a régi import- és
termékrekordokhoz teljes ügyfél-erőforráskör kell. Kijelölt cég/bolt jogból nem
következik hozzáférés erőforráshoz még nem kapcsolt termékekhez. Ezt a UX nem oldhatja
fel. Lásd [ADR-001](../decisions/ADR-001-tenant-and-access-boundaries.md).

Meglévő audit-alap: [`audit_events`](../../backend/app/models.py#L97) és
[`audit()`](../../backend/app/security.py#L573). Új termékszintű döntéseknél ezekhez
kell majd tenantot, aktort, célrekordot, revíziót és visszakereshető döntésrészletet
kapcsolni; a forrásfájlok és értékek másolása a naplóba nem indokolt.

## 5. Továbbhasználandó ellenőrzések

- [`test_supplier_import.py`](../../backend/tests/test_supplier_import.py):
  eredeti/normalizált adatok, ismétlésbiztonság, profil és drift, pontos kulcs,
  tenant-izoláció, korlátok, lapozott előnézet.
- [`test_import_browser.py`](../../backend/tests/test_import_browser.py):
  asztali/mobil feltöltés, jóváhagyás és exportmező-felület.
- [`test_frontend_hooks_browser.py`](../../scripts/tests/test_frontend_hooks_browser.py):
  ügyfélváltás, CSRF/session, 413, importűrlap és késői válaszok elleni védelem.
- [`test_access_control.py`](../../backend/tests/test_access_control.py) és
  [`test_restricted_session_gate.py`](../../backend/tests/test_restricted_session_gate.py):
  effektív tiltások, scope, megszorított session; a tervezett új végpontokra is kellenek.
- Kategória- és paraméterregressziók: `test_fixed_category_catalog.py`,
  `test_web_navigation.py`, `test_unified_browser.py`; a fix hierarchia és az
  értéklisták megőrzendők.

Ezek a jelenlegi működést ellenőrzik. A [UX-terv tesztmátrixa](CATEGORY-01B-UX.md#10-elfogadási-és-frontend-tesztterv)
az új funkciókra még megírandó teszteket sorolja fel.
