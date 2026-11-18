# IMPORT-MAP-01 – Webshopmotor-alapú oszlopmegfeleltetés és eMAG-paraméterdiff (API-szerződés)

GitHub #58. Kiinduló ág: `codex/release-candidate-04` (`2f2d52b`). Backend: Claude
(`claude/issue-58-backend`). Frontend: Codex (a kijelölt fájlgazda szerint).

A szerződés **előbb készült, mint a backend**. A frontend erre építhet. Minden itt leírt
végpont új. A meglévő `/api/v1/imports` végpontok és válaszmezők **változatlanok**; a
`PUT /engines/{key}` és a `POST /runs/{id}/approve` csak opcionális mezőkkel bővül.

## Alapelvek

- **Nincs új adatmodell és nincs migráció** (sorszám nem lett kiosztva):
  - a webshopmotor-nyilvántartás a meglévő `store_engines` sor (`unas`);
  - a mentett megfeleltetés a meglévő, beszállítónként verziózott `import_profiles` sor;
  - a futásszintű kijelölés az `import_runs.config`-ban él.
- **Nincs AI, nincs kredit, nincs hálózat.** Minden javaslat determinisztikus: név,
  szinonima vagy adatminta alapján, megadott bizonyossággal.
- **A `pinfo_db`-t semmi nem érinti.** A donorparaméterek az alkalmazás-adatbázisban lévő aktív
  közös katalógusból jönnek, ugyanonnan, ahonnan a CATEGORY-03A is olvas.
- **Minden oszlop megmarad.** Nincs rejtett „nem használjuk” állapot: a meg nem feleltetett
  oszlop `target: null` és forrásattribútumként tárolódik, mint eddig is
  (`supplier_products.source_attributes`).
- **Paraméter csak a kezelő jóváhagyásával jön létre.** A gép legfeljebb
  `new_parameter` javaslatot ad; mentéskor csak a kifejezetten jóváhagyott új paraméter
  érvényes.
- **A forráskategória érintetlen.** Az eMAG-kategória csak donor a hiányzó paraméterek
  kereséséhez, a forráskategóriát nem írja felül.
- **Meglévő értéket semmi nem ír át.** Árat, nevet vagy cikkszámot a rendszer nem talál ki.
- Minden módosító kérés a szokásos `X-CSRF-Token` és `Origin` védelemmel működik, minden válasz
  `no-store`, a döntések auditnaplóba kerülnek. A hibák formátuma a megszokott
  `{"error": {"code", "message"}}` (a `message` magyar szöveg).

Előtag: `/api/v1/imports`. Jogosultságok: olvasás `imports.read`, mentés
`imports.approve`, donorkijelölés `imports.manage`, nyilvántartás-szerkesztés
`exports.fields.manage`.

## A) Webshopmotor és oszlopmegfeleltetés

### A1. Központi mezőjegyzék – `GET /engines/{key}/registry`

A webshopmotor (első: `unas`) központi mezőlistája, amely minden ügyfélnél azonos. Ha az
adminisztrátor még nem mentett saját listát (`store_engines.fields` üres), a beépített UNAS-
alaplista jön (`source: "default"`), adatbázisírás nélkül.

```json
{
  "engine_key": "unas", "name": "UNAS", "version": 0, "source": "default",
  "fields": [
    {"key": "cikkszam", "kind": "standard", "header": "Cikkszám", "label": "Cikkszám",
     "group": "identity", "type": "text", "required": true, "unas_required": true,
     "allowed": [], "synonyms": ["sku", "articlenr", "cikkszam", "article"],
     "internal_field": "sku", "parameter": null},
    {"key": "param_ean", "kind": "parameter",
     "header": "Paraméter: EAN||text|1|0|0|0|0|0|||0|1|1", "label": "EAN",
     "group": "parameter", "type": "text", "required": false, "unas_required": false,
     "allowed": [], "synonyms": ["ean", "gtin", "barcode", "vonalkod"],
     "internal_field": "gtin", "parameter": {"name": "EAN", "group_name": "",
                                              "param_type": "text", "unit": null}}
  ]
}
```

- `required`: a **mi rendszerünk** előírása, amit az admin szerkeszthet.
- `unas_required`: az UNAS technikai kötelezősége (tájékoztató).

A két érték szándékosan külön mező. Alapból kötelező: `Cikkszám`, `Termék Név`, `Kategória`,
`Nettó Ár`, `Bruttó Ár`, `Státusz`. A `type` értéke `text`, `number`, `date` vagy `boolean`,
ugyanaz, mint az export-profiloknál. A `kind: "auxiliary"` segédmező (alapból egy van:
`afakulcs`, „Áfakulcs (segédmező)”). Csak a hiányzó ár kiszámításához használható, mert az UNAS
nem tárol áfakulcsot, és nem exportálódik. Az `internal_field` a belső importmező (`/fields`), amire
a megfeleltetés a meglévő importmotor felé lefordul.

### A2. Nyilvántartás szerkesztése – `PUT /engines/{key}` (meglévő)

A meglévő végpont, amely ezeket az **opcionális** mezőket is elfogadja:
`header`, `kind` (`standard`/`parameter`/`auxiliary`), `group`, `synonyms` (legfeljebb 30 szöveg),
`unas_required` (bool), `parameter` (`{name, group_name, param_type, unit}`).

- A régi formátumú kérés változatlanul érvényes.
- Minden mentés új `version`, auditálva (`export.engine_version`).
- Ha a `kind: "parameter"` és nincs megadva `header`, a fejlécet a szerver állítja elő az UNAS
  paraméterfejléc-formátumban (`backend/app/unas_schema.py`).
- A `header` mezőnév egyedi.

### A3. Megfeleltetési nézet – `GET /runs/{id}/column-mapping?engine=unas`

A fájl **összes** oszlopa, fájlsorrendben. Akkor érhető el, ha az elemzés kész
(`awaiting_approval` vagy később); különben 409.

```json
{
  "run_id": 12, "engine_key": "unas", "engine_version": 3,
  "rows": {"physical_rows": 3, "data_rows": 3, "empty_rows": 0},
  "columns": [
    {"index": 0, "header": "SKU", "samples": ["A-1", "A-2", "A-3"], "filled": 3,
     "empty": 0, "warnings": [],
     "suggestion": {"target": {"kind": "field", "key": "cikkszam", "header": "Cikkszám"},
                    "confidence": 0.95, "method": "synonym"},
     "current": {"kind": "field", "key": "cikkszam", "header": "Cikkszám"},
     "current_source": "saved_profile"},
    {"index": 4, "header": "Color", "samples": ["Fekete"], "filled": 1, "empty": 2,
     "warnings": [],
     "suggestion": {"target": {"kind": "new_parameter", "header":
                               "Paraméter: Szín||text|1|0|1|0|0|0|||0|1|1",
                               "parameter": {"name": "Szín", "group_name": "",
                                             "param_type": "text", "unit": null}},
                    "confidence": 0.7, "method": "translation"},
     "current": null, "current_source": null},
    {"index": 5, "header": "Unknown_01", "samples": ["x"], "filled": 1, "empty": 2,
     "warnings": [], "suggestion": null, "current": null, "current_source": null}
  ],
  "approved_parameters": [{"header": "Paraméter: Szín||text|...", "name": "Szín",
                           "approved_by": 1, "approved_at": "...", "profile_id": 7}],
  "saved_profile": {"id": 7, "version": 2, "missing_headers": ["Old col"],
                    "new_headers": ["Unknown_01"], "requires_review": true}
}
```

- A `samples` legfeljebb 5 nem üres, **szöveges** érték, pontosan úgy, ahogy a fájlban van.
  Az EAN/Barcode számjegysora teljes. Tudományos jelölésnél (`8,71999E+12`) a minta
  változatlan, és figyelmeztetés kíséri (`scientific_notation_identifier`); hiányzó
  számjegyet a rendszer nem talál ki.
- A `warnings` lehetséges értékei: `scientific_notation_identifier`, `invalid_gtin_samples`,
  `negative_values`, `duplicate_header`.
- A `suggestion.target.kind` értéke `field` (szabványmező), `parameter` (már jóváhagyott
  vagy központi paraméter) vagy `new_parameter`. Az utóbbi csak javaslat: létrehozni a kezelő
  hozza létre, A4/A5 `new_parameters`.
- A `suggestion.method` lehetséges értékei:
  - `exact_header`: pontos egyezés (bizonyosság 1.0);
  - `synonym`: szinonima (0.95);
  - `approved_parameter`: korábban jóváhagyott paraméter (0.9);
  - `translation`: rögzített szótár, pl. `Color` → `Szín` (0.7);
    a szótár a kódban van (`backend/app/import_mapping.py`, `TRANSLATIONS`); admin felületről
    egyelőre nem szerkeszthető (tulajdonosi döntés, 2026-11-18);
  - `content`: adatminta, pl. 8/12/13/14 számjegyű kód → EAN (0.65).
- A `current` a beszállító legutóbbi mentett megfeleltetéséből jön, fejlécazonosság alapján
  (`current_source: "saved_profile"`).
- Ha a fájlban új vagy hiányzó fejléc van a mentetthez képest, a válaszban
  `saved_profile.requires_review: true` szerepel: célzott kezelői ellenőrzés kell.
- A sorszámláló a meglévő `analysis` értékeiből jön, és a fejléc alatti sorokat számolja. Egy
  4 soros (fejléc + 3 termék) CSV esetén `physical_rows: 3`, `data_rows: 3`, `empty_rows: 0`.

### A4. Ellenőrzés mentés nélkül – `POST /runs/{id}/column-mapping/validate`

Kérés (A5-tel azonos törzs, a `name` kivételével):

```json
{
  "engine_key": "unas",
  "columns": [
    {"index": 0, "target": {"kind": "field", "key": "cikkszam"}},
    {"index": 4, "target": {"kind": "parameter",
                             "header": "Paraméter: Szín||text|1|0|1|0|0|0|||0|1|1"}},
    {"index": 5, "target": null}
  ],
  "new_parameters": [{"name": "Szín", "param_type": "text", "group_name": "",
                      "unit": null, "approved": true}],
  "identity_target": "cikkszam",
  "financial_approved": false,
  "vat_rate": null
}
```

- A `columns` **minden** oszlopot tartalmaz, `target: null`-lal is. Ha egy oszlop hiányzik,
  `422 missing_columns`.
- A `vat_rate` csak akkor adható meg, ha a kezelő ismeri a beszállító egységes áfakulcsát
  (0, 5, 18 vagy 27). Ilyenkor ebből számolható a hiányzó Nettó vagy Bruttó ár.

Válasz:

```json
{
  "valid": false,
  "errors": [{"code": "duplicate_target", "columns": [0, 2], "target": "cikkszam"}],
  "warnings": [{"code": "invalid_vat_rows", "count": 1}],
  "required": [
    {"key": "statusz", "header": "Státusz", "status": "fallback", "rule": "default_1",
     "rows_missing": 0},
    {"key": "brutto_ar", "header": "Bruttó Ár", "status": "missing",
     "rule": null, "rows_missing": 3}
  ],
  "parameters_to_create": [{"name": "Szín", "header": "Paraméter: Szín||text|..."}],
  "import_mapping": {"0": "sku", "1": "name", "2": "gtin"},
  "approval_defaults": {"tax_basis": "nettó"}
}
```

Az `approval_defaults` a `/approve` kéréshez javasolt kiegészítő értékeket tartalmazza (pl.
`tax_basis`, ha ár is meg van feleltetve).

**Hibák:**

| `code` | Jelentés |
|---|---|
| `duplicate_target` | két oszlop ugyanarra a célmezőre vagy paraméterre mutat |
| `unknown_target` | a mező nincs a nyilvántartásban |
| `parameter_not_approved` | a paraméter se nem jóváhagyott, se nem szerepel a `new_parameters` között `approved: true` értékkel |
| `invalid_parameter` | hibás név, típus vagy mértékegység |
| `missing_columns` | nincs minden oszlop a kérésben |
| `identity_missing` | sem azonosító (Cikkszám/EAN), sem név nincs megfeleltetve |
| `identity_target_not_mapped` | az `identity_target` mező nincs megfeleltetve |
| `identity_conflict` | az azonosítóoszlopban ugyanaz az érték ismétlődik eltérő sorokban (`values`: legfeljebb 10 példa) |
| `financial_approval_required` | ár, áfa vagy pénznem megfeleltetéséhez `financial_approved: true` kell |
| `invalid_vat_rate` | a `vat_rate` nem 0, 5, 18 vagy 27 |

**Figyelmeztetések:** `invalid_vat_rows`,
`scientific_identifier_rows`, `invalid_gtin_rows`.

**Kötelező mezők** (`required[].status`):

- `mapped`: van oszlop, és minden sorban van érték.
- `partial`: van oszlop, de `rows_missing` sorból hiányzik az érték, és nincs megbízható pótlás.
- `fallback`: determinisztikus pótlás érvényes (`rule` mondja meg, melyik).
- `missing`: nincs oszlop és nincs szabály. Ez **validációs hiány**, nem kitalált érték.

**Pótlási szabályok** (`rule`):

| `rule` | Mező | Szabály |
|---|---|---|
| `default_1` | Státusz | Ha nincs oszlop: 1. A készletnek nincs köze a Státuszhoz (tulajdonosi döntés, 2026-11-18): 0 készletnél is 1, figyelmeztetés nélkül. |
| `from_availability` | Státusz | Ha van megfeleltetett elérhetőség/rendelhetőség oszlop, annak értékét kell figyelembe venni: az értelmezhető igen/nem érték 1/0 lesz, a többi sor `partial`. |
| `net_from_gross_vat` | Nettó Ár | Bruttó / (1 + áfa), csak ismert áfakulcsból (`vat_rate` vagy soronkénti áfaoszlop 0/5/18/27). |
| `gross_from_net_vat` | Bruttó Ár | Nettó × (1 + áfa), ugyanezzel a feltétellel. |

A Cikkszám, a Termék Név és a Kategória nem pótolható. A Kategória a forráskategória-oszlop;
ha nincs, `missing`, és a B1 referenciajavaslatot ad, de a forráskategóriát nem tölti ki.

Az `import_mapping` a meglévő `POST /runs/{id}/approve` `mapping` mezőjének megfelelő belső
megfeleltetés: `{oszlopindex: belső mező}`, a nyilvántartás `internal_field` értékéből. Ha
Nettó és Bruttó Ár is van, a Nettó lesz a belső `price` (`tax_basis: nettó`), a Bruttó pedig
forrásattribútumként megmarad, nem vész el.

### A5. Mentés – `POST /runs/{id}/column-mapping`

A törzs A4-gyel azonos, és kötelező mellette a `name` (1–120 karakter). Csak `valid` mapping
menthető; különben 422 a válasz: `{"error": {"code": "422", "message": "…",
"validation": <A4 válasz>}}`.

- Új `import_profiles` verzió jön létre beszállítónként és webshopmotoronként. A neve
  `"<name>"`, a `config.engine_mapping` pedig tartalmazza: `engine_key`, `engine_version`,
  `columns` (fejléc + cél), `parameters` (a jóváhagyott paraméterek `approved_by` és
  `approved_at` értékkel), `identity_target`, `vat_rate`.
- A korábbi verziók megmaradnak.
- Válasz: `{"profile_id", "version", "import_mapping", "approval_defaults", "validation"}`.
- Audit: `import.engine_mapping` és minden új paraméterre `import.parameter_approved`.

A meglévő `POST /runs/{id}/approve` elfogad egy opcionális `engine_mapping_profile_id`
mezőt. Ezt a futás `config`-ja megőrzi, így az import a mentett megfeleltetéshez kötött. A
jóváhagyás menete egyébként változatlan, a frontend az A5 `import_mapping` mezőjét küldi
`mapping`-ként.

### A6. Mentett verziók – `GET /suppliers/{id}/engine-mappings?engine=unas`

`[{"profile_id", "version", "name", "engine_version", "columns", "parameters",
"approved_by", "created_at"}]`, legújabb elöl. Új import esetén az A3 a legfrissebbet
ajánlja.

## B) eMAG donor és hiányzó paraméterek

### B1. Donorjavaslat – `GET /runs/{id}/donor-categories`

A futás termékeinek **forráskategóriája változatlanul** jelenik meg. Mellette a besorolásból
(CATEGORY-02A) származó donor-eMAG-kategóriák is szerepelnek, termékszámmal.

```json
{
  "source_categories": [{"source_category_id": 3, "path": "Háztartás|Mosógép",
                         "products": 2}],
  "products_without_source_category": 1,
  "donors": [{"emag_category_id": 2001, "name": "Mosógépek", "products": 2,
              "parameter_profile_state": "ready", "parameter_count": 41}],
  "reference_suggestions": [{"navigation_node_id": "…", "path": ["…"],
                             "emag_category_ids": [2001], "products": 1}]
}
```

A `reference_suggestions` a forráskategória nélküli termékekre ad javaslatot (név alapú
referencia-egyezés). Ez csak javaslat, és nem írja ki a forráskategóriát.

### B2. Teljes paraméterdiff – `GET /runs/{id}/donor-parameters?emag_category_id=2001`

A donorkategória **összes** paramétere, AI-szűrés nélkül, egyszer
(`emag_parameter_id` szerint deduplikálva), katalógussorrendben.

```json
{
  "emag_category_id": 2001, "catalog_version": 5, "total": 41,
  "missing": 37, "covered": 4, "selected": 2,
  "parameters": [
    {"emag_parameter_id": 6511, "name": "Szélesség (mm)", "label": "Szélesség",
     "unit": "mm", "mandatory": false, "is_filter": true, "display_order": 3,
     "status": "covered", "covered_by": {"column": 7, "header": "Width",
                                          "via": "parameter_label"},
     "selected": false},
    {"emag_parameter_id": 7001, "name": "Szín", "label": "Szín", "unit": null,
     "mandatory": true, "is_filter": true, "display_order": 1,
     "status": "missing", "covered_by": null, "selected": true}
  ],
  "previous_selection": [7001]
}
```

- `status: "covered"`: a paraméter már szerepel az oszlopok között, ezért nem jelenik meg
  hiányzóként. Lefedheti:
  - megfeleltetett UNAS-paraméter, azonos címkével;
  - jóváhagyott paraméteralias (CATEGORY-03A);
  - egy nem megfeleltetett forrásoszlop, azonos címkével (`via`: `parameter_label`, `alias`
    vagy `source_header`).
- Csak `missing` paraméter jelölhető ki.
- A `previous_selection` ugyanannak a beszállítónak az utolsó, ugyanerre a donorra mentett
  kijelölése. Ez csak javaslat, nincs alkalmazva.
- Ha nincs aktív katalógus: 503. Ha a donor ismeretlen: 404.

### B3. Kijelölés – `PUT /runs/{id}/donor-parameters/selection`

```json
{"emag_category_id": 2001, "mode": "set", "emag_parameter_ids": [7001, 7002]}
```

- A `mode` értéke:
  - `set`: pontosan a megadottak;
  - `all`: összes kijelölése, vagyis minden `missing`;
  - `none`: kijelölés törlése.
- `covered` vagy ismeretlen paraméter kijelölése: 422,
  `{"error": {"code": "422", "message": "…", "reason": "not_selectable",
  "emag_parameter_ids": [...]}}`.
- Válasz: a B2 nézet frissítve.
- Tárolás: `import_runs.config.donor_selection[<emag_category_id>]`
  `{parameter_ids, selected_by, selected_at}`. Audit: `import.donor_selection`.
- A kijelölés **semmilyen termékértéket nem ír**, és AI-kitöltést sem indít.

### B4. Előkészített mezők – `GET /runs/{id}/prepared-fields`

Az elfogadott oszlopmegfeleltetés és a kijelölt paraméterhelyek együtt. Ez lesz a későbbi
dúsítás bemenete:

```json
{"engine_key": "unas", "profile_id": 7,
 "fields": [{"source": "column", "column": 0, "target": "Cikkszám"},
            {"source": "column", "column": 4, "target": "Paraméter: Szín||text|..."}],
 "donor_parameters": [{"emag_category_id": 2001, "emag_parameter_id": 7002,
                       "name": "Anyag", "state": "selected_empty"}]}
```

## Átvételi kritériumok és tesztek

A kritériumokat a `backend/tests/test_import_mapping.py` ellenőrzi:

| # | Kritérium | Teszt |
|---|---|---|
| 1 | 4 soros CSV → `data_rows: 3`, teljes oszloplista | `test_four_line_csv_counts_three_products_and_lists_every_column` |
| 2 | EAN teljes számjegysor; tudományos jelölésnél nincs kitalált számjegy | `test_ean_digits_kept_and_scientific_notation_flagged` |
| 3 | `Color` → `Paraméter: Szín` csak kezelői elfogadással; `Unknown_01` látszik és kezelhető | `test_color_parameter_requires_operator_approval` |
| 4 | Forráskategória változatlan, donor külön | `test_source_category_unchanged_by_donor_selection` |
| 5 | Donor összes hiányzó paramétere, kijelölés egyenként, összes vagy törlés, nincs duplikáció és AI | `test_donor_parameter_diff_lists_all_missing_and_selection_modes` |
| 6 | Kötelező mezők, Státusz=1, rendelkezésre állás, áfából számolt ár, hiány hibaként | `test_required_fields_fallbacks_and_missing_price` |
| 7 | Mentett mapping újrahasználható, módosult oszlopok nem vesznek el | `test_saved_mapping_reused_and_changed_columns_kept` |

## A frontend teendői (Codex)

- **Egyetlen folyamat, két lépésben:** (A) megfeleltetés, (B) donorparaméterek.
- **A lépés:**
  - Minden oszlop sora látszik: fejléc, minták, javaslat a bizonyossággal, választható célmező
    (A1 mezőlista és a jóváhagyott paraméterek).
  - `new_parameter` javaslatnál az „Új paraméter létrehozása” párbeszéd: név, típus,
    mértékegység és kifejezett jóváhagyás. A párbeszéd a `new_parameters` mezőt tölti.
  - Validáció: A4. Mentés: A5. Ezután a meglévő jóváhagyás (`/approve`), az A5
    `import_mapping` és `engine_mapping_profile_id` mezőivel.
- **B lépés:**
  - Donorválasztás: B1.
  - Lista: B2, a `covered` sorok halványan és nem jelölhetően.
  - Jelölőnégyzetek, valamint **Összes kijelölése** és **Kijelölés törlése**: B3 (`all`/`none`).
- Hibaüzenet: a `message` megjelenítése; a gépi kódok listája A4-ben.
