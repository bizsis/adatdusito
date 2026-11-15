# CATEGORY-03C – API/DTO-szerződés: tömeges paraméter-előkészítés és előkészítési jóváhagyás

- **Feladat:** [#28](https://github.com/bizsis/adatdusito/issues/28). Alap: CATEGORY-03A (#26, `c05746d`). UX-forrás: `docs/design/CATEGORY-01B-UX.md` S6–S7 (Codex).
- **Státusz:** szerződés; az implementáció a `claude/category-03c-bulk` ágon készül. Késznek csak az a végpont tekinthető, amelyet a PR „Implementált” listája annak jelöl.
- **Additív:** a 03A végpontjai és mezői változatlanok. A 03A egyéni `preview`/`apply` és a `parameter-runs` továbbra is működik; a 03C a **kiválasztott halmazra** kötött, tokenes, ellenőrzött tömeges útvonalat adja hozzá.
- Nincs AI-hívás, kutatás, kredit, fizetés, képkeresés, UNAS-export vagy telepítés. Az előkészítési jóváhagyás **csak** a későbbi kutatás bemenetét rögzíti.

## Viszony a 03A-hoz

| Igény | 03A | 03C |
|---|---|---|
| Egy termék előnézete/alkalmazása | `POST /products/{id}/parameters/preview\|apply` | változatlan |
| Hatókör szerinti háttérfutás | `POST /parameter-runs` (élő szűrő, megerősítés nélkül) | változatlan; adminisztratív újraszámolásra |
| Rögzített, szerveres kiválasztás | – | `POST /product-selections` → opaque `selection_token` |
| Hiteles tömeges előnézet | – | `POST /parameter-bulk-previews` → termékenkénti eredmény, `preview_token` |
| Megerősített tömeges alkalmazás | – | `POST /parameter-bulk-previews/{id}/apply` (token + megerősítés + idempotenciakulcs) |
| Előkészítési jóváhagyás | – (`prepared` csak azt jelenti: van tárolt hely) | `POST /preparation-checks` → `POST /preparation-approvals` |

## Közös szabályok

Session-cookie, `X-CSRF-Token`, Origin, `no-store`, tenant = a session munkaterülete, hibaformátum `{"error": {"code", "message"}}` – mint a 02A/03A-ban. A böngésző **nem küld** tenant-ID-t és nem küld nagy termék-ID-listát.

| Művelet | Jog |
|---|---|
| Kiválasztás, tömeges előnézet, előkészítési ellenőrzés, olvasás | `products.read` |
| Tömeges alkalmazás | **`products.parameters` és `products.bulk`** (új tenant-jog, 0011) – a kettő nem helyettesíti egymást |
| Előkészítési jóváhagyás, visszavonás, újramérés | **`products.prepare.approve`** (új tenant-jog, 0011). Nem importjóváhagyás, nem AI-/kreditengedély. |
| Futás megszakítása / folytatása | a futás létrehozója, vagy az indításához szükséges jogok birtokosa |

Az új jogokat a 0011 migráció veszi fel a jogkatalógusba; alapból az ügyféladminisztrátor (és a superadmin) kapja, más szerepkörhöz a szerepkör-szerkesztőben adható.

| Kód | Jelentés |
|---|---|
| 404 | idegen/nem létező kiválasztás, futás, jóváhagyás – vagy nem a sajátod kiválasztása |
| **409** | lejárt vagy hibás token; az előnézet/ellenőrzés még nem kész; a megerősített darabszám eltér a szerveres számtól; idempotenciakulcs más tartalommal; elavult `expected_version` |
| 422 | érvénytelen szűrő; üres kiválasztás; túl nagy kiválasztás (`> 250 000`); `confirm` hiányzik |
| 503 | nincs aktív közös katalógus |

**Tokenek:** `selection_token`, `preview_token`, `check_token` – 43 karakteres, véletlen, átlátszatlan karakterlánc. A szerver csak SHA-256 lenyomatát tárolja; **egyszer**, a létrehozó válaszban kapja meg a kliens. URL-be, naplóba, megosztható linkbe nem kerül. A token a létrehozó felhasználóhoz és tenanthoz kötött.

**Lejárat:** a kiválasztás `expires_at` értéke a létrehozástól **2 óra**. A belőle készült előnézet és ellenőrzés ugyanekkor jár le; lejárt token → 409. A már elindult alkalmazási futás a lejárat után is befejeződik (a megerősítés a lejárat előtt történt).

**Futáskorlát:** egy *feldolgozási futás* legfeljebb 50 000 terméket dolgoz fel (`run_product_limit()`). A kiválasztás ennél nagyobb is lehet (legfeljebb 250 000): az előnézet, az ellenőrzés és az alkalmazás ilyenkor **több egymást követő futásban** halad ugyanazon a feladaton (`runs`), automatikusan.

**Kötegek:** 500 termék/köteg, kötegenként commit és kurzor. Termékenként atomi (savepoint): egy termék hibája `error` eredmény, a többi halad. Nincs óriási tranzakció, a HTTP-kérés nem vár a feldolgozásra.

## 1. Kiválasztás (snapshot)

### `POST /api/v1/workspace/product-selections` (`products.read`)

```json
{"filters": {"state": null, "mandatory_missing": null, "navigation_node_id": null,
             "source_category_id": null, "supplier_id": null,
             "parameter_profile_state": null, "q": null},
 "exclude_product_ids": [12, 13],
 "product_ids": null}
```
- `filters`: pontosan a `GET /parameter-diff` szűrői, ugyanazzal a jelentéssel. A szerver a **teljes** szűrt halmazt rögzíti (nem csak egy oldalt), termékenként az aktuális `revision`-nel.
- `exclude_product_ids`: legfeljebb 1000 kizárt termék (rövid kivétellista).
- `product_ids`: a `filters` helyett egy oldalnyi (legfeljebb 100) kifejezett termék. A kettő együtt nem adható meg. Idegen ID → 404.

Válasz:
```json
{"id": 41, "selection_token": "…", "total": 18234, "expires_at": "2026-11-16T12:00:00",
 "filters": {…}, "excluded": 2, "mode": "filters|product_ids",
 "catalog_version_id": 4, "rule_version": "category-03a.1", "created_at": "…"}
```

### `GET /api/v1/workspace/product-selections/{id}` (`products.read`, csak a létrehozónak)

Ugyanez token nélkül, plusz `"expired": bool`.

## 2. Tömeges előnézet

### `POST /api/v1/workspace/parameter-bulk-previews` (`products.read`)

Body: `{"selection_token": "…"}`. Válasz: `{"preview": <művelet DTO>, "preview_token": "…"}`. A számítás háttérben fut; a kliens a `GET /product-jobs/{id}`-t kérdezi 2–5 mp-enként.

Termékenkénti **eredmény** (`outcome`):

| `outcome` | Jelentés | Alkalmazáskor |
|---|---|---|
| `eligible` | van alkalmazandó változás (új hely, frissítés, üres hely törlése) | alkalmazza |
| `unchanged` | a tárolt helyek már megfelelnek | kihagyja |
| `skipped_pending_review` | a donor `pending_review` (#25: 3 csomópont–donor pár) | kihagyja |
| `skipped_choice_required` | többprofilos, nincs kifejezett donor | kihagyja |
| `skipped_no_donor` | nincs besorolás vagy donor | kihagyja |
| `error` | a számítás hibát adott (a többi termék halad) | kihagyja |

A zárolt helyek egy `eligible` terméken belül sem íródnak: `blocked_locked` számlálóban látszanak.

**Művelet DTO** (előnézet, alkalmazás és előkészítési ellenőrzés közös alakja):
```json
{"id": 77, "kind": "bulk_preview|bulk_apply|preparation_check", "state": "pending|running|completed|cancelled|failed",
 "stalled": false, "selection_id": 41, "preview_id": null, "expires_at": "…",
 "total": 18234, "processed": 18234, "runs": 1, "run_limit": 50000,
 "outcomes": {"eligible": 15000, "unchanged": 3000, "skipped_pending_review": 20,
              "skipped_choice_required": 200, "skipped_no_donor": 14, "error": 0},
 "slots": {"create": 400000, "update": 1200, "remove": 300, "keep": 90000, "blocked_locked": 40},
 "new_slots": {"missing": 300000, "review": 5000, "conflict": 120, "invalid": 900,
               "present": 94000, "source_only": 1000},
 "accepted_present": 88000, "source_refresh": 150, "source_overwrites": 0,
 "revision_changed_since_selection": 12,
 "error": null, "created_by": 2, "created_at": "…", "updated_at": "…"}
```
- `slots`/`new_slots`: a ténylegesen érintett termékek tételes összege (nem becslés). `new_slots.missing` = újonnan létrejövő üres donorhely (a későbbi kutatás célja).
- `accepted_present`: változatlanul megmaradó, már kitöltött hely.
- `source_overwrites`: meglévő, nem üres érték másik forrásból történő felülírása. A motor szabálya szerint **mindig 0**; a szerver kiszámolja és közli, hogy a kliens ellenőrizhesse.
- `processed`/`total` pontos haladás (a `total` ismert, mert a kiválasztás rögzített).

### `GET /api/v1/workspace/product-jobs/{id}/items` (`products.read`)

Lapozható termékenkénti eredmény: `outcome`, `apply_outcome` szűrő, `cursor`, `limit ≤ 100`.
```json
{"items": [{"product_id": 7, "name": "…", "sku": "…", "outcome": "eligible",
            "apply_outcome": null, "revision_before": 4, "revision_after": null,
            "summary": {"create": 30, "update": 1, "remove": 0, "keep": 12, "blocked_locked": 0},
            "reasons": []}],
 "next_cursor": 7}
```
Alkalmazási futásnál ugyanez az előnézet tételeiből, az `apply_outcome`-mal.

## 3. Tömeges alkalmazás

### `POST /api/v1/workspace/parameter-bulk-previews/{id}/apply` (`products.parameters` + `products.bulk`)

```json
{"preview_token": "…", "confirm": true, "expected_eligible": 15000,
 "idempotency_key": "8b0c…(8–80 karakter)", "reason": "…"}
```
- Feltétel: az előnézet `completed`, nem járt le, a token egyezik, `confirm: true`, és az `expected_eligible` **pontosan** az előnézet `outcomes.eligible` értéke (amit a felhasználó látott). Különben 409/422.
- **Idempotencia:** ugyanazzal a kulccsal és tartalommal ismételt kérés a már létrehozott futást adja vissza (200), új futás nélkül. Ugyanaz a kulcs más tartalommal → 409.
- Válasz: `{"apply": <művelet DTO, kind=bulk_apply>}`.

Termékenkénti `apply_outcome`:

| `apply_outcome` | Jelentés |
|---|---|
| `applied` | alkalmazva, a termék `revision`-je eggyel nőtt |
| `unchanged` | időközben már nem volt mit alkalmazni |
| `stale` | a termék revíziója változott az előnézet óta: **kihagyva**, új előnézet kell |
| `changed_since_preview` | ugyanazon revízió mellett a számított változás eltér (pl. új alias, katalógusváltás): kihagyva |
| `cancelled` | a futást megszakították, mielőtt ide ért |
| `permission_revoked` | a létrehozó jogát visszavonták; a futás leállt, a már alkalmazott rész megmarad |
| `error` | hiba ennél a terméknél; a többi halad |

Az alkalmazás számlálói (`outcomes`): `applied`, `unchanged`, `stale`, `changed_since_preview`, `error`, plus a `slots`, `new_slots`, `source_overwrites` (0). Részleges siker = `completed` állapot nem nulla `stale`/`error` értékkel; **nem** „minden mentve”.

**Újrapróbálás:** ugyanarra az előnézetre új idempotenciakulccsal indított alkalmazás csak a még nem alkalmazott (`apply_outcome` üres vagy `error`) tételeket dolgozza fel. `stale`/`changed_since_preview` tételhez új kiválasztás/előnézet kell.

### `POST /api/v1/workspace/product-jobs/{id}/cancel` és `/resume`

- `cancel`: a hátralévő tételekre vonatkozik; a már alkalmazott rész megmarad (auditált). Állapot: `cancelled`.
- `resume`: `pending` vagy elakadt (`stalled: true`) futás újraindítása ugyanonnan (kurzor). Kész/megszakított futásra 409.

## 4. Előkészítési ellenőrzés és jóváhagyás

A `prepared` (a 03A diffben) csak azt jelenti, hogy a rendszer tárolt helyeket állított elő. Az **előkészítési jóváhagyás** külön, kifejezett felhasználói döntés egy ellenőrzött részhalmazra, rögzített termék-, séma- és katalógusrevízióval.

### `POST /api/v1/workspace/preparation-checks` (`products.read`)

Body: `{"selection_token": "…"}` → `{"check": <művelet DTO, kind=preparation_check>, "check_token": "…"}`.

Termékenkénti eredmény: `approvable` vagy `blocked`, a `reasons[]` mezőben:

| Blokkoló ok | Jelentés |
|---|---|
| `unclassified` | nincs belső kategória |
| `donor_pending_review` | a donor `pending_review` |
| `donor_choice_required` | többprofilos, nincs kifejezett donor |
| `donor_missing` | nincs alkalmazható donor |
| `not_prepared` | nincs tárolt paraméterhely |
| `stale_diff` | a tárolt helyek eltérnek a jelenleg számítottól (alkalmazatlan változás) |
| `meaning_conflict` | `conflict` állapotú hely |
| `meaning_uncertain` | `review` hely bizonytalan címkével (`similar_label`) |
| `unit_conflict` | `invalid` hely, vagy `review` `unit_unverified`/`ambiguous_number` okkal |

**Nem blokkol:** üres donorhely (`missing`) – ez a későbbi kutatás célja –, `source_only`, `detached`, zárolt kézi érték. Az eredmény `summary` mezője termékenként adja a kutatandó hiányok számát (`research_targets`, `mandatory_research_targets`).

Számlálók: `outcomes.approvable`, `outcomes.blocked`, `blocked_reasons{ok: db}`, `research_targets`, `mandatory_research_targets`.

### `POST /api/v1/workspace/preparation-approvals` (`products.prepare.approve`)

```json
{"check_id": 81, "check_token": "…", "confirm": true, "expected_approvable": 14200,
 "idempotency_key": "…", "reason": "Ellenőrzött mosógép-kör"}
```
- Feltételek, mint az alkalmazásnál (kész, nem lejárt ellenőrzés; token; megerősítés; pontos darabszám; idempotencia).
- Csak az `approvable` termékek kerülnek be, és csak akkor, ha a revíziójuk az ellenőrzés óta nem változott; a többi `skipped_stale`-ként számolódik.
- Rögzíti: termékenként `product_revision`, `navigation_node_id`, `donor_emag_category_id`, kutatandó hiányok; jóváhagyásszinten `catalog_version_id`, `rule_version`, `schema_fingerprint` (a besorolási szabályok és a donorellenőrzés lenyomata).

**Jóváhagyás DTO:**
```json
{"id": 5, "version": 1, "state": "active|revoked", "check_id": 81, "selection_id": 41,
 "approved": 14190, "skipped_stale": 10, "valid": 14190, "invalid": 0,
 "research_targets": 380000, "mandatory_research_targets": 41000,
 "catalog_version_id": 4, "rule_version": "category-03a.1", "schema_fingerprint": "…",
 "schema_current": true, "reason": "…", "approved_by": 2, "approved_at": "…",
 "revoked_by": null, "revoked_at": null, "revoke_reason": null, "revalidated_at": null}
```

**Érvényesség:** egy tétel érvényes, ha a termék `revision`-je változatlan, és a jóváhagyás `catalog_version_id`/`rule_version`/`schema_fingerprint` értéke megegyezik az aktuálissal (`schema_current`). Bármely termékváltozás (import, besorolás, donor, paraméterhely, kézi döntés) növeli a revíziót, így a tétel érvénytelen lesz. Az érvénytelen tétel a későbbi kutatási csomagba nem kerülhet.

### `GET /api/v1/workspace/preparation-approvals` (`products.read`)

Paraméterek: `state`, `cursor`, `limit ≤ 100` → `{"items": [<DTO>], "next_cursor"}`. A `valid`/`invalid` a legutóbbi újramérés szerinti érték; pontos aktuális érték a részletben.

### `GET /api/v1/workspace/preparation-approvals/{id}` (`products.read`)

A DTO **aktuálisan számolt** `valid`/`invalid` értékkel.

### `GET /api/v1/workspace/preparation-approvals/{id}/items` (`products.read`)

`valid` (bool) szűrő, `cursor`, `limit ≤ 100` →
```json
{"items": [{"product_id": 7, "product_revision": 9, "current_revision": 9, "valid": true,
            "invalid_reason": null, "navigation_node_id": "…", "donor_emag_category_id": 385,
            "research_targets": 26, "mandatory_research_targets": 3}], "next_cursor": null}
```
`invalid_reason`: `product_changed`, `schema_changed` vagy `revoked`.

### `POST /api/v1/workspace/preparation-approvals/{id}/revalidate` (`products.prepare.approve`)

Újramérés: az érvénytelen tételeket véglegesen érvénytelennek jelöli (`invalidated_at`), frissíti a számlálókat, auditál. Érvényessé nem tesz vissza semmit (ahhoz új ellenőrzés és jóváhagyás kell).

### `POST /api/v1/workspace/preparation-approvals/{id}/revoke` (`products.prepare.approve`)

Body: `{"expected_version": 1, "reason": "…"}` (az ok kötelező). Állapot `revoked`, `version` +1; a tételek megmaradnak (audit). Elavult verzió → 409.

### `GET /api/v1/workspace/products/{id}/preparation` (`products.read`)

`{"product_id", "revision", "approval": null | {"id", "approved_at", "product_revision", "valid", "invalid_reason", "research_targets", "mandatory_research_targets"}}` – a legutóbbi aktív jóváhagyás tétele.

## Események és audit

| Esemény | Mikor |
|---|---|
| `audit_events`: `products.selection_create`, `products.bulk_preview`, `products.bulk_apply`, `products.job_cancel`/`resume`, `products.preparation_check`, `products.preparation_approve`/`revoke`/`revalidate` | minden művelet, actorral és számlálókkal (nem tízezres JSON) |
| `product_events.kind = parameter_slots` | termékenként az alkalmazáskor (a 03A-val azonos), `after.job_id` = alkalmazási futás |
| `product_events.kind = bulk_operation` | összesítő esemény a futás végén (termék nélkül) |

## Ami nem része ennek a fázisnak

AI-kutatás, kalkuláció, kredit, fizetés, képkeresés, UNAS-export; kategória/donor tömeges módosítása (a 02A kategóriatérkép marad erre); a jóváhagyás nem indít semmit.
