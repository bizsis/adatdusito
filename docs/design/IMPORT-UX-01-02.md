# IMPORT-UX-01/02 – importelőzmény-törlés, valós előnézet, biztonságos mezőjavaslatok

- Források: [#41](https://github.com/bizsis/adatdusito/issues/41) és [#42](https://github.com/bizsis/adatdusito/issues/42).
- Kiindulás: `codex/release-candidate-01` @ `09dc09b` (#40).
- Ág: `claude/import-ux-41-42`.
- Nem volt `main`-merge és VPS-telepítés, a meglévő adatbázisban nem módosítottunk adatot, a `pinfo_db`-t nem érintettük.

## Reprodukció a #40-es release-candidate-en

Az eredeti `besz_minta.csv` nem érhető el a repóban, ezért **rekonstrukcióval** dolgoztunk. Ez a #42 tényei alapján készült: UTF-8 BOM, `;` elválasztó, 27 oszlop, 3 terméksor és 4945 sor 27 üres mezővel. A hibajegyben idézett értékek is benne vannak:

- `LASTINITIALCOST` `405,51`;
- `LISTPRICE` `589,7637795`;
- `BARCODE` `8,71999E+12` és `8,71716E+12`;
- `QUANTITY` `-35132`, `-710`, `-16920`.

A többi fejléc helyőrző. A rekonstrukció a `backend/tests/test_import_ux.py` fájlban található (`besz_minta()`).

| Megfigyelés (változatlan RC) | Eredmény |
|---|---|
| fizikai sor, oszlop | 4949 sor (1 fejléc + 4948), mindegyik 27 oszlop |
| `analysis.data_rows` | **3** – a backend már eddig is helyesen számolt, üres sorból terméket nem csinált (`counters`: `ready 3, empty 4945`) |
| forráselőnézet (`POST /runs/{id}/preview`) | **198 lap**, ebből **197 csupa üres sor**; a felület minden sorhoz egy teljes `JSON.stringify` `<pre>`-t rajzolt |
| feldolgozás utáni sorlista | 4948 sor, ebből 4945 üres, soronként JSON |
| automatikus javaslat | `LASTINITIALCOST → price` (**Ár**). A `LISTPRICE` nem kapott javaslatot: a normalizált `listprice` a `list_price` és a `price` aliasaira is illeszkedett, ezért kétértelmű lett. |
| importelőzmény törlése | `DELETE /imports/runs/{id}` → **405**: ilyen végpont nincs. Az RC-ben **sem API, sem UI** nem törölt importrekordot; az egyetlen DELETE (`/runs/{id}/source`) csak lejárt forrásfájlt töröl. |

**A „törölt” #1/#2 visszatérése.** Valódi törlés nem történt, mert nem is történhetett. Új feltöltés után a lista a szerverről töltődik újra (`refresh()`), így minden rekord ismét megjelenik. A tulajdonos ezeket közvetlenül eltávolította; ezzel a fejlesztéssel nem töröltünk semmit a VPS-en.

## IMPORT-UX-01: a törlés szemantikája

**A tényleges függőségek** (MySQL `information_schema`, `0011`-es séma):

| Hivatkozó | Oszlop | Cél |
|---|---|---|
| `import_file_chunks` | `run_id` | `import_runs.id` |
| `import_rows` | `run_id` | `import_runs.id` |
| `import_changes` | `run_id` | `import_runs.id` |
| `product_events` | `run_id` | `import_runs.id` |
| `supplier_products` | `last_run_id` | `import_runs.id` |
| `import_runs` | `profile_id` | `import_profiles.id` (a profil megmarad) |

További, nem FK-alapú hivatkozások:
- az auditnapló (`audit_events.target`, szöveg);
- a termékek `source_attributes[*].run_id` értéke (JSON).

Feldolgozott import esetén ezek léteznek, és ezért az ilyen import nem törölhető.

**Törölhető** (első verzió):
- a `approved_by IS NULL`, és az állapot `uploaded` / `awaiting_approval` / `failed` / `cancelled`;
- nincs aktív lease (az elemzés nem fut);
- nincs `import_rows`, `import_changes`, `supplier_products.last_run_id` vagy `product_events.run_id` hivatkozás.

**Mi törlődik:**
- az `import_runs` sora (elemzéssel és beállításokkal együtt);
- a tárolt forrásfájl darabjai (`import_file_chunks`).

**Mi marad meg:**
- termékek, importprofilok, beszállítók;
- más importok;
- az auditnapló: új `import.delete` bejegyzés készül, a régiek megmaradnak.

Jóváhagyott vagy feldolgozott import nem törölhető (409). Ezeknél egy későbbi, külön jóváhagyott **archiválási** folyamat jöhet szóba; ez most nem készült el.

| Végpont | Jog | Válaszok |
|---|---|---|
| `GET /api/v1/imports/runs/{id}/deletion` | `imports.manage` | 200: próbafuttatás – `deletable`, `reason` (`approved_or_processed`, `running`, `referenced`), `deletes`, `references`, `keeps`. Nem módosít semmit. |
| `DELETE /api/v1/imports/runs/{id}` | `imports.manage` | 200 `{"deleted": true, "run_id": id}`; 409 + magyar indoklás; 404 (másik tenant, nem létező vagy már törölt rekord – **ismételt hívásra 404**); 403 (jog, CSRF, Origin); 401 |

További részletek:
- A törlés `SELECT … FOR UPDATE` alatt újraellenőriz, és egy tranzakcióban fut.
- Az importlista (`GET /runs`) additív `deletable` jelzést kap. Ez csak felületi tipp; a döntést a próbafuttatás és a DELETE hozza.
- A meglévő `DELETE /runs/{id}/source` változatlan, és továbbra is csak a forrásfájl megőrzési idejét kezeli.

## IMPORT-UX-02: számlálás, előnézet, mezőjavaslatok

- **Üres sor:** minden cellája whitespace (NBSP-t is beleértve) vagy láthatatlan karakter (zero-width, BOM). Ugyanez a szabály érvényes a számlálásra, az előnézetre és a feldolgozásra (`import_parser.blank_row`).
- **`analysis`:** `physical_rows` (a fejléc utáni sorok), `data_rows` (nem üres) és `empty_rows`. Az 50 000-es korlát továbbra is futásonként, a nem üres sorokra érvényes.
- **Forrás- és értelmezett előnézet:** az üres sorokat kihagyja. Az `offset` a nem üres sorokban számol, a `line` a fizikai sorszám marad. A `limit` 1–50 (alapértelmezés 25; a felület 5/10/25/50 közül választ, 10-zel indul). A válasz tartalmazza a sorszámokat. Az értelmezett cella formája `{value, raw, issues}`.
- **Sorlista** (`GET /runs/{id}/rows`): az üres sorokat csak számolja (`counters.empty`); listázni csak `include_empty=true` mellett lehet. A tárolt sorok és a forrásfájl változatlanok.
- **Pénzösszeg-mezők** (`purchase_price`, `list_price`, `price`, `sale_price`): a fejlécegyezés **csak javaslat** (`suggested_field`, `requires_decision: true`, `field: null`). A felület „Döntés szükséges” jelzést mutat, a mező nincs előre kiválasztva, és eladási árra nem következtetünk.
  - Aliasok: `LASTINITIALCOST`, `COST` → beszerzési ár-javaslat; `LISTPRICE` → listaár-javaslat. Az `Ár` csak `price` vagy `ár` fejlécre javasolt.
  - A pénzügyi jóváhagyás (`financial_approved`) továbbra is kötelező.
- **EAN/GTIN:** a tudományos jelölésű (`8,71999E+12`) vagy érvénytelen kód nem kerül a termék `gtin` mezőjébe. A nyers szöveg megmarad a sorban és a provenance-ban, és a sor jelzést kap (`gtin:scientific_identifier_requires_review`, `gtin:invalid_gtin`). Az oszlop figyelmeztetései: `scientific_notation_identifier`, `invalid_gtin_samples`.
- **Negatív készlet:** nyers forrásadatként megmarad, és jelzést kap (`stock:negative_value_requires_rule`, oszlopfigyelmeztetés: `negative_values`). Eladható pozitív készlet nem lesz belőle; az exportprofilok `negative_stock: zero` alapszabálya változatlan.

## Felület

Fájlgazda-kivétel: a Vezér #41 és #42 alatti döntése alapján a `frontend/src/ImportWorkspace.tsx`, a `frontend/src/style.css` import-osztályai és az import-böngészőtesztek ezen az ágon Claude-hoz tartoznak. A HELP-01 fájljait ez a munka nem érintette.

- **Importelőzmények:** kompakt táblázat (fájl, állapot, létrehozás, műveletek), oldalanként 25, tartománykijelzővel és üres állapottal. A hosszú fájlnév ellipszist és `title`-t kap. 650 px alatt kártyanézet jelenik meg.
- **Törlés:** csak ott jelenik meg, ahol a szerver jelzése `deletable`. A megerősítés a szerver próbafuttatását mutatja. A „törölve” üzenet csak akkor jelenik meg, ha a szerverről újraolvasott lista már nem tartalmazza a rekordot.
- **`awaiting_approval`:** a Megszakítás a valódi `/actions/cancel` végpontot hívja (`imports.cancel`).
- **Előnézet és sorok:** kompakt, megfeleltetett mezőnkénti táblázat, problémacímkékkel. A nyers cellák és a JSON csak az összecsukott „Technikai részletek” alatt láthatók. Lépéslinkek vezetnek a jóváhagyáshoz.

## Tesztek

- `backend/tests/test_import_ux.py` (API, SQLite):
  - rekonstruált minta: számok, 3 soros előnézet, lapméretek;
  - pénzösszeg-javaslatok;
  - EAN és negatív készlet, feldolgozás után is;
  - láthatatlan karakterek;
  - törlés: valódi, és új feltöltés után sem tér vissza;
  - megszakítás `awaiting_approval` állapotban, majd törlés;
  - feldolgozott import, futó és hivatkozott import (409);
  - másik tenant (404), reviewer (403), hiányzó CSRF (403), idegen Origin (403), kijelentkezve (401).
- `backend/tests/test_import_ux_browser.py` (FastAPI és Chromium, 1440 és 390 px): az Import → Előkészítés / Sablonkészítés megőrzi az összes forrásoszlopot, a korábban feltöltött fájlokat és azok lapozását. A beszerzési ár nem kerül automatikusan eladási árhoz.
- A korábbi jóváhagyás, feldolgozás és törlés regresszióit az API-tesztek ellenőrzik. Ezek a műveletek a sablonkészítő képernyőről nem indíthatók.


## Tulajdonosi döntések (2026-11-17)

| Kérdés | Döntés | Megvalósítás |
|---|---|---|
| `LASTINITIALCOST` és `LISTPRICE` | a `LASTINITIALCOST` az **utolsó beszerzési ár**; a `LISTPRICE` a **listaár**, mindig **nettó** és mindig **HUF** | A pontosan így nevezett fejlécek előre kiválasztva: `purchase_price`, illetve `list_price` (`method: owner_confirmed`, `meaning`). A `LISTPRICE` mellé `confirmed_context` kerül (`tax_basis: nettó`, `currency: HUF`), ami csak az üres pénzügyi alapértékeket tölti elő. **A pénzügyi jóváhagyás továbbra is kötelező** (nélküle 422). Más pénzösszeg-fejléc (`COST`, `PRICE`, `SALE_PRICE` …) továbbra is csak „Döntés szükséges” javaslatot kap, az Ár mezőre semmi nem kerül automatikusan. |
| negatív `QUANTITY` | egyelőre marad, ahogy van | Nincs változás: nyers forrásadat, `negative_value_requires_rule` jelzéssel; az exportprofilok `negative_stock: zero` szabálya érvényes. |
| tudományos jelölésű `BARCODE` | a forrás-Excelben számként vagy szövegként kell formázni | A figyelmeztetés javítási útmutatót tartalmaz: az oszlopot Szám (0 tizedesjegy) vagy Szöveg formátumra kell állítani, majd újra feltölteni. A sérült kód továbbra sem kerül be EAN-ként. |
| archiválás | nem kell | Nincs archiválás. A jóváhagyott vagy feldolgozott import nem törölhető (409). |

Továbbra is nyitott: a reprodukció megismétlése az eredeti `besz_minta.csv`-vel. A rekonstrukció a hibajegy tényein alapul.
