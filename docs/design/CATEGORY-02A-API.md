# CATEGORY-02A – API/DTO-szerződés: saját kategória, belső besorolás, státusz

- **Státusz:** implementálva a `claude/category-02a-backend` ágon ([#16](https://github.com/bizsis/adatdusito/issues/16)).
- Ez a szerződés a frontend (Codex) számára **végleges útvonalakat** rögzít. A változtatás csak additív lehet, vagy a Vezér döntésével történhet.
- Kapcsolódó tervek: #14 (CATEGORY-01A), #15 (CATEGORY-01B). A munkanevekhez képesti eltérések a végén.

## Közös szabályok

- **Hitelesítés:** session-cookie, minden írásnál `X-CSRF-Token`, Origin-ellenőrzés, `Cache-Control: no-store`, ahogy eddig.
- **Tenant:** mindig a session kiválasztott munkaterülete (`tenant(who)`). Tenant-ID nem küldhető. Idegen vagy nem látható rekordra **404** a válasz.
- **Jogok:**

| Művelet | Jog |
|---|---|
| Olvasás (lista, részlet, saját kategóriák, belső kategóriák) | `products.read` |
| Besorolás módosítása, kategóriatérkép | **`products.classify`** (új) |
| Küszöb beállítása | `system.settings.manage` + friss újraazonosítás |

  - A `products.classify` alapból az ügyféladminisztrátoroknál (legacy `tenant_admin`) és a superadminnál van.
  - Más szerepkörhöz a szerepkör-szerkesztőben adható. A 0009 migráció felveszi a jogkatalógusba.
  - Ahogy minden `products.*` jogra, erre is érvényes, hogy csak teljes ügyfél-hozzáféréssel működik.
- **Hibák:** a meglévő `{"error": {"code", "message"}}` formátum.

| Kód | Jelentés |
|---|---|
| 401 | nincs érvényes munkamenet |
| 403 | nincs jog |
| 404 | idegen vagy nem létező rekord |
| **409** | elavult revízió: a kliens töltse újra a rekordot (`GET`), és mutassa az eltérést; nincs automatikus újrapróbálás |
| 422 | érvénytelen kategória vagy profil, illetve hiányzó mező |

- **A globális referencia-hozzárendelés** (`/api/v1/reference/navigation/{node}/assignment`) ügyféltermékre **nem** használható. Ezek a végpontok nem hívják.

## Fogalmak

| Mező | Jelentés |
|---|---|
| `source_category` | az ügyfél **saját** (beszállítói) kategóriája, változatlan szöveggel. A rendszer soha nem írja át. |
| `classification` | **belső** besorolás a jóváhagyott fix fa egy termékkategóriájára (`navigation_node_id`) |
| `donor_emag_category_id` | az eMAG-kategória, amely **csak a paraméterdefiníciókat** adja (stabil külső eMAG-ID) |
| `export_category` | `own`: saját kategória; ha nincs, `internal`: egyértelmű belső besorolás; különben `none` |
| `revision` | a termék optimista-zár verziója. Import, besorolás és visszaállítás is növeli. |

**Ügyféloldali állapot** (`status`, a felirat `status_label`-ben):

| `status` | `status_label` |
|---|---|
| `auto_classified` | Automatikusan besorolt |
| `needs_review` | Ellenőrzést igényel |

**Eredet** (`origin`), külön metaadatként:

| `origin` | Jelentés |
|---|---|
| `category_map` | jóváhagyott ügyfél-kategóriatérkép |
| `manual` | kézi döntés, zárolt |
| `suggestion` | gépi javaslat |
| `none` | nincs alap |

**Okok** (`reason_codes[]`):

| Kód | Jelentés |
|---|---|
| `approved_category_map` | a besorolás egy jóváhagyott kategóriatérképből jön |
| `manual_decision` | kézi döntés |
| `uncalibrated_suggestion` | van javaslat, de a módszer nincs kalibrálva |
| `ambiguous_candidates` | több jelölt is van |
| `no_candidate` | nincs jelölt |
| `no_source_category` | a terméknek nincs saját kategóriája |
| `category_map_rejected` | a kategóriatérképet elutasították |
| `category_map_target_unavailable` | a térkép célkategóriája már nem érhető el |
| `parameter_profile_choice_required` | a belső kategóriának több donorprofilja van, választani kell |
| `calibrated_rule` | kalibrált szabály döntött |
| `not_classified_yet` | még nincs besorolás |

A `confidence` csak kalibrált módszernél kap értéket, különben `null`. Kitalált százalék nincs.

## Végpontok

### `GET /api/v1/workspace/products`

A meglévő végpont, **visszafelé kompatibilis**: az `items[].fields`, `supplier_name`, `source_line`, valamint a `next_cursor` és a `field_labels` változatlan.

**Lekérdezési paraméterek** (mind opcionális, szerveroldali szűrés):

| Paraméter | Leírás |
|---|---|
| `cursor` | kulcskészletes lapozás `id` szerint |
| `limit` | 1–100, alapérték 25 |
| `status` | `auto_classified` / `needs_review` |
| `origin` | `category_map` / `manual` / `suggestion` / `none` |
| `locked` | bool |
| `supplier_id` | |
| `source_category_id` | |
| `without_source_category` | bool |
| `navigation_node_id` | |
| `q` | szerveroldali keresés, legfeljebb 120 karakter (lásd lent) |

**Keresés (`q`):**
- **Mezők:** terméknév (`fields.name`), beszállítói cikkszám (`fields.sku`) és EAN/GTIN (`fields.gtin`).
- **Egyezés:** részleges (a keresett szöveg bárhol szerepelhet), kis- és nagybetű-független, ékezet-független (pl. `televizio` megtalálja a `Televízió` terméket).
- **Normalizálás:** Unicode NFKD, a diakritikus jelek elhagyása, `casefold`, a szóközök összevonása, a vezérlőkarakterek eltávolítása.
- **Több szó:** a szóközzel elválasztott szavak (legfeljebb 5) mindegyikének szerepelnie kell, akár különböző mezőkben (ÉS-kapcsolat). Például `televízió 55` → név „Televízió 55 colos”.
- **Speciális karakterek:**
  - a `%`, `_`, `/`, `\`, `'` és `(` szó szerint értendő
  - az SQL-wildcardok escape-elve kerülnek a lekérdezésbe (`LIKE … ESCAPE`), és a lekérdezés paraméterezett
- Üres vagy csak szóközből álló `q` = nincs keresés. 120 karakternél hosszabb `q` → 422.
- A keresés minden más szűrővel, a `status_counts` értékkel és a kurzoros lapozással együtt működik. A lapok `id` szerint rendezettek, stabilak és ismétlésmentesek.
- **Tárolás és index:**
  - A keresés a `supplier_products.search_text` oszlopon fut (0009). Ez a hajtogatott „név⇥SKU⇥GTIN” szöveg, amelyet az import minden termékváltozáskor, a régi termékeknél pedig a `python -m app.product_backfill` tölt ki.
  - A szűrés teljesen az adatbázisban történik, Python-memóriába nem töltünk termékeket.
  - A lekérdezés a `tenant_id` indexen, `id` szerinti sorrendben halad, így csak az adott tenant sorait vizsgálja.
  - A részszöveges (`%…%`) egyezést B-fa index nem gyorsítja, ezért a költség a tenant termékszámával arányos. A `status_counts` miatt minden kérés a tenant összes egyező sorát megszámolja.
- **Mérés:** SQLite, 50 000 termék, egy tenant, `limit=25`. A medián válaszidő 26–43 ms volt: ritka és gyakori szónál, nem talált keresésnél és státuszszűrővel is.
  - **MySQL 8-on még nincs mérés, garancia nincs.**
  - Ha nagy tenantnál lassú, a következő lépés egy InnoDB `FULLTEXT … WITH PARSER ngram` index ugyanazon az oszlopon (külön migráció), vagy a `status_counts` opcionálissá tétele.
- A backfill lefutásáig a régi (0009 előtti) termékek keresésben nem jelennek meg, szűrőkkel és lapozással viszont igen.

**Válasz:**
```json
{
  "items": [ProductItem],
  "next_cursor": 123,
  "field_labels": {"sku": "Beszállítói cikkszám"},
  "status_counts": {"auto_classified": 10, "needs_review": 3},
  "status_labels": {"auto_classified": "Automatikusan besorolt", "needs_review": "Ellenőrzést igényel"}
}
```
A `status_counts` a többi szűrőt figyelembe veszi, a `status` szűrőt nem, így a fülek számlálói egyszerre megjeleníthetők.

**`ProductItem`:**
```json
{
  "id": 7, "revision": 3,
  "fields": {"sku": "001", "name": "…", "category": "Gépek/Mosó"},
  "supplier_id": 1, "supplier_name": "…", "source_line": 2, "source_run_id": 5,
  "source_category": {"id": 4, "path": "Gépek/Mosó", "origin": "supplier", "supplier_id": 1},
  "classification": {
    "status": "auto_classified", "status_label": "Automatikusan besorolt",
    "origin": "category_map", "method": "category_map", "reason_codes": ["approved_category_map"],
    "navigation_node_id": "web-item-114-3490",
    "navigation_path": ["Háztartási gépek és klíma", "Mosógépek és szárítógépek", "Elöltöltős mosógépek"],
    "donor_emag_category_id": 385, "donor_name": "Mosógépek", "donor_choices": [],
    "confidence": null, "alternatives": [], "locked": false,
    "rule_version": "category-02a.1", "decided_by": null, "decided_at": "2026-11-15T19:00:00"
  },
  "export_category": {"kind": "own", "path": "Gépek/Mosó"}
}
```
- A `source_category` értéke `null`, ha a terméknek nincs saját kategóriája.
- Az `alternatives[]` legfeljebb 3 elemű: `{"navigation_node_id", "path": [...], "score": null}`.
- A `donor_choices[]` csak többprofilos belső kategóriánál nem üres: `{"emag_category_id", "name"}`.

### `GET /api/v1/workspace/products/{id}`

A `ProductItem` mezői, kiegészítve:
- `source_attributes[]`: **minden** meg nem feleltetett forrásoszlop, oszlopsorrendben:
  ```json
  {"key": "Teljesítmény (W)", "header": "Teljesítmény (W)", "label": "Teljesítmény", "unit": "W",
   "raw": "2100", "column": 3, "run_id": 5, "line": 2, "present": true}
  ```
  - `present: false`: az oszlop a legutóbbi fájlból hiányzott. Az érték megmaradt, de nem friss.
  - A `unit` a fejlécből levezetett szintaktikai érték, nincs átváltva.
- `events[]` (legfeljebb 50, újabb elöl): `{"id", "kind", "revision", "actor_id", "run_id", "reason", "before", "after", "created_at"}`
  - `kind` értékei: `classification_auto`, `classification_manual`, `classification_reset`.
  - Az import mezőváltozásai továbbra is a `GET /api/v1/imports/products/{id}/changes` végponton érhetők el. A forrásparaméterek változásai ott `"source:<fejléc>"` kulccsal szerepelnek.
- `capabilities`: `{"classify": bool}`. A UI csak ez alapján ajánl írást; a backend minden írást újra ellenőriz.

### `PATCH /api/v1/workspace/products/{id}/classification` (`products.classify`)

**Kérés:**
```json
{"expected_revision": 3, "action": "set", "navigation_node_id": "web-item-114-3490",
 "donor_emag_category_id": 385, "reason": "…"}
```

| `action` | Hatás |
|---|---|
| `set` | Kézi döntés. A `navigation_node_id` kötelező, a `donor_emag_category_id` opcionális. Egyprofilos kategóriánál automatikusan kitöltődik; többprofilosnál választás nélkül `null`, és `parameter_profile_choice_required` okot kap. Eredmény: `origin: manual`, `locked: true`, `status: auto_classified`. |
| `reset` | Feloldja a zárat, és újrafuttatja az automatikus döntést. Kategória nem adható meg. |

- Egy művelet **pontosan egy** revízióval növel.
- Válasz: a frissített részlet (mint a `GET /products/{id}`).
- Elavult `expected_revision` → **409**, és semmi nem változik.
- Ismeretlen vagy nem besorolható kategória, illetve idegen donor → **422**.
- A döntés `product_events` bejegyzés és `audit_events` (`products.classification_manual`/`_reset`) mellett történik.
- A **zárolt** besorolást sem import, sem kategóriatérkép nem írja át.

### `GET /api/v1/workspace/category-maps`

Az ügyfél saját kategóriái és a hozzájuk tartozó térkép.
- Paraméterek: `cursor`, `limit` (1–100, alapérték 50), `state` (`unmapped` / `approved` / `rejected`), `supplier_id`.
- Válasz:
  ```json
  {"items": [{"source_category": {…}, "product_count": 120,
              "map": null | {"state", "navigation_node_id", "navigation_path", "donor_emag_category_id",
                             "revision", "reason", "decided_by", "decided_at"},
              "suggestions": [{"navigation_node_id", "path", "score": null}]}],
   "next_cursor": null}
  ```
- A `suggestions` pontos (ékezet- és kisbetű-független) névegyezés. **Nem kalibrált**, ezért csak felajánlás, automatikusan nem érvényesül.

### `PUT /api/v1/workspace/category-maps/{source_category_id}` (`products.classify`)

**Kérés:**
```json
{"expected_revision": null, "state": "approved", "navigation_node_id": "…", "donor_emag_category_id": null, "reason": "…"}
```
- Új térképnél `expected_revision: null`, meglévőnél az aktuális revízió. Eltérés → **409**.
- `state: rejected` mellett kategória nem adható meg.
- A mentés után a saját kategória **nem zárolt** termékei azonnal, kötegekben újra besorolódnak.
- Válasz: `{"source_category", "map", "products_changed", "locked_skipped"}`.
- Egyetlen összesítő `product_events` (`kind: category_map`) és `audit_events` bejegyzés keletkezik.

### `DELETE /api/v1/workspace/category-maps/{source_category_id}?expected_revision=N` (`products.classify`)

Törli a térképet, és újra besorolja a nem zárolt termékeket. Elavult revízió → 409.

### `GET /api/v1/workspace/internal-categories`

Választólista a belső besoroláshoz.
- Paraméterek: `q` (ékezet-független részszöveg az útvonalban), `offset`, `limit` (≤ 100).
- Válasz: `{"items": [{"navigation_node_id", "name", "path": [...], "donors": [{"emag_category_id", "name"}]}], "total", "offset", "limit", "rule_version"}`

### `GET` / `PUT /api/v1/system/settings/classification`

- `GET /api/v1/system/settings` válasza új `classification` csoportot kap: `{"auto_threshold": 0.98}`.
- `PUT /api/v1/system/settings/classification` törzse: `{"auto_threshold": 0.5..1.0}`.
  - `system.settings.manage` jog és friss újraazonosítás kell.
  - A módosítás naplózva van (`settings09.classification`).
- A küszöb azt adja meg, mekkora **mért** precizitás kell ahhoz, hogy egy módszer automatikusan besorolhasson. Ez **nem mért pontosság**. Kalibrálatlan módszer a küszöbtől függetlenül sosem automatikus (`CALIBRATED_PRECISION` jelenleg üres).

## Import: futáskorlát és forrásmegőrzés

- **Futásonként legfeljebb 50 000 termék.**
  - Az elemzés kitölti az `analysis.data_rows` és az `analysis.run_product_limit` mezőt.
  - Nagyobb fájlnál a jóváhagyás **422**-t ad, magyar üzenettel, amely a fájl bontását javasolja.
  - Automatikus profil esetén a futás egyetlen sor írása nélkül `failed` állapotba kerül.
  - Az `IMPORT_MAX_PRODUCTS` környezeti változó csak csökkentheti a korlátot.
- **A tenant teljes termékszámát semmi nem korlátozza.**
- A forrásoszlopok minden futásnál a termékre kerülnek. A hiányzó oszlop értéke megmarad (`present: false`). Részleges feedben az üres cella nem töröl; teljes (`full`) feedben töröl.

## Eltérések a CATEGORY-01B munkaneveitől

| 01B munkanév | Itt | Megjegyzés |
|---|---|---|
| `GET /workspace/category-options` | `GET /workspace/category-maps` + `GET /workspace/internal-categories` | A saját kategóriák és a belső választólista külön végpont. |
| `PATCH …/classification` „display-category + donor művelet” | `action: set/reset`, donor opcionális | A saját kategória (display) nem szerkeszthető, mert az import forrása. A belső besorolás és a donor együtt változik. |
| `parameter-diff`, `parameter-previews`, `bulk-previews`, `operations`, `preparation-approvals` | — | Későbbi szakasz (0010, paraméterhelyek). |
| `products.bulk.manage` és tömeges művelet | kategóriatérkép | A kategóriaszintű tömeges besorolás a térképen keresztül megy. Tetszőleges termékhalmazra vonatkozó tömeges művelet még nincs. |
