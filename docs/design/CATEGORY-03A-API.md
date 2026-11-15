# CATEGORY-03A – API/DTO-szerződés: paraméterhelyek, alias/mértékegység, verziózott diff

- **Feladat:** [#23](https://github.com/bizsis/adatdusito/issues/23). Alap: CATEGORY-02A (#18, `e946b93`) és a CATEGORY-02C donorvédelem (#25).
- **Státusz:** a szerződés az implementációval együtt készül a `claude/category-03a-parameters` ágon. Csak az a végpont tekinthető késznek, amelyet a PR „Implementált végpontok” listája annak jelöl.
- Az útvonalak és a mezőnevek a frontend (Codex) számára **véglegesek**. Változtatás csak additív lehet, vagy a Vezér döntésével történhet.
- Ez a fázis **paraméter-előkészítés**: nincs AI-hívás, nincs képkeresés, nincs kreditfelhasználás, nincs UNAS-export-módosítás. Meglévő, nem üres beszállítói értéket automatika nem ír felül.

## Közös szabályok

A CATEGORY-02A szabályai érvényesek: session-cookie, `X-CSRF-Token` minden írásnál, Origin-ellenőrzés, `Cache-Control: no-store`, a tenant mindig a session munkaterülete, idegen rekordra 404, hibaformátum `{"error": {"code", "message"}}`.

| Művelet | Jog |
|---|---|
| Diff, paraméterek, aliasok, futások olvasása; előnézet | `products.read` |
| Kézi paraméterdöntés, termékszintű alkalmazás, tenant-alias, futás indítása | **`products.parameters`** (új, tenant-jog; a 0010 migráció veszi fel, ügyféladmin és superadmin kapja) |
| Globális alias (minden tenantra érvényes) | **`parameters.global_aliases.manage`** (új, rendszerjog; csak superadmin vagy kifejezetten kiosztott rendszerszerep) |

| Kód | Jelentés |
|---|---|
| 404 | idegen vagy nem létező termék, hely, alias vagy futás |
| **409** | elavult `expected_revision` (termék) vagy `expected_version` (alias). A kliens töltse újra az adatot, nincs automatikus újrapróbálás. |
| 422 | érvénytelen művelet, hely vagy érték (pl. nem megengedett érték kötött listánál) |
| 503 | nincs aktív, ellenőrzött közös katalógusverzió (paraméterdefiníciók nélkül nem lehet helyeket képezni) |

## Fogalmak

**Paraméterhely** (`slot`): termékenként egy sor, kulcsa a `slot_key`.

| `slot_key` | Jelentés |
|---|---|
| `emag:<emag_parameter_id>` | a kiválasztott donor egy paramétere. Termékenként **legfeljebb egy** van paraméterenként. |
| `src:<forráskulcs>` | olyan beszállítói adat, amely nem illeszthető biztosan donorparaméterre. **Megmarad**, nem dobjuk el. A forráskulcs a `source_attributes` kulcsa, strukturált mezőnél `field:<mező>` (pl. `src:field:weight`). |

**Állapot** (`state`):

| `state` | Felirat | Jelentés |
|---|---|---|
| `present` | Kitöltve | biztos érték: normalizált egyezés, jóváhagyott alias vagy kézi döntés |
| `missing` | Hiányzik | a donor paramétere, amelyhez nincs forrásadat (üres hely) |
| `review` | Ellenőrzést igényel | bizonytalan egyezés vagy nem igazolt mértékegység; `candidates[]` sorolja a jelölteket |
| `conflict` | Ellentmondás | több forrás eltérő értékkel ugyanarra a helyre; minden forrás megmarad a `sources[]`-ben |
| `invalid` | Érvénytelen | típus-, egység- vagy megengedettérték-hiba; a nyers érték megmarad |
| `source_only` | Csak forrásban | `src:` hely, donorparaméterre nem illeszthető |
| `detached` | Korábbi profilból | donorváltás után megmaradt, kitöltött vagy kézi érték, amely az új donorban nincs |

**Eredet** (`origin`): `source` (normalizált névegyezés), `alias` (jóváhagyott alias), `added_slot` (a donor hiányzó paraméteréhez létrehozott üres hely), `user` (kézi döntés). Az `ai` értéket későbbi fázis számára foglaltuk le, ebben a fázisban nem fordul elő.

**Okok** (`reason_codes[]`, bővülhet):

| Kód | Jelentés |
|---|---|
| `exact_label_match` | a forráscímke normalizálva megegyezik a donorparaméter nevével |
| `approved_alias` | jóváhagyott alias alapján (`alias.id`, `alias.version`) |
| `unit_converted` | igazolt, determinisztikus egységátváltás történt (`unit_conversion`) |
| `similar_label` | hasonló címke, nem biztos: review |
| `unit_unverified` | a forrásnál nincs mértékegység, a célparaméternél van: review |
| `unit_mismatch` | nem átváltható mértékegység: invalid |
| `not_numeric` | mértékegységes célhoz nem szám érték: invalid |
| `value_not_allowed` | kötött értékkészletnél (`allow_new_value = false`) nincs egyező megengedett érték: invalid |
| `conflicting_sources` | több forrás eltérő értékkel |
| `donor_param_without_source` | hiányzó donorparaméter, üres hely |
| `donor_not_ready` | a terméknél nincs dúsításra kész donor (`parameter_profile_state` ≠ `ready`): csak `src:` helyek keletkeznek |
| `source_changed_locked` | a forrásérték változott, de a hely kézzel zárolt: az érték nem változott |
| `source_refreshed` | ugyanabból a forrásoszlopból frissült az érték (feedfrissítés) |
| `profile_changed` | donorváltás miatt `detached` |
| `manual_decision` | kézi döntés |

**Donorvédelem (#20 / #25):** paraméterhely-kiegészítés (`emag:` helyek) csak `parameter_profile_state == "ready"` állapotnál történik. `pending_review`, `choice_required` és `none` esetén csak a forrásadatok (`src:`) képződnek, `donor_not_ready` okkal. A meglévő kitöltött helyek nem törlődnek.

### Paraméterhely DTO

```json
{
  "slot_key": "emag:6506",
  "emag_parameter_id": 6506,
  "name": "Teljesítmény (W)",
  "label": "Teljesítmény", "target_unit": "W",
  "mandatory": true, "is_filter": false, "allow_new_value": true,
  "state": "present", "state_label": "Kitöltve",
  "origin": "source",
  "reason_codes": ["exact_label_match", "unit_converted"],
  "value": "2100", "unit": "W", "value_id": null,
  "unit_conversion": {"from": "kW", "to": "W", "factor": 1000, "raw_number": "2,1"},
  "sources": [
    {"key": "Teljesítmény (kW)", "kind": "attribute", "header": "Teljesítmény (kW)",
     "label": "Teljesítmény", "unit": "kW", "raw": "2,1", "run_id": 12, "line": 7, "present": true}
  ],
  "candidates": [],
  "alias": null,
  "locked": false,
  "donor_emag_category_id": 385,
  "catalog_version_id": 4,
  "rule_version": "category-03a.1",
  "updated_by": null, "updated_at": "2026-11-16T09:00:00"
}
```

- A `sources[]` az eredeti fejlécet, nyers értéket, mértékegységet és eredetet **változatlanul** adja vissza. A `kind` értéke `attribute` (`source_attributes`) vagy `field` (strukturált mező, pl. `weight`).
- A `candidates[]` (review/conflict esetén, legfeljebb 3 elem) alakja: `{"slot_key", "emag_parameter_id", "name", "reason"}` címkejelöltnél, vagy `{"source_key", "value", "unit"}` értékjelöltnél.
- Az `alias` alakja: `{"id", "version", "scope"}`, ha alias döntött.

## Végpontok

### `GET /api/v1/workspace/parameter-diff` (`products.read`)

Lapozható termékszintű áttekintés a **tárolt** paraméterhelyekről.

Paraméterek: `cursor` (utolsó termék-ID), `limit` (≤ 100, alapérték 25), `state` (`present|missing|review|conflict|invalid|source_only|detached`: csak az ilyen helyet tartalmazó termékek), `mandatory_missing` (bool), `navigation_node_id`, `source_category_id`, `supplier_id`, `parameter_profile_state` (`ready|choice_required|pending_review|none`), `q` (a 02A keresés).

```json
{
  "items": [{
    "product_id": 7, "revision": 4, "name": "Mosógép A", "sku": "001",
    "navigation_node_id": "web-item-114-3490", "navigation_path": ["…"],
    "donor_emag_category_id": 385, "parameter_profile_state": "ready",
    "counts": {"present": 12, "missing": 30, "review": 1, "conflict": 0,
               "invalid": 1, "source_only": 4, "detached": 0},
    "mandatory_missing": 3,
    "prepared": true,
    "rule_version": "category-03a.1", "catalog_version_id": 4
  }],
  "next_cursor": 7,
  "state_labels": {"present": "Kitöltve", "…": "…"}
}
```
- `prepared: false`: a termékhez még nincs tárolt hely; ilyenkor a `counts` értékei 0-k. Előnézet a termék végpontján kérhető.

### `GET /api/v1/workspace/products/{id}/parameters` (`products.read`)

```json
{"product_id": 7, "revision": 4,
 "classification": {"navigation_node_id": "…", "donor_emag_category_id": 385, "parameter_profile_state": "ready"},
 "catalog_version_id": 4, "rule_version": "category-03a.1",
 "slots": [<Paraméterhely DTO>, …],
 "capabilities": {"edit": true}}
```
A sorrend: előbb az `emag:` helyek a donor `display_order` szerint, utána az `src:` és `detached` helyek a forrás oszlopsorrendjében.

### `POST /api/v1/workspace/products/{id}/parameters/preview` (`products.read`)

Kiszámolja a jelenlegi forrásadatból, besorolásból, aliasokból és katalógusból adódó helyeket. **Nem ír.** Body: `{}`.

```json
{"product_id": 7, "revision": 4, "slots": [<DTO>, …],
 "changes": [{"slot_key": "emag:6506", "change": "create|update|remove|keep|blocked_locked",
              "before": {"state", "value", "unit"} | null, "after": {"state", "value", "unit"} | null}],
 "summary": {"create": 30, "update": 1, "remove": 0, "keep": 12, "blocked_locked": 0}}
```

### `POST /api/v1/workspace/products/{id}/parameters/apply` (`products.parameters`)

Body: `{"expected_revision": 4}`. Az előnézet szerinti változást alkalmazza **egy** termékre. Ha változott, a termék `revision`-je eggyel nő. Válasz: mint a `GET …/parameters`, kiegészítve ezzel: `"applied": {"create", "update", "remove", "keep", "blocked_locked"}`. Elavult revízió esetén 409.

### `PATCH /api/v1/workspace/products/{id}/parameters/{slot_key}` (`products.parameters`)

Kézi döntés egy helyen. A `slot_key` URL-kódolva értendő (pl. `emag%3A6506`).

```json
{"expected_revision": 4, "action": "set|accept_candidate|lock|unlock|reset",
 "value": "2100", "unit": "W", "value_id": null, "source_key": null, "reason": "…"}
```

| `action` | Hatás |
|---|---|
| `set` | Kézi érték (`origin: user`, `state: present`, `locked: true`). Kötött értékkészletnél (`allow_new_value = false`) `value_id` kötelező és megengedett kell legyen, különben 422. Az eredeti `sources[]` megmarad. |
| `accept_candidate` | A `source_key` forrás értékét fogadja el review/conflict helyen (`origin: user`, zárolt). |
| `lock` / `unlock` | Zárolás be/ki. Feloldás után a következő alkalmazás újraszámolhatja a helyet. |
| `reset` | Feloldja a zárat, és a helyet újraszámolja (mint az `apply`, egy helyre). |

Minden sikeres kézi művelet növeli a termék `revision`-jét, és `product_events` (`kind: parameter_manual`) és `audit_events` bejegyzést ír. Elavult revízió esetén 409.

### `GET /api/v1/workspace/parameter-aliases` (`products.read`)

Paraméterek: `scope` (`tenant|global|all`, alapérték `all`), `state` (`approved|revoked`, alapérték `approved`), `emag_parameter_id`, `q` (címke), `cursor`, `limit` (≤ 100).

```json
{"items": [{"id": 3, "version": 1, "scope": "tenant", "state": "approved",
            "label": "Teljesítmény", "label_key": "teljesitmeny", "unit": "kW",
            "emag_parameter_id": 6506, "scope_emag_category_id": 385,
            "reason": "…", "decided_by": 2, "decided_at": "…"}],
 "next_cursor": null}
```

### `POST /api/v1/workspace/parameter-aliases`

```json
{"scope": "tenant|global", "label": "Teljesítmény", "unit": "kW",
 "emag_parameter_id": 6506, "scope_emag_category_id": 385, "reason": "…"}
```
- `tenant`: `products.parameters` kell; `global`: `parameters.global_aliases.manage`.
- A `scope_emag_category_id` kötelező: az alias **donorkörnyezethez** kötött, mert ugyanaz a címke más kategóriában mást jelenthet. A paraméternek szerepelnie kell a donor paraméterei között, különben 422.
- Azonos (tenant/globális, donor, címke, egység) kulcsra egy jóváhagyott alias lehet. Ha már létezik, 409.
- Az alias a következő alkalmazástól kezdve (termékszintű `apply` vagy futás) érvényesül, importonként újrafelhasználható. Visszamenőleges automatikus csere nincs: zárolt vagy kitöltött értéket nem ír felül.
- Elsőbbségi sorrend: tenant-alias, majd globális alias, majd normalizált névegyezés.

### `DELETE /api/v1/workspace/parameter-aliases/{id}?expected_version=N`

Visszavonás: `state: revoked`, a `version` eggyel nő, a rekord megmarad (verziózott). Jog: mint a létrehozásnál. Elavult verzió esetén 409. A már tárolt helyek nem változnak, a következő alkalmazás `review`-ra teheti őket.

### `POST /api/v1/workspace/parameter-runs` (`products.parameters`)

Folytatható háttérfutás a paraméterhelyek előállítására.

```json
{"mode": "preview|apply",
 "scope": {"source_category_id": null, "navigation_node_id": null, "supplier_id": null},
 "start_after_product_id": 0}
```
- Egy futás **legfeljebb 50 000 terméket** dolgoz fel (`RUN_PRODUCT_LIMIT`, a 02A-val közös, környezeti változóval csak csökkenthető). A tenant összes termékszáma ezen felül korlátlan: ha a hatókörben több termék van, a futás `has_more: true` és `next_start_after_product_id` értékkel zárul, és a kliens új futást indíthat onnan.
- `preview`: csak számlál, nem ír. `apply`: kötegelt (500 termék) írás kurzorral. Megszakítás után folytatható, ismételt futtatás esetén idempotens (változatlan termékhez nem ír és nem növel revíziót).
- Termékenként a `apply` ugyanazt teszi, mint a termékszintű `apply`, revízióellenőrzés nélkül: zárolt helyet nem ír, csak `blocked_locked`-ként számolja.
- Válasz: `{"job": <job DTO>}`. Ugyanarra a hatókörre indított újabb futás a régit `superseded` állapotba teszi.

### `GET /api/v1/workspace/product-jobs/{id}` (`products.read`)

A 02C végpont, bővítve: `kind: "parameter_slots"`. A paraméterfutás számlálói:

```json
{"id": 9, "kind": "parameter_slots", "state": "running", "stalled": false,
 "mode": "apply", "scope": {…}, "start_after_product_id": 0,
 "processed": 1500, "limit": 50000, "has_more": false, "next_start_after_product_id": null,
 "products_changed": 1400, "products_not_ready": 80,
 "slots": {"create": 40000, "update": 120, "remove": 30, "keep": 5000, "blocked_locked": 4},
 "states": {"present": 9000, "missing": 30000, "review": 300, "conflict": 12, "invalid": 40,
            "source_only": 2000, "detached": 5},
 "error": null, "created_at": "…", "updated_at": "…"}
```
A 02C mezők (`source_category_id`, `total`, `products_changed`, `locked_skipped`) a térképfeladatnál változatlanok.

## Események

| `product_events.kind` | Mikor |
|---|---|
| `parameter_slots` | alkalmazás egy terméken (termékszintű vagy futás), csak változás esetén. `after: {"create": [...], "update": [...], "remove": [...], "run_id"?}` |
| `parameter_manual` | kézi döntés egy helyen, `before`/`after` helyállapottal |
| `parameter_source_refresh` | ugyanabból a forrásoszlopból frissült, nem zárolt érték |
| `parameter_alias` | alias létrehozása/visszavonása (termék nélküli esemény) |

Minden kézi művelet `audit_events`-be is kerül (`products.parameter_*`, `parameters.alias_*`).

## Egységátváltás

Csak az alábbi, igazolt, determinisztikus átváltások léteznek. Más esetben `invalid` vagy `review` lesz az eredmény.

| Mennyiség | Egységek |
|---|---|
| hossz | mm, cm, m |
| tömeg | g, kg |
| teljesítmény | W, kW |
| térfogat | ml, cl, dl, l |
| energia | Wh, kWh |
| frekvencia | Hz, kHz, MHz, GHz |

Adatméret (MB/GB/TB) nem váltódik át, mert kétértelmű (1000 vs. 1024). A nyers érték mindig megmarad (`sources[].raw`, `unit_conversion.raw_number`). A tizedesvessző és -pont is elfogadott, ezres elválasztót nem találgatunk.
