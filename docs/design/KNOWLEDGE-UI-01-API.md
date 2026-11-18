# KNOWLEDGE-UI-01 – referenciaforrás-adminisztráció

Bázis: `claude/release-candidate-03` @ `d0e2c2c`. Saját ág: `codex/knowledge-ui-01`.

## Migráció és integrációs függőség

A Tulajdonos által kiosztott **0015** a Claude-hoz rendelt **0014**-re épül. Lánc: `0011 → 0012 → 0013 → 0014 → 0015`. Claude valódi `0014` migrációja a tulajdonos külön engedélyével, a `9854587` commit integrálásával került a munkágba (`1298f9f`). Az RC-03 és a main ág változatlan maradt. A teljes láncteszt aktív; nincs helyettesítő vagy átugrott migráció.

A 0015 kizárólag:

- a `reference_import_runs` táblához adja a `ui_config` JSON, `ui_cursor` integer, `ui_task_token` és `ui_lease_until` mezőket;
- létrehozza a `reference_import_chunks(run_id, ordinal, data)` táblát, 60 000 bájtos darabokkal;
- tárolt feltöltések vagy futó feladatok esetén megtiltja a downgrade-et. Az eredeti forrás- és termékadatokat nem törli.

A `ui_` prefix az adminfelület saját feladatmetaadatait választja el a KNOWLEDGE-01 oszlopaitól. A meglévő `ReferenceProductSource`, `ReferenceImportRun`, `ReferenceProduct`, azonosító- és attribútumtáblák maradnak az egyetlen referenciatár.

## Jogosultság

Minden végpont egyszerre igényel `reference.manage` jogot, tényleges rendszerszintű hozzáférést és `tenant_id = null` munkaterületet. Hiányzó jog: 403; ügyfél-munkaterület: 409. Az ügyfél-adminisztrátor nem rendszeradminisztrátor. A meglévő Origin/CSRF/no-store védelem minden új végpontra érvényes. A menüpont csak rendszerszinten látszik.

## API / DTO v1

Prefix: `/api/v1/knowledge-admin`.

| Művelet | Végpont | Tartalom |
|---|---|---|
| GET | `/options` | Választható mezőjelentések és aktív ügyfelek |
| GET | `/sources?q=&offset=0&limit=25` | `{items,total,offset,limit}`; legfeljebb 100 forrás/oldal |
| GET | `/sources/{id}` | Forrás részletes statisztikája |
| PUT | `/sources/{id}` | `{name,usage_status,enrichment_enabled,usage_note}`; indoklás és audit kötelező |
| GET | `/sources/{id}/imports?offset=&limit=` | Lapozott importelőzmények |
| GET | `/sources/{id}/audit?offset=&limit=` | Lapozott adminaudit |
| POST multipart | `/uploads` | `file`, `source_name`, `scope: system\|tenant`, opcionális meglévő `source_id`, `tenant_id`, `reuse_authorized` |
| GET | `/imports/{id}` | Feladatállapot, számlálók, első sorhibák, megfeleltetések és előnézet |
| POST | `/imports/{id}/preview` | `{mapping: {"0":"sku",...}}`; módosítás nélküli, maszkolt előnézet |
| POST | `/imports/{id}/start` | Ugyanilyen megfeleltetés; külön importindítás |
| POST | `/imports/{id}/cancel` | Leállítás; mentett termékek és pozíció megmaradnak |
| POST | `/imports/{id}/retry` | Sikertelen, megszakított vagy 15 perce elhagyott webes feladat folytatása |
| POST | `/imports/{id}/repeat` | Befejezett webes feltöltés új futásként ismétlése |

Forrás DTO: `id,key,name,kind,tenant_id,products,parameters,attribute_values,imported_at,updated_at,state,last_import,usage_status,enrichment_enabled,usage_basis,usage_note,trust_level,contribution,quality,excluded_columns`.

`quality`: `valid_gtin_products`, `without_valid_gtin`, `with_name`, `verified_products`. Ezek tényleges adatbázis-összesítések, nem kitalált minőségi vagy bizalmi pontszámok. `parameters` a termékekhez ténylegesen kapcsolt, különböző paraméterdefiníciókat számolja; az EAN külön azonosító, nem termékattribútum.

Import DTO: `id,source_id,file_name,state,counters,errors,started_at,finished_at,cursor,uploaded,retryable,headers,mapping,preview,parser`. A számlálók közt az elemzett/előkészített sorok és a meglévő motor `created,updated,unchanged,errors,empty` értékei szerepelnek. Új: `protected` és `excluded_cells`. Sorhiba: `{line,code,column?}`. Az előnézet legfeljebb 10 sor/cellánként 1024 karakter; megőrzi a valódi forrásrekord sorszámát; a nem kijelölt oszlopok értéke `[Kizárva]`. A `parser` nem tartalmaz forrásadatokat; a tárolt teljes nyers elemzési JSON nincs az API-ban.

Állapotok: `queued → analyzing → preview → queued_import → converting → running → completed|partial`; mellékágak: `failed`, `cancelled`. A frontend magyar címkéket mutat. Kizárólag a `preview` állapotból indítható import. A CLI-importok továbbra is láthatók, de tárolt webes fájl hiányában új feltöltéssel frissíthetők.

## Egyetlen importmotor

A CSV/XLSX beolvasása a meglévő `import_parser.analyze/rows` függvényekkel történik. A `knowledge_uploads` csak tartós feladatorchestráció és oszlopadapter: a megengedett mezőkből folyamatos, szöveges UNAS-alakú sorfolyamot ad át, köztes XLSX és annak cellakorlátja nélkül. A teljes sémaregisztrációt, termék-upsertet, attribútum- és azonosítómentést továbbra is a **`reference_products.import_export`** végzi.

Az importmotor új, opcionális keyword argumentumai: `run=<ReferenceImportRun>`, `checkpoint=<callback>`, `prepared={headers,total,rows,warnings,excluded_cells}`. A korábbi CLI-hívás változatlan. A webes séma `reference_upload/` névterű; nem válthatja fel a sablongenerátor alapértelmezett natív `unas_export/` sémáját. A callback `(db, run) -> bool`; csomaghatáron ellenőrzi a tokent és állapotot. A sorpozíció, számlálók és hibák együtt commitolódnak. Új futás ismételhető, megszakított futás pozícióból folytatható. Azonos `(source_id,source_sku)` és nyers hash nem hoz létre új terméket. Már hitelesített vagy védett rekord eltérő importját a `protected` számláló jelzi; az értékek változatlanok.

## KNOWLEDGE-01 együttműködés és adatvédelem

- Rendszerszintű új forrás: az RC-03 tulajdonosi politikája szerint `approved_enrichment`, `owner_policy:2026-11-17`, `enrichment_enabled=true`, `contribution=automatic`. A feltöltő kifejezetten nyilatkozik az újrahasznosítási jogról.
- Meglévő forrás korlátozását vagy kizárását újraimport nem oldja fel. A `reference_products.usable_sources` minden keresésnél ellenőrzi a forrás jogát.
- Ügyfélhez kötött adminfeltöltés: `tenant_id` megmarad, `internal_only`, `tenant_upload_pending_review`, `contribution=pending`, `enrichment_enabled=false`. **Tenantforrás a közös keresésbe akkor sem kerülhet, ha egy korábbi admin API tévesen engedélyezi.**
- A hagyományos beszállítói importok automatikus tudásátvételét a KNOWLEDGE-01 motor kezeli; ez a felület nem épít mellé második tanulási vagy átvételi motort. Az ebből keletkező `ReferenceProductSource` rekordok ugyanebben a listában jelenhetnek meg.
- Megengedett, explicit megfeleltetés: cikkszám (csak forráson belüli technikai kulcs), terméknév, EAN, márka, kategória, leírás, kép, egység, termékparaméter. Ismeretlen oszlop alapból kizárt. A személyes/ügyféloszlopokat, árat, készletet, SEO- és rendszermezőket a webes adapter nem adja az importmotornak. Szabad szövegbe ágyazott személyes adat felismerésére nem állítunk teljes körű DLP-garanciát: a rendszergazda ellenőrzi a kijelölt tartalmat.
- A feltöltés és elemzés nyers fájlja/mintái az adminfeladat privát inputjai, **nem tudásbázis-adatok**. A KNOWLEDGE-01 nem olvashatja ezeket közös terméktudásként; csak a jogosult források normalizált, megosztható termékadatait használhatja.
- Visszakövethetőség: forrás, eredeti fájl hash, importfutás, eredeti sorpozíció, nyers termékhash, első/utolsó importkapcsolat. Az audit nem tárol cellatartalmakat. Képlet nem értékelődik ki; bizonytalan Excel-azonosító és nem tárolható cella kizárva, sorjelöléssel.

## Korlátok és ellenőrzés

Fájlonként 50 MB, a meglévő XLSX kibontási védelem, legfeljebb 512 forrásoszlop és egymillió forrásrekord. Feldolgozás Celeryben; a webes kérés nem végez teljes importot. Egy forráshoz egyszerre egy adatíró import indulhat. Az alkalmazás-adatbázison kívül nincs írás; `pinfo_db`, `.env`, Compose, Nginx, VPS változatlan.

Önállóan ellenőrizhető: API/SQLite üzleti és jogosultsági tesztek, a 0015 DDL-je külön műveleti tesztben, frontend build/lint/tesztek, asztali és 390 px-es böngészőteszt. Az integrált Alembic- és MySQL-tesztek a teljes `0013→0014→0015` láncot ellenőrzik, beleértve a régi adatok megőrzését és a visszaállítás előtti döntésvédelmeket. A hosted CI ugyanazokat a kapukat futtatja.

## Publikált KNOWLEDGE-01 szerződés (9854587)

A `claude/knowledge-01` ág publikált bázisa `9854587281c5e70396065f4f244bafee1ccf88d8`. A tényleges `0014_knowledge_base.py` változatlanul `0013`-ra épül, hét új tudástáblát ad; a 0015 által bővített referenciaimport-mezőkkel nincs DDL-ütközése.

Claude fenntartja az `app.knowledge`, `app.knowledge_models`, **`app.knowledge_views`** modulokat és a `/api/v1/knowledge` végpontokat. Az adminfelület új modulja **`app.knowledge_admin_views`**, előtagja `/api/v1/knowledge-admin`; nincs név- vagy végpontütközés. Az `options.knowledge_engine_available` jelzi a motor jelenlétét.

Integrációs hook: `knowledge_bridge.schedule_source(source_id)` kizárólag Claude `knowledge.schedule(source_id=...)` függvényét hívja, ha az elérhető. Nem végez tanulást vagy szinkron újraépítést. Az import és a forrásjog-módosítás ezután kér háttérfrissítést; az integrációkor a referenciaimport végén **egyetlen** ütemezési hívás maradjon. A `reference_products` importbekötését és a `main.py` routereit mindkét ágból meg kell őrizni.

A motor által létrehozott, engedélyezett `tenant_import`/`contribution=automatic` források a motor saját, megosztható megfigyeléseivel dolgozhatnak. Ezeket az adminfelület nem jelöli függőben levőnek és engedélyük kezelhető. Az adminfelületen külön feltöltött ügyfélfájl továbbra is `contribution=pending`; a közvetlen referencia-lookup nem adhat vissza tenant nyers rekordját. A két adatút nem azonos.

A két ág egyesítése a tulajdonos kifejezett engedélyével kizárólag a `codex/knowledge-ui-01` ágon történt meg. Az importütemezés és a head-teszt két ütközése mindkét fejlesztés megőrzésével oldódott fel. Az integrált ág teljes lánctesztjének elvárt headje `0015`, szigorú `0013 → 0014 → 0015` szülőellenőrzéssel; a KNOWLEDGE-01 tesztjeit és az adminfelület tesztjeit együtt kell futtatni.

A `tenant_import` források fájlos frissítését a referenciakezelő nem engedi: ezeket továbbra is a beszállítói importmotor frissíti. Az adminisztráció az engedélyüket kezeli és naplózza; új ügyfél-referenciafájl külön, átvételre váró forrásként tölthető fel.

## Az integrált ág ellenőrzése

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_knowledge_admin.py backend/tests/test_knowledge_ui_migration.py
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend test
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_knowledge_admin_browser.py backend/tests/test_template_preparation_api_browser.py scripts/tests/test_help_browser.py
```

Az integrált futásban nincs `-k` szűrés vagy migrációs tesztkihagyás. A közös tesztfixture a KNOWLEDGE-01 ütemező hálózati küldését leválasztja; a motor tényleges újraépítését a tesztek a saját SQLite/MySQL adatbázison hajtják végre. Ezzel a szintetikus rekordok nem kerülnek egy fejlesztő esetleg futó brokerébe.

A `scripts/mysql_knowledge_ui_check.py` kizárólag üres, loopback MySQL 8.0 tesztadatbázist fogad, `KNOWLEDGE_UI_FIXTURE_ACK=isolated-knowledge-ui-01` megjelöléssel. A CI külön eldobható szolgáltatáson futtatja, a régi RC02- és migrációs próbák mellett. Ellenőrzi a 0013-as rekord megőrzését, a webes feltöltést, az ismételhetőséget, a tényleges KNOWLEDGE-01 újraépítést, a feltöltésvédelmet, a több lépéses downgrade előtti döntésvédelmet és az `0015→0014→0015`, `0015→0013→0015` köröket. Nem VPS-telepítési parancs.

Telepítés kizárólag tulajdonosi jóváhagyás és mentés után: a teljes migrációs lánc sorrendben futtatandó, majd a backend/worker/frontend frissítendő. Ebben a munkában sem VPS-telepítés, sem main-/RC-03-merge nem történt.

## Ügyfélforrások tényleges statisztikája

A motor `tenant_import` típusú forrásánál a termékek és minőségi számlálók a `supplier_products`, a paraméterszám a kitöltött eMAG `product_parameter_values` rekordokból jön. A forrás feltöltési előzményei az eredeti `ImportRun` összesítői, `engine=supplier` megkülönböztetéssel; csak állapot/számláló/időpont adatok, nyers sor, ár, készlet és beállítás nélkül. Ezek az előzmények a referenciaadminban csak olvashatók; műveleteik az ügyfél eredeti importmunkaterületén érhetők el. A referenciafeltöltések `engine=reference` jelölésűek, az importazonosítók két tartományát a felület nem keveri.

A minőségi összesítések számai explicit egészértékű SQL `CASE` összegzéssel készülnek, nem logikai `SUM` eredményként: több érvényes/named rekord nem válhat `true` értékké.
