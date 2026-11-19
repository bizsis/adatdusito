# TEMPLATE-PREP-01 – Webshopmotor-alapú sablonkészítés (API-szerződés)

Kiinduló commit: `c925419`, ág: `claude/template-preparation-backend`. Backend: Claude.
Frontend: Codex. A szerződés a backend megvalósítása **előtt** készült, a frontend erre
építhet.

Hatókör: kizárólag az **Import → Előkészítés → Sablonkészítés** fázis. A folyamat a sablon
mentésével ér véget. eMAG-paraméterkeresés, AI-dúsítás és UNAS-export nem tartozik ide. Az
eMAG- és AI-folyamat változatlan.

## Alapelvek

- **Nincs migráció.** A sablon a meglévő, beszállítónként verziózott `import_profiles` sor
  (`config.template`). Egy beszállítónak több, név szerint különböző sablonja lehet, és
  mindegyiknek több verziója.
- **A sablonmentés nem indít termékfeldolgozást.** Az import jóváhagyását nem érinti, és a
  `config.automatic` mindig `false`.
- **Minden forrásoszlop és eredeti érték megmarad.**
  - A „Nem használjuk” állapotot csak a kezelő választhatja; a rendszer önállóan soha.
  - A fel nem használt oszlopok forrásattribútumként megmaradnak, mint eddig.
- **Az EAN/GTIN szöveg.** Tudományos jelölésből a rendszer nem talál ki számjegyet; az ilyen
  érték figyelmeztetést kap.
- **Nincs automatikus devizaátváltás**, és **nincs fiktív ár.**
- Minden módosító kérés a szokásos `X-CSRF-Token` és `Origin` védelemmel működik, minden válasz
  `no-store`, ügyfélhez (tenanthoz) kötött, és auditált. Más ügyfél erőforrására 404 a válasz.
- A hibák formátuma `{"error": {"code", "message", ...}}`; a `message` mindig magyar szöveg.
- A `pinfo_db`-t semmi nem éri el.

Előtag: `/api/v1/imports`. Jogosultságok: olvasás `imports.read`, feltöltés
`imports.create`, sablonmentés `imports.approve`.

## 1. Célmezők és pénznemek – `GET /template-targets?engine=unas`

A célmezők listája rögzített; a kezelői elnevezéseket a Tulajdonos határozta meg. A
`unas_header` a belső UNAS-technikai fejléc, a meglévő sémából (`backend/app/unas_schema.py`).
Az `evidence` mutatja, milyen alapon:

- `unas_schema`: a sémában szereplő szabványoszlop;
- `export_sample`: a valós UNAS-exportban látott oszlop;
- `unverified`: a fejléc feltételezés, megerősítésre vár (lásd *Nyitott kérdések*);
- `none`: nincs UNAS-exportoszlop.

```json
{
  "engine": {"key": "unas", "name": "UNAS"},
  "engines": [{"key": "unas", "name": "UNAS"}],
  "currencies": ["HUF", "EUR", "USD", "GBP", "CHF", "CZK", "PLN", "RON", "BGN", "RSD", "UAH"],
  "default_currency": "HUF",
  "defaults": {"statusz": "1", "afa": "27"},
  "targets": [
    {"key": "cikkszam", "label": "Cikkszám", "required": true, "multiple": null,
     "unas_header": "Cikkszám", "evidence": "unas_schema", "type": "text",
     "group": "identity", "default": null}
  ]
}
```

A `multiple` értéke:

- `null`: egy célmezőhöz egy oszlop;
- `"instances"`: többszörözhető, minden példány külön oszlopot kap;
- `"ordered"`: több forrásoszlop sorrendben (csak a Kép).

A `type` értéke `text`, `number`, `price`, `percent`, `date`, `integer`, `flag` vagy
`html`.

| `key` | Kezelői név | `multiple` | `unas_header` | `evidence` |
|---|---|---|---|---|
| `cikkszam` | Cikkszám * | – | `Cikkszám` | unas_schema |
| `termek_megnevezes` | Termék megnevezés | – | `Termék Név` | unas_schema |
| `kategoria` | Kategória | – | `Kategória` | unas_schema |
| `alternativ_kategoria` | Alternatív kategória | instances (1…) | `Alternatív Kategória {n}` | unas_schema |
| `gyarto` | Gyártó | – | `Paraméter: Márka\|\|enum\|0\|0\|0\|0\|0\|0\|\|\|0\|1\|1` | export_sample |
| `raktarkeszlet` | Raktárkészlet #0 | instances (0…) | #0: `Raktárkészlet`; #n: `Raktárkészlet #{n}` | #0 unas_schema, #n unverified |
| `netto_ar` | Nettó ár | – | `Nettó Ár` | unas_schema |
| `brutto_ar` | Bruttó ár | – | `Bruttó Ár` | unas_schema |
| `netto_akcios_ar` | Nettó akciós ár | – | `Akciós Nettó Ár` | unas_schema |
| `brutto_akcios_ar` | Bruttó akciós ár | – | `Akciós Bruttó Ár` | unas_schema |
| `akcio_kezdete` | Akció kezdete | – | `Akció Kezdet` | unas_schema |
| `akcio_vege` | Akció vége | – | `Akció Lejárat` | unas_schema |
| `afa` | ÁFA | – | `null` | none (nem exportált; árszámításhoz) |
| `ean` | EAN | – | `Paraméter: EAN\|\|text\|1\|0\|0\|0\|0\|0\|\|\|0\|1\|1` | export_sample |
| `gyartoi_cikkszam` | Gyártói cikkszám | – | `Paraméter: Gyártói cikkszám\|\|text\|1\|0\|1\|0\|0\|0\|\|\|0\|1\|1` | unverified |
| `reszletes_leiras` | Részletes leírás | – | `Tulajdonságok` | unas_schema |
| `rovid_leiras` | Rövid leírás | – | `Rövid Leírás` | unas_schema |
| `mennyisegi_egyseg` | Mennyiségi egység | – | `Egység` | unas_schema |
| `masodlagos_egyseg` | Másodlagos egység | – | `Másodlagos egység` | unas_schema |
| `masodlagos_mennyiseg` | Másodlagos mennyiség | – | `Másodlagos egység váltószám` | unas_schema |
| `min_rendelheto` | Min. rendelhető mennyiség | – | `Min. Menny.` | unas_schema |
| `lepeskoz` | Lépésköz | – | `Lépésköz` | unas_schema |
| `statusz` | Státusz | – | `Státusz` | unas_schema (alapérték 1) |
| `tomeg` | Tömeg | – | `Tömeg` | unas_schema |
| `osszevonas_alapja` | Termék összevonás alapja | – | `Alap Típus` | unverified |
| `export_tiltas` | Export tiltás | – | `Export Tiltás` | unas_schema |
| `kep` | Kép | ordered | `Kép link` | unas_schema |
| `lapful_1` | További lapfül 1 | – | `További lapfül tartalma 1` | unas_schema |
| `lapful_2` | További lapfül 2 | – | `További lapfül tartalma 2` | unas_schema |
| `lapful_3` | További lapfül 3 | – | `További lapfül tartalma 3` | unas_schema |
| `kiegeszito_termekek` | Kiegészítő termékek | – | `Kiegészítő Termékek` | unas_schema |
| `hasonlo_termekek` | Hasonló termékek | – | `Hasonló Termékek` | unas_schema |
| `parameter` | Paraméter | instances (paraméterenként) | `Paraméter: <név>\|<csoport>\|<típus>\|…` | unas_schema (formátum) |

A Paraméter fejlécét a szerver állítja elő az UNAS paraméterfejléc-formátumban.

> **TEMPLATE-FIX-02 (végleges szabály):**
> - A fenti 33 célmező változatlanul az első 33 helyen marad. Utánuk következik minden
>   dokumentált, importálható UNAS-oszlop: 44 egyszerű és 7 számozott családos, összesen 84.
>   A számozott családok sorszáma csak a valós exportban látott tartományban
>   (`min_instance`…`max_instance`) választható.
> - Paraméterhez **csak név** kell. A `Paraméter:` előtag nem duplázódik, és az előtagos
>   forrásoszlop automatikusan paraméter.
> - A megjelenített név `Paraméter: Név` (`label`). Az exportfejléc a dokumentált teljes UNAS-
>   formátum marad.
> - Új mező: `occupied`.
>
> Részletek: `docs/design/TEMPLATE-FIX-02-API.md`.

## 2. Fájlfeltöltés – `POST /runs` (meglévő, bővítve)

- A meglévő végpont mostantól a **CSV, XLS, XLSX és XML** fájlokat is elfogadja.
- A kódolást, az elválasztót, a fejlécsort és a munkalapot a rendszer magától felismeri:
  - a munkalapnál az első olyat választja, amelyben adat van;
  - XML-nél a rekordelem a leggyakrabban ismétlődő összetett elem.
- XML-ben:
  - minden rekord egy sor;
  - az oszlopok a rekordon belüli levélelemek útvonalai (pl. `ar/netto`) és az attribútumok
    (`@id`);
  - ugyanazon útvonal ismétlése külön oszlop (`kep`, `kep #2`, …), így semmi nem vész el.
- **XML-biztonság:** `DOCTYPE`/`ENTITY` deklarációt tartalmazó fájl elutasítva (422), külső
  erőforrás betöltése nincs.
- **XLS és XLSX:**
  - a képletet a rendszer nem futtatja;
  - a numerikus cella szövegként jön át;
  - a 15 számjegynél hosszabb vagy tudományos formátumú számcella bizonytalannak jelölt.
- Az elemzés után a futás `awaiting_approval` állapotú, mint eddig. A sablonkészítés innen
  indul.

### Elemzésre korlátozott feltöltés (sablonkészítéshez)

A sablonkészítés feltöltése **`purpose=template`** form-mezővel megy (a
`multipart/form-data` kérés `supplier_id` és `file` mezője mellett). Alapértéke `import`,
ami a régi működés, változatlanul. Más érték: 422.

- A futás `config.analysis_only: true` jelzőt kap, és a futás válaszában
  `"analysis_only": true` szerepel.
- Csak elemzés történik: minden oszlop és minta elérhető a 3. pont szerint.
- **Automatikus importprofil sem indít feldolgozást**, akkor sem, ha az oszlopszerkezet
  egyezik.
- A `POST /runs/{id}/approve` 409-et ad. Ebből a futásból termékimport nem indítható; importhoz
  a fájlt újra kell tölteni `purpose=import`-tal.
- Az újraelemzés (`PUT /runs/{id}/settings`) megtartja a jelzőt. A `settings` mezőn át a jelző
  nem állítható és nem törölhető.
- Sem a feltöltés, sem a sablonmentés nem hoz létre termékrekordot.

## 3. Előkészítési nézet – `GET /runs/{id}/template-preparation?engine=unas&currency=HUF&template_id=`

A fájl **összes** oszlopa fájlsorrendben, oszloponként **1 valós mintaértékkel**, a
felismert sablonnal együtt.

```json
{
  "run_id": 12, "supplier_id": 3, "engine": "unas", "currency": "HUF",
  "file": {"format": "xlsx", "sheet": "Termékek", "sheets": ["Üres", "Termékek"],
           "encoding": null, "delimiter": null, "header_line": 1, "record_path": null,
           "data_rows": 3, "source_available": true},
  "columns": [
    {"index": 0, "header": "SKU", "occurrence": 1, "sample": "A-1",
     "sample_source": "file", "empty": false, "warnings": [],
     "suggestion": {"target": {"key": "cikkszam"}, "confidence": 0.95,
                    "method": "synonym"},
     "assignment": {"state": "mapped", "target": {"key": "cikkszam"}},
     "assignment_source": "auto", "status": "suggested"},
    {"index": 4, "header": "Color", "occurrence": 1, "sample": "Fekete",
     "sample_source": "file", "empty": false, "warnings": [],
     "suggestion": {"target": {"key": "parameter",
                               "parameter": {"name": "Szín", "param_type": "text",
                                             "group_name": "", "unit": null}},
                    "confidence": 0.7, "method": "new_parameter"},
     "assignment": null, "assignment_source": null, "status": "unmapped"}
  ],
  "template": {"id": 41, "name": "Alap", "version": 3, "score": 0.86,
               "missing_headers": ["Old col"], "new_headers": ["Unknown_02"]},
  "template_candidates": [{"id": 41, "name": "Alap", "version": 3, "score": 0.86},
                          {"id": 44, "name": "Akciós", "version": 1, "score": 0.4}],
  "approved_parameters": [{"name": "Szín", "header": "Paraméter: Szín||text|…"}],
  "defaults": {"statusz": "1", "afa": "27"},
  "warnings": [{"code": "currency_mismatch", "columns": [6], "values": ["EUR"]}]
}
```

**Az `assignment` mezők**

- `state` lehet:
  - `"mapped"`: célmezőhöz rendelve;
  - `"unused"`: Nem használjuk;
  - `null`: nincs döntés, de az adat megmarad.
- `assignment_source` lehet:
  - `"template"`: a betöltött sablonból;
  - `"auto"`: biztos felismerés;
  - `null`.
- Automatikus hozzárendelés csak akkor jár, ha a felismerés legalább 0.9 bizonyosságú, és a
  cél **nem ár** és **nem új paraméter**.
- Ár és új paraméter mindig csak javaslat (`suggestion`), azt a kezelő veszi át.
- A rendszer `"unused"` állapotot soha nem ad.

**A `status` mező**

- `from_template`: változatlan a sablonhoz képest;
- `new`: új oszlop a sablonhoz képest;
- `suggested`: automatikus hozzárendelés;
- `unmapped`: nincs döntés.

Felülvizsgálatot csak a `new` és a `missing_headers` igényel; ez a „csak a változott
részek” elv.

**Mintaérték**

- Az első nem üres érték, szó szerint.
- Ha a forrásfájl már törölve van (régi import), a `sample_source` értéke `"analysis"`, és az
  érték az elemzéskor eltárolt mintából jön.
- Ha a teljes oszlop üres: `sample: null`, `empty: true`.

**A `suggestion.method` értékei**

| `method` | Alapja | Bizonyosság |
|---|---|---|
| `exact` | a fejléc azonos a célmező nevével vagy UNAS-fejlécével | 1.0 |
| `synonym` | szinonima | 0.95 |
| `approved_parameter` | korábban jóváhagyott paraméter | 0.9 |
| `content` | mintaérték alapján: 8/12/13/14 számjegy → EAN; kép URL → Kép; 0/1 → Státusz; 0/5/18/27(%) → ÁFA | 0.65–0.8 |
| `new_parameter` | ismeretlen oszlop → új paraméterjavaslat (rögzített szótár, pl. `Color` → Szín, vagy a fejléc neve) | 0.4–0.7 |

**Árak**

- Beszerzési árnak tűnő oszlop (`cost`, `lastinitialcost`, `beszerzési ár`, …) **soha** nem kap
  eladásiár-javaslatot.
- Ha a kezelő mégis eladási árhoz rendeli, a validáció `purchase_price_as_sale_price`
  figyelmeztetést ad.

**Oszlopszintű figyelmeztetések (`warnings`):** `scientific_notation_identifier`,
`uncertain_excel_number`, `invalid_gtin_samples`, `duplicate_header`.

**Nézetszintű figyelmeztetés:** `currency_mismatch`. Akkor jön, ha egy pénznemkódokat
tartalmazó oszlopban a sablon pénzneme helyett más érték is szerepel. Átváltás nincs.

**Sablonfelismerés**

- A `template` mező a beszállító sablonjai közül (mindegyik név legfrissebb verziója) az
  oszlopszerkezetben legjobban egyező, ha az egyezés legalább 0.5. Ezt a nézet automatikusan
  betölti.
- Pontszám: azonos fejlécek / összes fejléc (Jaccard).
- `template_id` megadásával más sablon (vagy egy régebbi verzió) tölthető be.
- `template_id=0`: sablon nélküli nézet.

## 4. Ellenőrzés – `POST /runs/{id}/template-preparation/validate`

Mentés nélkül ellenőriz. A törzs azonos az 5. pontéval, `name` nélkül.

```json
{
  "engine": "unas", "currency": "HUF",
  "columns": [
    {"index": 0, "state": "mapped", "target": {"key": "cikkszam"}},
    {"index": 1, "state": "unused"},
    {"index": 2, "state": null},
    {"index": 3, "state": "mapped", "target": {"key": "kep", "order": 1}},
    {"index": 4, "state": "mapped",
     "target": {"key": "parameter", "parameter": {"name": "Szín", "param_type": "text",
                                                   "group_name": "", "unit": null}}},
    {"index": 5, "state": "mapped", "target": {"key": "raktarkeszlet", "instance": 0}}
  ],
  "new_parameters": [{"name": "Szín", "param_type": "text", "group_name": "",
                      "unit": null, "approved": true}],
  "defaults": {"statusz": "1", "afa": "27"}
}
```

**Kéréskor:**

- A `columns` **minden** oszlopot tartalmaz; ha egy hiányzik: `missing_columns` hiba.
- Az `instance` (Alternatív kategória: 1-től, Raktárkészlet: 0-tól) és az `order` (Kép:
  1-től) elhagyható. Ilyenkor a szerver oszlopsorrendben osztja ki.
- A `defaults.statusz` értéke `0` vagy `1`. A `defaults.afa` értéke `0`, `5`, `18` vagy `27`;
  ha nincs ÁFA-oszlop, vagy a cellája üres, ezzel számol.

Válasz:

```json
{
  "valid": true,
  "errors": [],
  "warnings": [{"code": "price_missing"}],
  "fields": [
    {"key": "statusz", "status": "default", "value": "1"},
    {"key": "afa", "status": "default", "value": "27"},
    {"key": "brutto_ar", "status": "computed", "rule": "gross_from_net_vat"},
    {"key": "netto_akcios_ar", "status": "empty"}
  ],
  "price_missing": true,
  "parameters_to_create": [{"name": "Szín", "header": "Paraméter: Szín||text|…"}],
  "resolved": [{"index": 3, "target": {"key": "kep", "order": 1},
                "unas_header": "Kép link"}]
}
```

**Hibák**

| `code` | Jelentés |
|---|---|
| `missing_columns` | nincs minden oszlop a kérésben |
| `unknown_target` | a célmező nincs a listában |
| `duplicate_target` | nem többszörözhető célmező több oszlopon, vagy azonos példány/paraméter/képsorszám kétszer |
| `parameter_not_approved` | a paraméter se nem jóváhagyott, se nem szerepel a `new_parameters` között `approved: true` értékkel |
| `invalid_parameter` | hibás paraméternév, típus vagy mértékegység |
| `cikkszam_required` | a Cikkszám nincs hozzárendelve |
| `invalid_default` | hibás Státusz- vagy ÁFA-alapérték |
| `unsupported_currency` | a pénznem nincs a listában |
| `unsupported_engine` | a webshopmotor nem támogatott |

**Figyelmeztetések**

| `code` | Jelentés |
|---|---|
| `price_missing` | nincs eladási ár (sem nettó, sem bruttó); a sablon menthető, a hiány a későbbi feldolgozás számára jelölve |
| `price_rows_missing` | `count` sorban üres az ár (fájl alapján) |
| `purchase_price_as_sale_price` | beszerzési árnak tűnő oszlop eladási árként |
| `currency_mismatch` | lásd a 3. pontot |
| `invalid_vat_rows` | értelmezhetetlen ÁFA-érték (`count`); ezekben a sorokban nincs számított ár |
| `scientific_identifier_rows` | tudományos jelölésű EAN (`count`) |
| `undecided_columns` | `columns`: döntés nélküli oszlopok; az adat megmarad |

**`fields[].status`:**

- `mapped`: van forrásoszlop;
- `default`: alapérték (Státusz 1, ÁFA 27); üres cellánál is az alapérték érvényes;
- `computed`: nettó és bruttó egymásból számolható ismert ÁFA alapján, normál és akciós
  árra is; `rule` értéke `gross_from_net_vat` vagy `net_from_gross_vat`;
- `missing`: csak eladási árnál;
- `empty`: opcionális, hozzárendelés nélkül üres; ide tartoznak az akciódátumok is.

## 5. Sablon mentése – `POST /import-templates`

```json
{"run_id": 12, "name": "Alap", "template_id": 41, "engine": "unas", "currency": "HUF",
 "columns": [...], "new_parameters": [...], "defaults": {"statusz": "1", "afa": "27"}}
```

- Csak `valid` állapot menthető. Egyébként 422, a hiba mellett `error.validation` a 4. pont
  válasza.
- Ha a `template_id` meg van adva, ugyanannak a sablonnak **új verziója** jön létre; a név
  változhat, a sablon azonosítója (`template_key`) ugyanaz marad. Ha nincs megadva, új sablon
  jön létre. Azonos névvel két különböző sablon nem lehet egy beszállítónál (`409
  template_name_taken`).
- A régi verziók változatlanul megmaradnak.
- A mentés **csak kezelői művelet**: nincs külön összesítő képernyő, és nem indít
  termékfeldolgozást. Az import jóváhagyását sem érinti.
- Válasz:
  `{"id", "template_key", "name", "version", "price_missing", "validation"}`.
- Audit: `import.template_saved` és minden új paraméterre `import.parameter_approved`.

**Tárolás** (`import_profiles.config.template`): `engine`, `currency`, `columns`, `defaults`,
`parameters`, `price_missing`, `source`, `template_key`.

- A `columns` mezőben minden oszlop szerepel: `header`, `occurrence`, `sample`, `state`,
  `target`, `unas_header`.
- A `parameters` a jóváhagyott paraméterek listája `approved_by` és `approved_at` értékkel.
- A `source` rögzíti: `run_id`, `format`, `headers`.
- A meglévő importmotor kompatibilitása miatt a `config.mapping` (belső megfeleltetés) és a
  `config.analysis` is mentődik, `automatic: false` értékkel.

## 6. Sablonok – `GET /suppliers/{id}/import-templates`, `GET /import-templates/{id}`

- **Lista:** beszállítónként a sablonok legfrissebb verziója:
  `[{"id", "template_key", "name", "version", "versions", "engine", "currency",
  "columns": <darab>, "price_missing", "created_at", "approved_by"}]`.
- **Örökölt profilok:** a korábbi importprofilok és az IMPORT-MAP-01 megfeleltetések
  `"legacy": [{"id", "name", "version", "kind": "import_profile" | "engine_mapping"}]`
  formában, változatlanul.
- **Részletek:** `GET /import-templates/{id}` egy verzió teljes adata. A
  `GET /import-templates/{id}/versions` az adott sablon minden verziója.

## Kapcsolat a korábbi folyamatokkal

- A meglévő importvégpontok változatlanok. Az IMPORT-MAP-01 végpontok (`/column-mapping`,
  `/donor-*`) továbbra is működnek, de ebbe a folyamatba nem tartoznak.
- A régi importok forrásoszlopai az előkészítési nézetből visszanyerhetők akkor is, ha a
  forrásfájl már lejárt (`sample_source: "analysis"`).
- A sablonmentés egyetlen terméket sem dolgoz fel újra.

## Nyitott kérdések (Tulajdonos/Vezér)

1. **Raktárkészlet #1…:** a valós UNAS-exportban csak `Raktárkészlet` szerepel. A
   többraktáras fejléc formátuma (`Raktárkészlet #1`?) megerősítést igényel (`unverified`).
2. **Termék összevonás alapja:** `Alap Típus` feltételezés (`unverified`).
3. **Gyártói cikkszám:** nincs UNAS-szabványoszlop. Paraméterként javasolt (`unverified`).
4. **Kép:** a több képoszlop sorrendje mentődik. Az UNAS-export összefűzési szabálya
   (elválasztó vagy több oszlop) az exportfázis kérdése.

## A frontend teendői (Codex)

- **1. lépés:** beszállító kiválasztása vagy létrehozása, webshopmotor (UNAS) és pénznem
  (alapból HUF), majd fájlfeltöltés **`purpose=template`** mezővel. Így az automatikus
  importprofillal rendelkező beszállítók is használhatók; a frontend ideiglenes
  feltöltés-tiltása elhagyható.
- **2. lépés:** egyetlen táblázat, oszloponként:
  - forrásnév és mintaérték;
  - célmező-választó: a rögzített lista, a „Nem használjuk” és az „Új paraméter”;
  - javaslat átvétele gombbal.
- **Többszörözhető célmezők:** az Alternatív kategória, a Raktárkészlet és a Paraméter több
  oszlophoz is választható. A Kép több oszlopot fogad, a sorrendjük módosítható.
- **Alapértékek:** a Státusz és az ÁFA alapértéke szerkeszthető (1 és 27%).
- **Pénznem:** eltérés esetén figyelmeztetés jelenik meg.
- **Betöltött sablon:** csak a `new` oszlopok és a `missing_headers` jelölése szükséges.
- **Mentés:** a „Sablon mentése” gomb a 4. ponti validáció után, külön összesítő képernyő
  nélkül. Sikeres mentés után a folyamat lezárul.
