# CATEGORY-03B – valós paraméter-API-integráció

Feladat: [#24, végleges integrációs utasítás](https://github.com/bizsis/adatdusito/issues/24#issuecomment-6902773899).
Frontend: [PR #27](https://github.com/bizsis/adatdusito/pull/27), `codex/category-03b-frontend`,
base továbbra is #22 (`a780c65`). A működő backend és szerződés: **#26 / `c05746d`**,
`docs/design/CATEGORY-03A-API.md`. A korábbi `e330ee7` csak dokumentáció volt.

A produkciós felület most a valódi FastAPI-végpontokat használja. A közös
integrációs tesztág `codex/category-03b-api-integration`: a változatlan #26 backend
és a #27 frontend együtt, a main módosítása nélkül. A frontend PR nem tartalmaz
backend-, migrációs vagy függőségzár-módosítást.

## Produkciós működés

A meglévő `ProductData` termékrészlet „Termékparaméterek” kinyitható panelje
csak megnyitáskor tölti a paraméteradatokat. Így a besorolási munkafolyamat nem
indít mellékes paraméterkéréseket, és az eltérő műveletek hibái nem keverednek.
A bekötött `LiveParameters` az alkalmazás
közös session/CSRF/tenant API-kliensét kapja; nincs másik fetch/session-tár.
Az új `liveContract.ts` futásidőben ellenőrzi a felhasznált DTO-mezőket, a nullokat,
azonosítókat, állapotokat, számlálókat és lapméreteket. Az additív extra mezők
megengedettek, a hiányzó vagy hibás kötelező mező nem lesz hamis üres/sikeres adat.

| Funkció | Tényleges API a `/api/v1` prefix alatt |
|---|---|
| Szerveres termékáttekintés, keresés, állapot/donor/kötelező hiány szűrés, kurzor | GET `/workspace/parameter-diff` |
| Tárolt paraméterhelyek | GET `/workspace/products/{id}/parameters` |
| Szerver számított diffje | POST `/workspace/products/{id}/parameters/preview` |
| Revíziós újraszámítás és alkalmazás | POST `/workspace/products/{id}/parameters/apply` |
| Kézi érték, jelölt elfogadása, lock/unlock/reset | PATCH `/workspace/products/{id}/parameters/{slot_key}` |
| Ügyfél/globális aliasszabályok keresése, lapozása | GET `/workspace/parameter-aliases` |
| Kifejezett hatókörű alias létrehozása | POST `/workspace/parameter-aliases` |
| Verzióellenőrzött visszavonás | DELETE `/workspace/parameter-aliases/{id}?expected_version=…` |
| Hatókörös előnézeti/alkalmazási futás | POST `/workspace/parameter-runs` |
| Futásállapot és számlálók | GET `/workspace/product-jobs/{id}` |

Az áttekintés legfeljebb 25 terméket kér oldalanként. A termékrészlet egyetlen
termék teljes szerveres helylistáját kapja meg (a jelenlegi API ilyen), majd ezt
helyben szűri és 25 soronként jeleníti meg. Ez nem szerveres helylista-lapozás,
és nem tölti le a tenant teljes termékállományát vagy a milliós értéklistát.

A tárolt érték, a számított előnézet, a nyers beszállítói érték és az összes kapott
forrásjelölt megkülönböztethető. Mind a hét API-állapot külön marad:
`present`, `missing`, `conflict`, `invalid`, `review`, `source_only`, `detached`.
A konverziót a backend végzi; a frontend a visszakapott értéket és szabályt mutatja.
A forrás szerinti kötelezőség ismeretlen, ha azt az API nem közli; ez nem hamis
„opcionális” jelölés. A donor szerinti kötelezőség változatlanul látszik.

## Írások és donorvédelem

- Az alkalmazás valódi szerveres preview után **csak `expected_revision`-t** küld.
  A UI helyi handle-je kizárólag az aktuális komponens előnézetét azonosítja;
  nem szerveres token, nem snapshot és nem az apply bemenete.
- A preview/apply újraszámít; meglévő forrásértéket nem szerkeszt. Az indokmező
  a felhasználói megerősítés része: az apply API nem fogad ilyen mezőt, ezért
  ennek szerveres auditálását nem állítjuk. A PATCH/alias/profilválasztás indoka
  viszont az adott API tényleges bemenete.
- `pending_review` esetén csak saját forráshelyek készülhetnek, automatikus új
  `emag:` helyek nem. `choice_required` esetén külön, explicit profilválasztó
  használja a meglévő revíziós classification PATCH-et. Ez **nem donorjóváhagyás**.
- A kézi érték elkülönül a forrástól; zárolt hely új értékéhez explicit unlock
  szükséges. A reset külön, auditált újraszámítás. A jelöltelfogadást a backend
  ellenőrzi, nincs fuzzy egyezés vagy értékkitalálás a böngészőben.
- A kézi PATCH, alias és futásindítás helyi megerősítése feliratozva van:
  **nem szerveres dry-run**. Hibás/malformed sikeres HTTP-válasz sem mentési siker.
- 401 a közös kliens kijelentkezési útját használja; 403/404/409/422/503 külön
  valódi hibaválaszként marad meg. Írási hiba után friss adatlekérés szükséges,
  nincs automatikus újramentés. A jogok a közös Me/RBAC és a termékválasz
  capabilities mezői együtt; a backend minden kérést újra ellenőriz.
- Tenant- és globális alias külön jog és explicit hatókör. Létrehozás/visszavonás
  nem indít visszamenőleges termékalkalmazást.

## Valódi háttérfutások

Saját kategória, belső kategória, beszállító vagy az aktív munkaterület explicit
hatóköre választható. A preview futás nem ír paraméterhelyet, az apply önálló
újraszámítás, nem egy korábbi preview-snapshot alkalmazása. A UI az API által
adott `processed`, `limit`, `products_changed`, `products_not_ready`, slot- és
hibaszámlálókat mutatja; nem számít hamis százalékot a `processed/limit` arányból.

Egy futás maximum 50 000 termék, a teljes tárolt állomány ennél nagyobb lehet.
`completed` + `has_more` + `next_start_after_product_id` után a felhasználó
külön indítja a következő, változatlan hatókörű és módú futást. Nincs automatikus
láncolás, kliensoldali terméklista-batching vagy 2000-es paraméterkorlát.
A futásazonosító később is betölthető. A 2,5 másodperces polling API-hibára megáll;
a folytatás/frissítés explicit. Sikertelen/elakadt futásnál az API nem ad általános
resume endpointot: az erre kínált művelet egyértelműen **új futás az elejétől**,
nem folytatásnak álcázott indítás. Megszakítási végpont nincs bekötve.

## Konkrét API-eltérések Claude számára

Reprodukciók a `c05746d` backenddel, kizárólag izolált SQLite fixture-ben:

1. `test_real_parameters_preview_apply_conversion_manual_lock_reset`: a
   `unit_conversion.factor` ténylegesen `"1000"` szöveg, a szerződés példájában szám.
   A decoder szigorú pozitív decimális szöveget és számot is fogad, nem konvertál
   termékértéket. Kérjük a dokumentáció pontosítását.
2. `test_real_conflict_invalid_review_detached_and_candidate_resolution`: donorváltás
   után a `review` jelölt alakja `{source_key, header, raw}` is lehet; nem csak a
   dokumentált célparaméter-jelölt vagy `{source_key,value,unit}` alak. Ezt is
   szigorúan dekódoljuk, a nyers érték külön látszik. A backend forrásjelölt-listája
   nincs három elemre korlátozva; a UI sem feltételez ilyen szerződéses maximumot.
3. `test_real_locked_feed_refresh_preserves_old_and_current_raw`: kézi `2000 W`
   zárolás után új `2,3 kW` feed. A belső `details.pending_source` nem kerül a
   `slot_dto()` válaszába, noha a szerződés jelzi. A UI a meglévő GET termékrészlet
   `source_attributes` mezőjéből, kizárólag azonos explicit forráskulccsal mutatja
   a friss nyers értéket, az eredeti `2,1 kW` és a kézi érték mellett. Kérjük a
   `pending_source` szerializálásának és szerződésének egységesítését.
4. A slot nem közöl saját kötelezőséget, paramétertípust vagy kategóriaspecifikus
   megkötést. Ezeket nem gyártjuk le. Kötött értékű slotnál nincs stabil univerzális
   értéklista-kapcsolat az API-válaszban: szabad szöveges `set` itt tiltott,
   meglévő forrásjelölt elfogadása elérhető és szerveresen validált. Az általános
   értéklistaválasztóhoz explicit cél-link/értéklista-kapcsolat szükséges.

Ezeket a hiányokat a frontend kezeli vagy jelöli; backendkódot nem módosítottunk.
A státuszdokumentum pontos jelentésként átadható Claude-nak; nem állítjuk, hogy
külön chatben vagy GitHub-kommentben már elküldtük.

## Tudatosan nem aktivált funkciók

A korábbi prezentációs tesztharnessben marad, a produkcióban nincs bekötve:
általános bulk snapshot/token/apply, külön preparation approval, teljes
history-/audit- és hibalista-lapozás, univerzális allowed-values CRUD, általános
job-cancel/resume, AI, kredit, fizetés és képkeresés. A `prepared` csak tárolt hely
létezését jelenti, nem felhasználói jóváhagyást. A termékrészlet legfeljebb 50
legutóbbi eseményét használjuk; nem teljes auditot ígérünk.

## Ellenőrzés és korlátok

A `scripts/tests/test_parameter_api_browser.py` a produkciós bundle-t Chromiumban
nyitja meg, a kéréseket a valódi FastAPI TestClient és az izolált SQLite adatbázis
kezeli. A normál válaszok nem mockok. Öt külön, jelölt transport-hibateszt a valódi
válasz után rontja el a JSON-t; ezek DTO-hibatűrési tesztek, nem backend-bizonyítékok.
Az enqueue kizárólag a tesztben helyettesített; a tényleges `advance_parameters`
workerfüggvény fut, nem Celery/Redis infrastruktúrateszt.

A 50 002-es fixture ténylegesen ennyi adatbázisrekordot tartalmaz. A két valódi
preview workerfutás 50 000 + 2 terméket dolgoz fel; paraméterhelyet egyik sem ír.
Külön scoped apply teszt valódi helyeket készít, ismételve idempotens. Keresés,
25-ös szerveres terméklapozás, 390/1440 px, mind a hét állapot, kW→W és mm→cm,
kézi javítás/reset, zárolás és feedfrissítés, explicit donorválasztás,
aliasjogok, tenantizoláció, 401/403/404/409/422/503 és hibás DTO is tesztelt.

**Saját MySQL-teljesítménymérés nem készült.** A fenti adatmennyiségi és E2E
bizonyíték SQLite; a #26 MySQL-mérései Claude külön backend-bizonyítékai.
A frontend-only #27 CI-ben a 21 natív paraméterteszt explicit dependency-skip,
amíg #26 nincs a base-ben. A közös tesztágon mindegyiknek futnia kell.
A 32 korábbi paraméter-prezentációs teszt továbbra is mock UI-regresszió.

Végső helyi eredmények: **410 backend/eszköz**, **134 böngésző** (113 korábbi +
21 új natív), **14 menüexport**, **3 lintkonfigurációs teszt** sikeres. Node 22
lint/TypeScript/build, backend/frontend Docker és dependency resolver ellenőrzés
sikeres; npm audit 0 találat. A parancsok a PR-leírásban. A GitHub API/GraphQL ebben a
környezetben HTTP 403-at ad; az ág pusholható, de a PR szövegének szerkesztése
és a hosted CI API-lekérdezése korlátozott. A ténylegesen megfigyelt állapotot
külön jelezzük, nem azonosítjuk a helyi ellenőrzéssel.

## Integráció, kiadás

A frontend #26-tal együtt használható; régi backend 404 esetén a termékrészlet
jelzi a hiányzó paraméter-API-t. A kiadásról és a base retargetről a tulajdonos
vagy a Vezér dönt. Ez a PR nem futtat migrációt; #26 saját `0010` migrációja az
ott leírt backendfüggőség. Nincs main-merge, VPS-művelet, .env/Compose-módosítás,
pinfo_db-írás vagy kategóriahierarchia-változás. Visszaállítás a frontend commit
visszavonása; a paraméteradatok szerveroldalon megmaradnak.
