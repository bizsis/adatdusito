# CATEGORY-03B – paraméter-diff UI, első kör

Feladat: [#24](https://github.com/bizsis/adatdusito/issues/24).
Ág: `codex/category-03b-frontend`, kiindulás a [#22](https://github.com/bizsis/adatdusito/pull/22)
`a780c65` integrációs ágából. A #22 runtime DTO-, retry-, 409-, donor- és
adatmegőrzési javításai megmaradnak. Main: `80b0dce`, nincs automatikus merge/deploy.

**Állapot: szerződésfüggetlen frontend és tesztmockok; a megjelent végleges
szerződéshez igazított állapotnevekkel. Nem elkészült CATEGORY-03A API-integráció.**
Munka közben megjelent a `claude/category-03a-parameters` ág `e330ee7` commitjában
a `docs/design/CATEGORY-03A-API.md` végleges útvonal-/mezőszerződés. A commit csak
dokumentáció; a paraméterhelyek endpointjai, 0010 migrációja és implementációja
még nincsenek benne. A szerződés maga is kimondja: csak a PR „Implementált
végpontok” listája tekinthető késznek. Ezért az új éles API-hívásokat nem aktiválom.
A 02A alap `e946b93`; a #22-ből örökölt kódhoz ebben a frontendkörben nem adtam
párhuzamos backendimplementációt.

A korábbi CATEGORY-01B S3–S7 terv UX-forrás, az ottani API-munkanevekből nem
készült kérés. A végleges szerződés és a későbbi üzleti pontosítások az elsődlegesek.

## Elkészült komponensek

- `ParameterWorkspace`: magyar, reszponzív diff; `present`, `missing`, `conflict`,
  `invalid` külön felirattal; a publikált `review`, `source_only`, `detached`
  állapotok is külön maradnak, nem nevezzük őket tévesen konfliktusnak vagy hibának. Nyers saját érték/egység/forrás és a kapott normalizált
  érték/konverziós indok egymás mellett. Saját és donor szerinti kötelezőség külön.
  Nincs frontend-egységkonverzió, névalapú összevonás vagy aliasfelismerés.
- Biztos egyezés külön jelölve, szükségtelen kézi jóváhagyás nélkül. Bizonytalan
  alias külön előnézhető; egyezés nélkül a saját/donor sorok megmaradnak. A hiányzó
  hely és a meglévő, de üres érték külön fogalom. Kategóriamegkötés látható, nem
  írja felül csendben a saját értéket.
- Több donorprofil és kézi profil-felülvizsgálat. Profilváltás csak előnézet és
  visszaigazolt alkalmazás után; a nyers saját adat megmarad. `pending_review`
  donor mellett nincs automatikus hely-előkészítés vagy előkészítési jóváhagyás.
  Nincs paraméterérték-automatikus kitöltő művelet vagy AI-kérés.
- `ParameterValues`: részleges, kereshető/lapozható értéklista. A szolgáltató által
  jelzett „nincs lista”, a keresésben nincs találat és a betöltési hiba külön állapot.
  Egy olvasás maximum 100 prezentációs értéket kezel; nincs milliós értékletöltés.
- Kézi javítás külön korrekciós értékként, eredeti nyers érték és audit mellett;
  védett sor nem szerkeszthető. Feloldás külön joggal, indokkal és előnézettel.
  Sorváltás/részletbezárás/szűrés/lapozás nem dobja el kérdés nélkül a kézi draftot.
- `ParameterAction`: indok → előnézet → alkalmazás. A `local` becslés megtekinthető,
  de nem alkalmazható szerveres próbafuttatásként. Visszakapott server-preview és
  tényleges apply callback nélkül nincs mentés. Forrásérték-felülírást jelző
  előnézet blokkolt; nincs automatikus mentés vagy 409-re vak újrapróbálás.
- Opcionális, szerver által rögzített termékkör és opaque handle. A tömeges vezérlő
  csak snapshot/preview/apply callbackekkel és jogosultsággal jelenik meg. Nincs
  összes termék/ID letöltés, helyi batching vagy kliensoldali sémaszámítás.
- `ParameterJobPanel`: kapott jobállapot, részleges siker, ismert vagy ismeretlen
  százalék, feldolgozott/módosított/kihagyott/hibás számlálók; jogosult folytatás és
  megszakítás. A százalékot nem számolja a UI a számlálókból. API-hiba leállítja a
  pollingot, a legutóbbi állapot hibajelzéssel látható. Olvasási oldalon frissíthető.
- A feldolgozási futás 50 000-es maximuma külön szerepel a nagyobb teljes
  termékállománytól. A UI a kapott többfutásos tervet mutatja, nem gyárt ilyet.
  50 000 fölötti egyedi tervezett futás nem alkalmazható.
- Előkészítési jóváhagyás külön revíziós állapot. A hiányzó érték önmagában nem
  tiltja: a szolgáltató `canApprove` döntése és donoralkalmazhatóság számít.
  Nincs AI-indító gomb, kredit-/árígéret, fizetés vagy képkeresés.

## Kapcsolódás a meglévő felülethez

A `ClassificationPresentation.parameterPreparation` opcionális szolgáltatással
ugyanazon `ProductData` termékrészletben jeleníthető meg a nézet. Az
`ImportWorkspace.parameterJob` opcionális slot ugyanazt a futáskártyát használja.
A normál produkciós API-adapter ezeket **nem adja át**: amíg nincs 03A szerződés,
a valódi felületen nincs működőnek látszó új paraméterművelet vagy mock adat.
Az új munkaterület lazy chunk, a normál import és besorolás működése megmarad.

A `frontend/src/parameters/presentation.ts` nevei **csak frontend propsok és
callbackek**, nem javasolt HTTP DTO-k, API-műveletnevek vagy jogosultságkódok.
Nincs itt `fetch`, endpoint, session-/CSRF-tár vagy sikeres alapértelmezett mentés.
A későbbi adapter a publikált 03A szerződést a meglévő közös API-klienssel kell
hogy illessze, a tenant/scope/CSRF/RBAC és revíziók szerveres ellenőrzése mellett.

Munkaterület/termék váltása újramountolja a nézetet; az oldalkurzor, kiválasztás,
régi előnézet, job és draft nem kerül át másik termékhez. A késői olvasás akkor
is eldobódik, ha az adapter nem támogatja a transport abortot. A teljes appból
kilépésre/tenantváltásra vonatkozó globális draftvédelmet a végleges integrációkor
kell összehangolni a meglévő workspace-kezeléssel; nem akadályozunk szerveroldali
munkamenet- vagy tenantváltást egy elavult helyi űrlappal.

## Tesztmockok határa

A `frontend/tests/parameters` külön Vite-entry. A `/__category03b_test__/...`
szintetikus útvonalak kizárólag a tesztharnessben élnek, nem végpontjavaslatok.
A mockolt preview `server` jelzője egy tesztelt UI-ágat jelöl; **nem bizonyít
valódi szerveroldali diffet, auditot, snapshotot, normalizálást vagy jobfuttatást**.
A mockos 401/403/404/409/422 az error UI működését teszteli, nem a még el nem
készült 03A API RBAC-ját vagy sessionkezelését.

A képernyőképek 390 és 1440 px-en készülnek a mock felületről. A teszt-entry és
transport nincs a produkciós bundle-ben vagy a Docker build inputban.
A mock mutat 125 000 összes tárolt terméket, csak lapnyi paramétert és három
külön 50 000/50 000/25 000-es tervezett futást. Ez nem MySQL-terhelésteszt és
nem egy tényleges 125 000-es paraméterjob végrehajtása.

## API-integrációra váró, pontos adatigény

Az alábbi lista adatjelentést ír le, **nem végpont-/mezőnévjavaslat**.

| Terület | A végleges szerződésből szükséges adat/garancia |
| --- | --- |
| Termék és érvényesség | Stabil termékazonosító, saját kategória, belső kategória teljes útvonala; termék-, forrásimport-, kategóriatérkép-, profil-, séma- és katalógusrevízió; diff érvényessége. Tenant mindig sessionből, nem szabadon küldött ügyfél-ID-ből. |
| Jogok | Műveletenkénti read/edit/alias-approval/donor-choice/preparation-approval/unlock/bulk/job-resume/cancel capability; erőforrásscope. A gomb elrejtése nem helyettesít szerveres jogellenőrzést. |
| Saját paraméter | Stabil saját kulcs, eredeti címke, eredeti nyers érték (null/üres/0 külön), eredeti egység; meg nem feleltetett mezők is; beszállító/fájl/futás/sor/oszlop, legutóbbi importban jelen volt-e. |
| Normalizálás | Normalizált érték és egység külön; szabály, verzió, indok és igazolt dimenzióhelyesség. A UI nem végez átváltást vagy összemérést puszta címkeegyezésből. |
| Donorprofil és audit | Stabil forrás-/profilazonosítók, név/útvonal/verzió, több profil; donor auditállapot (`pending_review` is), alkalmazhatóság és konkrét tiltási indok. A #20 audit döntését a UI nem találja ki. |
| Donorparaméter | Stabil paraméterazonosító, típus, név, egység, saját/donor szerinti kötelezőség külön; kategóriamegkötés. Meglévő eredeti paraméterértékekhez való stabil kapcsolat. |
| Diff és egyezés | Lapozható/kereshető sorok, present/missing/conflict/invalid jelleg; biztos/bizonytalan/nincs egyezés, aliasjelölt és jelentés/egység/profil alapján számított indok. Semelyik oldal adatát nem lehet név alapján elveszíteni. |
| Megengedett értékek | Stabil paraméter+profil+verzió kontextus; keresés és lapozás; lista tényleges hiánya vs üres találat vs olvasási hiba; legfeljebb lapnyi adat. |
| Kézi döntés és zár | Korrekció külön az eredeti forrástól, hatóköre és revíziója; védett rekordok; auditált, indokolt feloldás. Import/profilváltás ne írjon felül védett saját értéket. |
| Változástörténet | Előtte/utána, ki/mikor/miért, régi és új revízió, import/batch hivatkozás. Rövid első oldal és végleges, lapozott előzményolvasás; ne teljes napló kerüljön a listaválaszba. |
| Snapshot és előnézet | Szerver által rögzített termékkör, szűrőleírás és opaque azonosító; termékenként/sémánként csoportosított hiteles diff. Token/érvényesség/revízió, alkalmazható/megmaradó/új üres hely/védett/ütköző/blokkolt/felülírandó számlálók pontos mértékegységgel. Forrásfelülírás 0. |
| Preview/apply | Publikált, megvalósított műveletek; kötelező revízió és snapshot, 409/lejárat, ismétlésbiztosság és bizonytalan mentési eredmény visszaolvasása. Részleges siker esetén pontos eligible/skip/conflict szabály. Kliensbecslés nem szerveres dry-run. |
| Nagy állomány és job | Feldolgozási futásonként ≤50 000, nagyobb teljes állomány és több futás támogatása; stabil jobazonosító, célhalmaz, revízió, állapot, kapott százalék vagy ismeretlen állapot, számlálók és bounded/lapozott hibák. Jogosult folytatás/megszakítás/ismétlésbiztosság; kliens nem tölt le minden termék-ID-t. |
| Előkészítési jóváhagyás | Jóváhagyott revízió/scope, indokolt blokk és érvénytelenedés. Hiányzó kutatandó érték elfogadható; megoldatlan jelentés/egység/identitás/donoralkalmazhatóság blokkol. Ez nem importjóváhagyás vagy igazolt teljes adatlap. |
| Hibák és védelem | A közös magyar error envelope, valódi 401 session expiry, 403/404 scope, 409 stale és 422 validáció; Origin/CSRF/no-store; hibás vagy elutasított válaszra nincs üres siker vagy automatikus újramentés. |

## Valódi backenddel később kötelező

A publikált szerződés endpointjainak implementációja után adapter + valódi FastAPI/SQLite Chromium
integráció szükséges. Az új 03A végpontokon ellenőrizendő: confirmed/ambiguous/
no-match, több donor és audittiltás, egységkonverzió és nyers értékmegőrzés,
protect/reset/audit, 401/403/404/409/422, 409 utáni összehasonlítás és friss diff,
lejáró snapshot, gyors szűrés/tenantváltás, 50 000-es futás és nagyobb teljes
állomány, részleges batch/job és folytatás, valamint előkészítési jóváhagyás
érvényessége. **Ezek a 03A API-n jelenleg nem ellenőrzöttek.** A #22 régi valódi
API-tesztjei ettől külön regressziós ellenőrzések, nem a 03-as integráció pótlékai.

Nincs backend-, migráció-, `.env`-, dependency-lock-, Compose-, referenciaadat-
vagy VPS-módosítás. A 457 besorolható kategóriához és a 13 főcsoporthoz nem nyúlunk.
A PR a #22 ágára épülő frontend PR; a függőség mainbe kerüléséről és az átadásról
a Tulajdonos dönt, nincs automatikus retarget/merge/deploy.

## A megjelent 03A szerződéshez tartozó integrációs különbségek

- A dokumentált termékparaméter GET teljes `slots` listát ad, míg a prezentáció
  oldalas és szűrhető. A végleges implementációban ellenőrizni kell a slotlista
  tényleges felső korlátját/pagingját; a UI nem hív kitalált query-paramétert.
- A szerződés állapotai bővebbek a kezdeti négy diff-jellegnél. Mind a hét állapot
  külön megjeleníthető/szűrhető; a `review` nem egyenlő `conflict`-tal.
- A termék-preview valódi számítást és változáslistát ígér, apply termékrevízióval.
  A kézi slot PATCH-hez viszont nincs külön általános szerveres változáselőnézet.
  A jövőbeli adapternek ezt külön kell jelölnie; helyi becslést nem címkézhet servernek.
- A `parameter-runs` hatókör és kurzor alapján fut; nem dokumentál szerveroldali
  kiválasztási snapshotot vagy preview-tokenhez kötött batch apply-t. A #24 csak
  ilyen garanciákkal engedi a tömeges jóváhagyást, ezért a prototípus bulk callbackje
  nem köthető rá úgy, mintha ezek a garanciák meglennének.
- A job DTO nem ad egyértelmű százalékos készültséget vagy teljes termékszámot;
  a `processed/limit` arány nem feltétlen készültségi százalék. Ilyenkor ismeretlen
  százalékot kell megjeleníteni. `has_more/next_start_after_product_id` új futást
  jelöl, nem automatikusan ugyanazon futás folytatását. Állapot- és művelettérképezés
  csak a tényleges implementáció alapján készülhet.
- Nincs külön előkészítési jóváhagyás végpont/DTO a szerződésben. `prepared` azt
  jelenti, hogy van tárolt hely; nem jelent felhasználói jóváhagyást. A prototípus
  jóváhagyási művelete nem aktiválható pusztán ettől.
- A kötött értékkészlethez a kézi PATCH `value_id`-t kér. A végleges adapter/UI
  értékválasztóhoz stabil érték-ID, profil/katalóguskontextus és valódi értéklista-
  API szükséges; a jelenlegi mock stringje nem tekinthető menthető referenciának.
- A donorállapotokat (`ready`, `choice_required`, `pending_review`, `none`),
  alias/verzió/visszavonás, több forrás és jelölt megőrzése, kézi accept/lock/unlock/
  reset, valamint a jobok végső állapotai az implementációból térképezendők.
  Nem vezetünk be e célból saját alias-/normalizáló- vagy donor-audit rendszert.

E pontok egyeztetendő szerződés/implementációs feltételek, nem engedély nélküli
backendmódosítások. A már létező végleges útvonalakból sem készül működőnek
állított adapter addig, amíg a végpontokat Claude ténylegesen nem implementálta.

A publikált 03A DTO nem ad teljes tenant-termékszámot. Ezért a prezentációs
összesítés nullable: ismeretlen esetben nincs kitalált 0 vagy 50 000-es kvóta.
Egy szűrt lista számlálója nem nevezhető át teljes adatbázis-méretnek.
Az alias-felülvizsgálat prototípusbeli terméksor-döntés; tenant-/globális
alias létrehozásához a végleges művelet hatókörét és jogát külön kell tisztázni.
Termékdöntésből nem következhet rejtett, minden ügyfélre érvényes szabály.
