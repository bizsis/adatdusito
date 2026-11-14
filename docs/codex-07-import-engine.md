# CODEX 07 – Beszállítói importmotor

## Felhasználói folyamat

Válassz ügyfél-munkaterületet, majd a **Beszállítói import** menüt. Válassz vagy hozz létre beszállítót és tölts fel CSV/XLSX fájlt. A háttérfeladat felismeri a fejlécet és javaslatot ad az oszlopok jelentésére. Az előnézet lapozható, az eredeti és az értelmezett értékek egymás mellett láthatók. Az ismeretlen oszlopokat a lenyitható részben rendelheted mezőhöz; az eredeti adat akkor is megmarad, ha nincs megfeleltetés.

A pénzügyi értelmezést külön jelölőnégyzettel kell jóváhagyni. A LISTPRICE és LASTINITIALCOST csak általános árjavaslat: egyik sem lesz ellenőrzés nélkül eladási/beszerzési ár. Ha két oszlop ugyanahhoz a belső mezőhöz tartozna, a rendszer javítást kér. A hiányzó pénznem, áfa és nettó/bruttó jelleg ismeretlen marad; ismert profilértéket a pénzügyi beállításokban adhatsz meg.

Válassz pontos összekapcsolási kulcsot, ha ugyanazon beszállító további ár-/készletfájljait a meglévő tételekhez szeretnéd kapcsolni. Az automatikus javaslat pontos mintabeli egyezéseket mutat; az első kulcsválasztás mindig felhasználói jóváhagyás. Hasonló nevek és azonosítók nem elegendők. Megbízható kulcs nélkül a sor külön tétel marad. EAN, ár, készlet és gyártó nem kötelező: használható azonosító vagy név elegendő.

A mentett profil a következő feltöltésnél újrahasználható. Automatikus feldolgozás csak előzetesen engedélyezett profil és eltérésmentes minta esetén indul. A fejléc/sorrend, numerikus jelleg, mintabeli pénznem/árjelleg és jelentős numerikus eloszlás eltérései felülvizsgálatot eredményeznek. A szüneteltetés, folytatás, megszakítás, hibás sorok újrapróbálása és hibajegyzék-letöltés a futás adatlapján érhető el. Újrapróbálás az eredeti adatot nem javítja át: tartalmi hiba esetén javított fájlt tölts fel.

A **Webáruházmotorok / Exportmezők** felületen a központi admin kezeli a motorokat és a meződefiníciókat. Az ügyféladmin saját exportprofilt menthet, a központi kötelező mezők és validációik kikapcsolása nélkül. Az UNAS-mintából beolvasott mezők először opcionális javaslatok. Tényleges UNAS-termékexport ebben a fázisban nincs.

## Előzetes felmérés és architektúra

A meglévő FastAPI/SQLAlchemy/Alembic alkalmazást, cookie-munkamenetet, CSRF-védelmet, tenant-munkaterületet és szerepkörengedélyeket használjuk. A meglévő Celery alkalmazásban regisztrált `supplier.import` feladat dolgozik, a meglévő Redis brokerrel. Nincs második auth- vagy feladatkezelő keretrendszer és nincs fizetős AI-hívás.

Új komponensek:

- `import_parser.py`: kódolás/elválasztó/fejléc, XLSX lapok, szöveges azonosítók, normalizálás, oszlopjavaslat és modelfüggetlen AI-adapter interfész.
- `import_engine.py`: fájlrekonstrukció, profilfelismerés, kötegelt feldolgozás, idempotencia, zárolás és tartós kurzor.
- `import_api.py`: tenant szerint ellenőrzött feltöltés, előnézet, profilok, futások és központi exportmezők.
- `import_models.py`: csak az alkalmazás saját adatmodellje.
- `ImportWorkspace.tsx`: működő importfelület és exportmező-szerkesztő a meglévő navigációban.

A 13 főkategória, a fix kategóriaazonosítók, a hierarchia, a termékszerepek, a katalógusverziók, a profil-hozzárendelések és a paraméterértékek változatlanok. A modul nem hív eMAG-importot és nem ír a `pinfo_db` adatbázisba.

## Adatmodell és migráció

A `0006_supplier_import` migráció kizárólag az `adatdusito_dev` alkalmazás-adatbázisban hoz létre 9 táblát:

| Tábla | Szerep |
|---|---|
| import_suppliers | Tenant saját beszállítói |
| import_profiles | Jóváhagyott, visszakereshető profilverziók és jóváhagyó |
| import_runs | Állapot, profil, kurzor, statisztika, hiba, munkazárolás |
| import_file_chunks | Eredeti fájlbájtok 60 000 bájtos darabokban |
| import_rows | Eredeti sor, forráshely, értelmezési metaadat, hiba és termékhivatkozás |
| supplier_products | Aktuális beszállítói állapot, tenant/beszállító/pontos kulcs szerinti egyediség |
| import_changes | Tényleges mezőváltozás: előtte/utána és forrássor |
| store_engines | Központi motor- és meződefiníció, verzió |
| store_export_profiles | Ügyfél saját mezői, alapértékei és export-előkészítő szabályai |

Az eredeti fájl darabolt adatbázis-tárolása a backend és a worker közötti közös, tartós elérést biztosítja a Compose hálózatának vagy köteteinek módosítása nélkül. Olvasáskor egy ideiglenes helyi fájl készül, amely lezáráskor törlődik. A CSV soronként, az XLSX `read_only` módban olvasható. Az értelmezés nem tárol ismételt teljes terméksnapshotot: az aktuális állapot és a delta külön tárolódik; a korábbi értelmezett sor az eredeti adatbázissorból, az akkori változatlan profilból és a `1.0` normalizáló szerződésből áll elő, ismételt forrásfájl-beolvasás nélkül. Az Excel formátum-/numerikus bizonytalanságát a sor metaadata megőrzi.

A migráció bővíti a meglévő jogosultságjegyzéket:

| Jogosultság | Szerepek |
|---|---|
| imports.read | superadmin, tenant_admin, processor, reviewer |
| imports.manage | superadmin, tenant_admin, processor |
| exports.manage | superadmin |
| exports.profile | superadmin, tenant_admin |

A korábbi migrációk változatlanok. A központi motor kezdetben `unas`, üres meződefinícióval: kötelező mezőt nem találunk ki.

## Feldolgozási szabályok

Az azonosítók karakterláncok. A CSV vezető nullái és az Excel egyszerű `00000` számformátuma megmaradnak. Tudományos jelölésből nem találunk ki elveszett számjegyeket; az Excel tudományos formátuma és túl hosszú numerikus azonosítója is ellenőrzendő. Az eredeti XLSX bájtjai ettől függetlenül megmaradnak. Excel-képleteket nem futtatunk; szövegként és bizonytalansági jelzéssel kezeljük.

Támogatott kódolás: UTF-8/BOM, UTF-16/BOM és közép-európai CP1250; CP1252 kézzel megadható. A fallback kódolás szükség esetén felülbírálható. Számoknál magyar tizedesvessző, szóközös/pontos és nemzetközi ezreselválasztás kezelhető. Kétértelmű adatokhoz nem adunk kitalált pénzügyi jelentést. A regisztrált akciódátumok ismert ISO/magyar/nemzetközi dátummintái normalizálhatók; más alak ellenőrzendő marad.

A negatív készlet importoldalon negatív marad. A saját exportprofil `negative_stock_policy` értéke `zero` (alapértelmezett) vagy `preserve`: ez a későbbi exporthoz tárolt szabály, most nem alakít át adatot.

Egyetlen sor sem tűnik el észrevétlenül: üres sor `empty`, hibás mezőszám/azonosíthatatlan sor `error`, pontos ismétlődés `duplicate`, ütköző ismétlés `conflict`. A hibás és bizonytalan adatok eredeti alakja megmarad. Részleges feedben az üres érték nem törli a korábbi mezőt, a hiányzó sor pedig nem töröl terméket. Teljes terméktörzsnél a `not_seen_in_full_feed` számláló jelzi a nem látott korábbi tételeket; életciklus-kezelés és automatikus törlés nincs.

A feldolgozás 100 soros tranzakciókkal halad. A `(run_id,line)` elsődleges kulcs, a pontos beszállítói azonosság és a run munkazárolása védi az újrapróbálást. A worker 5 perces, kötegenként megújított zárolást használ. Folyamatleállás után a tartós kurzortól folytatható; a lejárt zárolás a Folytatás művelettel átvehető. Fájlon belüli eléréskor az olvasó a kurzorig újra átlép a sorokon, nem tart teljes fájlt memóriában. Tartalmi hiba újrapróbálása nem írhatja felül automatikusan az ütköző értéket.

Az AI-adapter nincs szolgáltatóhoz kötve. Kredit nélküli hívást elutasít, konfigurált provider hiányában kézi megfeleltetés használható. Ebben a kiadásban nincs bekötött vagy rejtett fizetős AI-hívás, nincs kreditelszámolás és nem jelenik meg kitalált AI-siker.

## Importprofil

A profil konfigurációja tartalmazza a formátumot, kódolást, elválasztót, fejlécsort, munkalapot, az index→belső mező megfeleltetést, az elemzés mintáját és típusstatisztikáit, az azonosítómezőt, a feed típusát, a kifejezetten jóváhagyott pénzügyi jelentést, az automatikus feldolgozás engedélyét és az oszloponkénti jóváhagyást. A név szerinti következő jóváhagyás új profilverziót hoz létre. A korábbi verzió megmarad; az utolsó sikeres feldolgozás a hozzá kötött befejezett futásokból lekérdezhető.

A profilfelismerés tenant/beszállító, fejlécazonosság (sorrendfüggetlen), adattípus, mintabeli pénzügyi kontextus és numerikus eloszlás alapján történik. Nincs kizárólag fájlnév szerinti azonosítás. Átnevezett oszlop vagy elégtelen minta nem indít felügyelet nélküli importot. A mintavételes eltérésfigyelés nem bizonyíthat olyan szemantikai változást, amelyhez a fájl semmilyen jelzést nem ad; a profil engedélyezése ezért kifejezett ügyfél-döntés.

## API és állapotok

A prefix `/api/v1/imports`. Minden beszállítói erőforrás a munkamenetben kiválasztott tenant szerint szűrt, superadmin esetén is. Más tenant objektumazonosítója 404-et ad. Minden módosítás a meglévő CSRF-ellenőrzést használja.

| Végpont | Funkció |
|---|---|
| GET fields | Belső mezőjegyzék |
| GET/POST suppliers | Saját beszállítók |
| GET profiles?supplier_id=… | Jóváhagyott profilverziók |
| GET/POST runs | Lapozott futások / multipart feltöltés |
| GET runs/{id} | Állapot, kurzor, statisztika, hiba |
| GET runs/{id}/source-preview | Lapozott eredeti előnézet |
| POST runs/{id}/preview | Mapping és offset szerinti értelmezett előnézet, írás nélkül |
| PUT runs/{id}/settings | Még jóvá nem hagyott fájl újraelemzése más lappal/beállításokkal |
| POST runs/{id}/approve | Új profilverzió és feldolgozás indítása |
| POST runs/{id}/actions/{action} | pause, resume, cancel, analyze, retry-errors |
| GET runs/{id}/rows | Lapozott eredeti/értelmezett sorok és átadási interfész |
| GET runs/{id}/errors.csv | Adatfolyam-alapú hibajegyzék |
| GET runs/{id}/file | Eredeti bájtok letöltése |
| DELETE runs/{id}/source | Lezárt futás fájljának törlése a megőrzési idő után, auditálva |
| GET runs/{id}/join-suggestions | Pontos, mintabeli beszállítón belüli kulcsegyezések |
| GET products | Aktuális saját beszállítói adatok |
| GET products/{id}/changes | Mezőváltozások története |
| GET engines; PUT engines/{key} | Központi motorok/mezők és auditált verziók |
| DELETE engines/{key}/fields/{field} | Központi mező törlése új definícióverzióban |
| POST engines/{key}/reference | CSV/XLSX fejlécből opcionális mezőjavaslatok |
| GET/POST export-profiles | Saját export-előkészítő profilok |

Állapotok: `uploaded`, `awaiting_approval`, `processing`, `paused`, `completed`, `partial`, `failed`, `cancelled`. Az elemzés a feltöltött futás zárolt háttérfeladata. A technikai hiba és a feladatszintű hibaüzenet elérhető; az érvényes kötegek megmaradnak. A profiljóváhagyás auditált és a böngésző bezárása nem állítja le a workert.

## Verziózott belső átadás

`GET runs/{id}/rows` válaszában `schema_version: "1.0"`, `tenant_id`, `supplier_id`, `run_id`, lapozás és `items` szerepel. Egy elem: `line`, `raw`, `normalized`, `issues`, `state`, `product_id`. A `normalized` tartalmazza a mezőértékeket (`fields`), a forrásoszlopot/fejlécet és Excel-bizonytalanságot (`provenance`), a `profile_id`, a megfeleltetési döntések (`mapping`), a `missing_fields` és `uncertain_fields` listáit. Ezt használhatja a CODEX 08–24; nincs szükség új fájlbeolvasásra. A normalizáló 1.0 szerződésének későbbi változása új verziót igényel, a régi futások nem értelmezhetők észrevétlenül új szabályokkal.

## Korlátok és üzemeltetés

Opcionális környezeti változók, jelenlegi `.env` módosítása nélkül:

| Beállítás | Alapérték |
|---|---:|
| IMPORT_MAX_BYTES | 50 000 000 bájt |
| IMPORT_MAX_ROWS | 250 000 adatsor |
| IMPORT_MAX_PRODUCTS | 100 000 kész tétel / futás |
| IMPORT_SOURCE_RETENTION_DAYS | 90 nap |

Legfeljebb 512 oszlop, 1 MB CSV-mező, 200 MB kibontott XLSX és 100 soros felismerési minta engedélyezett. A megőrzési művelet explicit, lezárt futásra alkalmazható; nincs váratlan automatikus adateltávolítás. A forrássorok és a változástörténet megmaradnak. A visszajátszás és a lapozott forráselőnézet soronként újra átlép a fájlon; nagyon nagy állományoknál ennek I/O-költsége van. XLS (régi bináris Excel), jelszavas Excel és tetszőleges kódolás automatikus felismerése nem támogatott.

A frontend Nginx feltöltési korlátja 51 MiB. A VPS külső Nginx proxyja is engedje át a kiválasztott fájlméretet: ha ott kisebb korlát van, azt a szerver adminisztrátorának külön ellenőriznie/módosítania kell. A fejlesztés nem módosítja ezt a meglévő szolgáltatást.

## Ellenőrzések és referenciafájlok

A ténylegesen feltöltött `besz_minta.csv` helyi ellenőrzése: UTF-8 BOM, pontosvessző, 27 oszlop, 4948 sor, 3 termék és 4945 üres sor. A helyi importpróba 3 tételt hozott létre; a hiányos/scientific azonosítók bizonytalansága megmaradt. Az `unas_minta.xlsx` olvasható munkalapja 115 mezős; ezek opcionális referenciaként beolvashatók. A kereskedelmi adatokat tartalmazó feltöltött minták nem kerülnek a Gitbe. A CI szintetikus mintákon reprodukálja a problémás alakokat, a 27/4948/3 darabszámot és a 115 oszlopos referenciát.

Automatizált tesztek: BOM/CSV, XLSX/munkalapok, vezető nulla és Excel számformátum, bizonytalan GTIN, magyar/nemzetközi szám és dátum, negatív készlet, üres/hiányos/hibás sor, árjóváhagyás, profil újrafelhasználás és eltérés, ismétlődés/ütközés, több fájl pontos összekapcsolása, folytatás/újrapróbálás, tenant/engedély, központi mező CRUD és kötelező validáció, kredit nélküli kézi út, 50 000 soros streaming memóriahatár, migráció upgrade/downgrade és asztali/mobil felhasználói út.

Külön helyi ellenőrzés: valódi MySQL 8 migráció (`0001` → `0006`, illetve `0006` vissza/előre), Redis és Celery workerrel végigfutó import. A tesztállapot és a készlet ténylegesen ellenőrzött; nem mock importeredmény. Ezek kizárólag eldobható helyi konténerek voltak.

## Telepítés előkészítése

Ez a változás **migrációt igényel**. Készíts alkalmazás-adatbázis-mentést és ellenőrizd a munkafát/Compose-konfigurációt. A meglévő `.env`, az external `adatdusito-dev-net`, a MySQL/Nginx/UFW/HTTPS-beállítások és az éles környezet változatlanok. Nincs katalógusimport vagy aktiválás.

A szerver adminisztrátora a frissített image buildje után a saját alkalmazás-adatbázison futtassa a `docker compose run --rm migrate` parancsot, és csak sikeres migráció után frissítse a backend, worker, frontend konténereket. Az új workernek az új image-et kell használnia. A VPS-en a fejlesztés során nem futtattunk parancsot.

Helyi eredmény: **173 sikeres teszt** a teljes backend/scripts csomagban, majd a végső mezőjegyzék-/átadási pontosítás után **22 sikeres célzott backend/migrációteszt**. Az új modul asztali és mobil felületét valódi FastAPI-val és tényleges, szinkron tesztütemezéssel ellenőriztük; ez nem helyettesíti a külön elvégzett Redis/Celery próbát. Frontend TypeScript/Vite build, Ruff és diffellenőrzés sikeres. Egy külső Starlette/AnyIO deprecation warning maradt.

A nem megfeleltetett oszlopok a belső átadás `unmapped_attributes` listájában is elérhetők (index, fejléc, eredeti érték), központi mező vagy eMAG-paraméter létrehozása nélkül. Külön beszerzési-/listaár-mezőt a felhasználó kézzel választhat; az eredeti LISTPRICE/LASTINITIALCOST fejléc önmagában továbbra sem igazolja e jelentéseket.

Végső profilpontosítás: feltöltés előtt konkrét meglévő profil is kiválasztható (csak ugyanannak a tenantnak és beszállítónak a profilja). A sorrendfüggetlen újrafelismerés az új fájl elválasztóját, munkalapját és fejlécsorát használja; a mentett pénzügyi/szabálybeli döntéseket tartja meg. Az oszlopok jóváhagyási metaadata az új sorrendhez igazodik. Külön regressziós teszt ellenőrzi a pontosvesszős → vesszős, átrendezett CSV-t. Futásváltáskor az előző pénzügyi űrlapértékek nem öröklődnek másik importba. A profil név/verzió tenanton és beszállítón belül egyedi, konkurens jóváhagyás sem hozhat létre két azonos verziót. A végső módosításokkal 25 célzott modul-/migráció-/böngészőteszt sikeres.
