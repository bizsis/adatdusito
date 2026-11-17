# UNAS-REF-01 – UNAS-sématár és termékreferencia-adatbázis

- **Ág:** `claude/unas-reference-database`, kiindulás: `codex/release-candidate-02` @ `0580a74`; a PR célága is ez.
- **Migráció:** `0013` (a Tulajdonos kiosztása). A `0012`-t a Codex párhuzamosan fejleszti.
- **Mintafájl:** `UnasShop_engermarket-unas-hu_20261117-084322.xlsx` – 1 munkalap, 135 oszlop, 18 454 termék.
- **Mi nem került a Gitbe:** a minta tartalma (termékek, árak, vevőcsoport-adatok). A tesztek szintetikus XLSX-et használnak, és csak a 135 fejlécet rögzítik (`backend/tests/unas_export_headers.py`), a vevőcsoportnevek helyén `Csoport A–E` szerepel.

## A meglévő rendszer felmérése

| Terület | Megállapítás | Döntés |
|---|---|---|
| eMAG-adatok | Az `emag_categories`, `emag_category_parameters` és `emag_parameter_values` a **csak olvasható `pinfo_db`-ben** vannak (`app/reference.py`). Az alkalmazás saját, verziózott másolata a `catalog_*` táblákban él (`app/catalog_store.py`). | Az új kód egyiket sem írja. A javaslatkészítés az aktív `catalog_*` verzió paramétereit csak olvassa. A teszt ellenőrzi, hogy a `catalog_parameters` és a `reference_sources` sorszáma nem változik. |
| Meglévő referenciatáblák | A `reference_sources` és a `reference_observations` (0003) **kategória-kutatási bizonyítékok**, nem termékek. | Nem bővíthetők termékreferenciává párhuzamos jelentés nélkül, ezért külön `reference_product_*` táblák készültek. |
| Oszlopfelismerés | `app/import_parser.FIELDS` (aliasok és `norm`) | A sablontervező ezt használja annak felismerésére, hogy egy beszállítói oszlop már lefed-e egy UNAS-mezőt. Új felismerő nem készült. |
| Paraméter-alias | A `parameter_aliases` (0010) beszállítói címkéket köt eMAG-paraméterhez. | Más irány: a `parameter_mappings` eMAG-paramétert köt UNAS-paraméterhez vagy -mezőhöz. |
| Sablongenerálás | **Egyik ágon sincs** (a `main`, az RC-01/02, a HELP-01/02 és a CATEGORY-03D ágakat is ellenőriztem). | A feladat szerint csak kompatibilis adatmodell és interfész készült (`template_plan`, `POST /api/v1/unas/template-plan`), a generátor maga nem. |

## A sématár (`unas_field_definitions`)

Egy sor egy export egy oszlopa: `schema_source` (`unas_export/<áruház>/<verzió>`), pozíció, eredeti fejléc, `field_key` (ASCII), `scope`, `field_group`, `data_type`, `requirement` és annak forrása, `importable`, `default_value`, `validation`, `note`, valamint `profile`. A `profile` tartalommentes oszlopprofil: kitöltöttség, típusok, maximális hossz.

| Besorolás | Darab (a mintában) | Jelentés |
|---|---:|---|
| `standard` | 97 | Fix nevű UNAS-exportoszlop, beleértve a számozott családokat (`Tartalmi elemek N`, `CrossSale N` …). |
| `store_specific` | 38 | Az áruház saját paraméterei (26 `Paraméter: …`), a vevőcsoportárak (`Ár: <csoport>`, `Ár típus: <csoport>`, 10 db) és a `Vásárló csoport …` (2 db). **Soha nem globálisan kötelező.** |
| `unknown` | 0 | – |

**A kötelezőség forrása.** Az unas.hu ebből a környezetből nem volt elérhető (DNS-hiba), ezért:

- **`required` (6):** `Cikkszám`, `Termék Név`, `Státusz`, `Kategória`, `Nettó Ár`, `Bruttó Ár`. Forrás: `unas_help_excerpt`, vagyis az UNAS súgó és blog keresési kivonata (2026-11-17). **Ideiglenes, az élő UNAS-dokumentáción ellenőrizni kell.**
- **`recommended` (6):** `Rövid Leírás`, `Tulajdonságok`, `Kép link`, `Raktárkészlet`, `Egység`, `Tömeg`. Forrás: `adatdusito`, azaz projektjavaslat, nem UNAS-szabály.
- **`importable`:**
  - `false` a rendszer által generált `Létrehozás`, `Utolsó Módosítás` és `Termék link` oszlopnál;
  - `null` (ismeretlen) az `Azonosító` oszlopnál;
  - minden más `true`, a mintabeli előfordulás alapján.
- **`validation`:** típusonkénti alapszabályok. Az árak és a készlet `time_dependent: true` jelölést kapnak.
- **`default_value`:** üres, mert dokumentált alapértéket nem találtunk.

A fájl oszlopai **nem a teljes hivatalos UNAS-séma**, hanem ennek az áruháznak ez az exportja. Egy másik áruház vagy verzió saját `schema_source` alá kerül. Ha ugyanazzal a forrással eltérő fejléc érkezik, a rendszer elutasítja.

## Paraméterdefiníciók (`unas_parameter_definitions`)

Példa: `Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1` → a `|` mentén darabolva:

| Pozíció | Jelentés | Bizonyíték |
|---|---|---|
| 0 | név (`Szélesség`) | a minta |
| 1 | csoport (üres; vagy `Connestic`, `Marketplacek`) | a minta |
| 2 | típus: `text`, `num`, `enum`, `enummore`, `link_text` | a minta |
| 10 | mértékegység (`cm`) | a minta (`unit_source: export_sample`) |
| 3–9, 11– | **nem értelmezett** | a `settings` listában, változatlanul megőrizve |

A fejléc `name|group|type|settings…` alakban bájtra visszaállítható; ezt teszt ellenőrzi. Az azonos nevű, de eltérő csoportú paraméterek külön sort kapnak (pl. a két `Terméktípus`), és az automatikus javaslat ezeket nem vonja össze.

## eMAG–UNAS megfeleltetés (`parameter_mappings`)

Mezők:
- eMAG-kategória (opcionális) és eMAG-paraméter (azonosító és név);
- **pontosan egy** cél: UNAS-paraméter vagy UNAS-mező;
- `unit_from`, `unit_to` és `unit_factor`: mm/cm/m, g/kg, ml/l; más párosítás 422;
- `status`: `proposed`, `approved` vagy `rejected`;
- `origin`: `automatic` vagy `manual`;
- `confidence`, `reason`, valamint ki és mikor döntött.

Működés:
- Az **automatikus javaslat** (`propose`, `POST /parameter-mappings/propose`) csak pontos hajtogatott névegyezésből vagy egy kis szinonimalistából készül (Brand/Márka, Width/Szélesség, Height/Magasság, Length/Hosszúság, Material/Anyag, Size/Méret). Mindig `proposed` állapotú. Kétértelmű célra (azonos név több csoportban) nem készül javaslat.
- A **döntéshez** (`approve`/`reject`) és a kézi felvételhez `reference.manage` jog kell, és auditált. A sablontervező csak `approved` megfeleltetést használ.

## Termékreferencia-tár

| Tábla | Tartalom |
|---|---|
| `reference_product_sources` | forrás (`unas_export:<áruház>`), `usage_status` (`restricted` alapból, `internal_only`, `approved_enrichment`, `revoked`), `enrichment_enabled` (alapból `false`), döntéshozó és időpont, kizárt oszlopok |
| `reference_import_runs` | futásonként: fájlnév, SHA-256, állapot, számlálók, az első 200 sorhiba (`line`, `code`) |
| `reference_products` | forrás és cikkszám (egyedi a forráson belül), UNAS-azonosító, név, márka, kategóriaút, rövid és részletes leírás, képlinkek, termék-URL, **`raw`** (minden nem kizárt, nem üres oszlop az exportált értékkel), `raw_sha256`, első és utolsó import |
| `reference_product_identifiers` | szöveges azonosítók: `gtin` (minden EAN-oszlopból, ellenőrzőszámmal, `valid` és `issues`), `source_sku`, `external_id` |
| `reference_product_attributes` | az áruházi paraméterek értékei paraméterdefinícióhoz kötve (EAN nélkül, mert az azonosító) |

Megjegyzések:
- **A mezők forrása:** a „részletes leírás” a `Tulajdonságok`, a márka a csoport nélküli `Paraméter: Márka` oszlopból jön.
- **Gyártói cikkszám:** ebben az exportban nincs ilyen oszlop. A `Cikkszám` az áruház saját cikkszáma, ezért csak a forráson belül egyedi.
- **Kizárt oszlopok:** az `Ár: <csoport>`, az `Ár típus: <csoport>` és a `Vásárló csoport …` sosem kerül a tárba. Ezek áruházspecifikus kereskedelmi adatok, és a csoportnevek személyt is azonosíthatnak.

**Import** (`python -m app.reference_products import <fájl> [--store-key K --version V]`):
- az XLSX-et streamelve olvassa (`openpyxl` `read_only`);
- 500-as kötegekben commitol, soronként savepointot használ: egy hibás sor naplózódik, a többi halad;
- a forrás és a cikkszám alapján upsertel; azonos `raw_sha256` esetén nem ír, így az ismételt import nem duplikál;
- csak az alkalmazás-adatbázist írja.

**Felhasználás** (`lookup`):
- Csak `approved_enrichment` állapotú **és** `enrichment_enabled` forrásból ad találatot.
- Sorrend és megbízhatóság:
  - érvényes GTIN: 0,95;
  - érvénytelen GTIN: 0,60;
  - több termékre illeszkedő GTIN: −0,25;
  - márka és név pontos egyezése: 0,50.
- A találat csak javaslat (`overwrites_supplier_data: false`), és nem tartalmaz árat, készletet vagy időbélyeget (`excluded: time_dependent`).

A felhasználási jog beállítása `PUT /api/v1/unas/reference-sources/{id}/usage` (`reference.manage`, kötelező indoklással, auditálva).

## A sablongenerátor interfésze

`template_plan(db, schema_source, supplier_headers, emag_parameters)`, illetve `POST /api/v1/unas/template-plan` (`reference.read`). Az oszlopsorrend:

1. **A beszállítói oszlopok** változatlanul, eredeti sorrendben. A `covers` jelzi, ha egy oszlop egy standard UNAS-mezőt lefed (az `import_parser` aliasai alapján: SKU → Cikkszám, NAME → Termék Név …).
2. **A hiányzó standard `required` és `recommended` UNAS-oszlopok.** Áruházspecifikus és vevőcsoport-oszlop soha nem kerül ide.
3. **A kategória eMAG-paraméterei.** Jóváhagyott megfeleltetésnél az UNAS-paraméter teljes fejlécével (pl. `Paraméter: Márka||enum|…`), egyébként `eMAG: <név>` néven.

Egyetlen oszlop sem szerepelhet kétszer (normalizált név alapján). Az XLSX/CSV letöltést a sablongenerátor ezen az oszloplistán valósítja meg. Integráció: a generátor a `schema_source`-t (`GET /api/v1/unas/schemas`) és a kategória eMAG-paramétereit adja át, a válasz `columns` listáját pedig sorrendhelyesen írja ki.

## Migráció és integráció a 0012-vel

- A `0013` additív: 8 új tábla, meglévő táblához, sorhoz vagy jogosultsághoz nem nyúl.
- A downgrade a táblákat FK-sorrendben, a saját indexeikkel együtt dobja el (a RELEASE-02 B1 tanulsága szerint). Megtagadja a futást, ha mapping- vagy felhasználási döntés létezik.
- A referenciasorok a forrás-exportból újra betölthetők.
- **Most:** `down_revision = "0011"`, mert a `0012` ezen az ágon nincs, és a `0013` nem függhet a Codex még nem integrált változásaitól.
- **Integráláskor kötelező** (a két ág összefésülése után, egy commitban):

  ```diff
  --- a/backend/migrations/versions/0013_unas_reference.py
  +++ b/backend/migrations/versions/0013_unas_reference.py
  -down_revision = "0011"
  +down_revision = "0012"
  ```

  A `test_unas_reference.py::test_single_alembic_head_and_0013_chain` két head esetén elbukik, és a `0012` jelenlétében `down_revision == "0012"`-t vár. Ugyanígy a `migrate` szolgáltatás `alembic upgrade head` parancsa is két headdel hibát adna. Így a sorrend `0011 → 0012 → 0013` lesz.
- **A `0013`-at az integráció előtt nem szabad tartós adatbázison futtatni.** Ha egy adatbázis már `0013`-on áll, az átkötés után az Alembic a `0012`-t alkalmazottnak tekintené. (A `0013` tábláinak nincs függőségük a `0012`-re, csak a lánc sorrendje változik.)

## Ellenőrzés

- **`backend/tests/test_unas_reference.py`** (11 teszt, a feladat 12 pontja):
  - mind a 135 oszlop besorolva;
  - paraméterfejlécek, veszteségmentes visszaállítás;
  - áruházspecifikus és globális mezők elkülönítése;
  - szöveges cikkszám és EAN, vezető nullával;
  - több EAN, és a duplikált EAN csak egyszer kerül be;
  - azonos nevű paraméterek eltérő csoportban;
  - eMAG–UNAS javaslat, jóváhagyás, jogosultság (403/409/422) és mértékegység;
  - ismételt import (változatlan és módosult sor);
  - 4000 soros XLSX;
  - az eMAG- és `catalog_*` adatok érintetlenek, a teljes meglévő tesztcsomag zöld;
  - korlátozott vagy visszavont forrás kizárása a dúsításból;
  - sablonterv-sorrend, duplikáció nélkül;
  - egyetlen Alembic-head és a `0013` additív migrációja, védett downgrade-del.
- **Eldobható MySQL 8.0.46** (helyi, loopback; nem VPS, nem `pinfo_db`):
  - `0013` upgrade, downgrade `0011`-re (nem marad tábla), újra upgrade;
  - a meglévő `mysql_release02_downgrade_check.py` (56/56) és `mysql_release01_check.py` `exit=0` a `0013` mellett;
  - **a valódi mintafájl importja ugyanebbe az eldobható adatbázisba**, az alkalmazás saját engine-jével és timeoutjaival:

    | Futás | Eredmény |
    |---|---|
    | 1. | 18 454 új, 0 hiba, 12 kizárt oszlop, 81 s |
    | 2. | 18 454 változatlan, 38 s |
    | Létrejött | 26 366 GTIN, 88 555 attribútum, 135 meződefiníció, 26 paraméterdefiníció; kb. 112 MB |

    A forrás állapota `restricted`, a dúsítás kikapcsolva.

**A referenciaadatokat nem töltöttük be semmilyen tartós (staging vagy éles) adatbázisba.** Csak az importáló készült el, a fenti eldobható ellenőrzéssel.

## Nyitott kérdések

1. A kötelező UNAS-oszlopok ellenőrzése az élő UNAS-dokumentáción: az unas.hu ebből a környezetből nem volt elérhető.
2. A paraméterfejléc 3–9. és 11–13. pozíciójának jelentése (UNAS-dokumentáció kell hozzá).
3. Felhasználási jog: kell-e írásos engedély az engermarket-adatok más ügyfelek dúsításához való használatához (`approved_enrichment`)?
4. Az éles importot a Tulajdonos indítja (a `0012` integrálása után), mentéssel: `docker compose exec backend python -m app.reference_products import <fájl> --store-key engermarket-unas-hu --version 20261117-084322`.
