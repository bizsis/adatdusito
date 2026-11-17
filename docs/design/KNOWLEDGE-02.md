# KNOWLEDGE-02 – Forrásfüggetlenség, kézi összevonás, szövegváltozatok, személyes adatok

A KNOWLEDGE-01 tudásbázis bővítése a Tulajdonos döntései alapján (#55-ös terv, 0016-os migráció).
A meglévő `/api/v1/knowledge` végpontok és a `/api/v1/knowledge-admin` (KNOWLEDGE-UI-01) API
**változatlan**. Az új funkciók új végpontokon érhetők el, a meglévő válaszok csak új mezőkkel
bővültek.

## Elvek

- **Semmi nem lesz automatikusan hiteles.** `verified` állapotba érték továbbra is csak emberi
  döntéssel (jóváhagyott javítás, adminisztrátori döntés) kerülhet. A másolásgyanú, a
  nyelvfelismerés és a változatvédelem csak **csökkentheti** a bizonyosságot, vagy akadályozhat.
- **A másolás csak gyanú.** A küszöbök elérése `suspected` állapotot ad, nem bizonyítékot. A
  gyanús forráspár egyetlen független forrásnak számít, amíg adminisztrátor másként nem dönt.
- **A személyes adatnak tűnő tartalom automatikusan visszatartott.** Nem kerül az összesített
  tudásba, más ügyfelek felé és az AI-felhasználásba, amíg `reference.manage` jogú felhasználó
  felül nem vizsgálja.
- **Bizonytalan összevonás nincs.** Két termék csak kézzel, előnézettel, indoklással és
  naplózva vonható össze, és az összevonás visszavonható.

## Beállítások (`knowledge` csoport)

`GET /api/v1/system/settings` → `knowledge`; módosítás:
`PUT /api/v1/system/settings/knowledge` (`system.settings.manage`, friss hitelesítés, auditált
`settings09.knowledge`). Mentés után a rendszer háttérben újraszámolja a bizonyosságokat
(`knowledge.rebuild`, `recompute=True`).

| Kulcs | Alapérték | Jelentés |
|---|---|---|
| `trust_reference` | 0.6 | referenciaforrás alapbizalma |
| `trust_tenant` | 0.5 | ügyfélfeltöltés alapbizalma |
| `trust_approved_correction` | 0.9 | jóváhagyott javítás bizalma |
| `suggest_threshold` | 0.8 | javaslati küszöb (enrichment-plan alapértéke), ≤ `confidence_cap` |
| `confidence_cap` | 0.95 | a kombinált bizonyosság plafonja (soha nem 1) |
| `copy_min_shared_values` | 50 | legalább ennyi közös érték egy forráspár közös termékein |
| `copy_identical_ratio` | 0.9 | és ezek legalább ekkora aránya betűre azonos |
| `copy_min_identical_texts` | 20 | vagy legalább ennyi betűre azonos hosszú leírás |
| `variant_attributes` | méret, szín, kivitel, változat, kiszerelés, size, color, colour, variant | változatjellegű tulajdonságok (részszó-egyezés, ékezet- és kisbetű-független) |
| `languages` | hu, en, ro, de | felismerendő nyelvek (ISO 639 kód) |

A forrás saját `trust_level` értéke (ha be van állítva) továbbra is felülírja az alapbizalmat.

## Működés

### Forrásfüggetlenség

- Egy érték bizonyossága `1 − Π(1 − c)` a **forráscsaládok** szerint (családonként a legerősebb
  állítás), legfeljebb `confidence_cap`.
- Egy családba tartoznak az azonos `lineage_group` értékű források (adminisztrátori
  beállítás, pl. közös beszállítói feed), és a `suspected` vagy `confirmed_dependent` állapotú
  forráspárok. A `confirmed_independent` a gyanút feloldja, de az azonos lineage-csoportot nem.
- A felismerés minden újraépítés végén lefut. Mindkét forrásnak csak az aktuális, vissza nem
  tartott állításai számítanak. Állapotváltozáskor `copy_suspected` vagy
  `copy_suspicion_cleared` esemény keletkezik, és az érintett termékek értékei újraszámolódnak.
  Az adminisztrátori döntést a felismerés nem írja felül.
- `knowledge_values.support_sources`: forrásszám (mint eddig).
  `knowledge_values.independent_sources`: független forráscsaládok száma.

### Változatvédelem

A márka+név egyezés nem kapcsol össze két rekordot, ha egy változatjellegű tulajdonságban
(pl. Méret: M ↔ XL) eltérnek. Ilyenkor `variant_candidate` esemény keletkezik, és a rekord
külön termék marad. GTIN-egyezésnél nincs ilyen korlát, mert a GTIN változatonként egyedi.

### Szövegváltozatok és nyelv

- A név, rövid leírás és hosszú leírás minden változata eredeti szöveggel megmarad
  (`knowledge_texts`): forrás, formátum (`plain`/`html`), nyelv, nyelvi bizonyosság és módszer
  (`heuristic`/`admin`), ellenőrzési állapot, felhasználási engedély és előzmény
  (`current`, `superseded_at`). A szövegek nem konszolidálódnak, mindegyik megmarad a későbbi
  magyar AI-leírásokhoz.
- Nyelvfelismerés: hálózat és új függőség nélküli heurisztika (gyakori szavak és jellemző
  betűk). `unknown` lesz az eredmény, ha 4 szónál rövidebb a szöveg, ha kevés a bizonyíték
  (2 pont és a szavak 15%-a alatt), vagy ha a két legjobb nyelv túl közel van egymáshoz
  (különbség < 30%). Új nyelv profillal bővíthető (`app/knowledge_signals.py`, `PROFILES`) és
  a `languages` beállítással kapcsolható be.
- Egy szöveg akkor használható AI-generáláshoz vagy közös tudásként (`usable_for_ai`), ha a
  forrása engedélyezett, a szöveg aktuális, nincs elutasítva, a felhasználása nem
  `internal_only` vagy `restricted`, és nincs felülvizsgálatlan személyesadat-gyanúja.

### Személyes adatok

Mintakeresés (`email`, `phone`, `tax_number`, `iban`) az értékekben és a szövegekben. Ez
felismerés, nem DLP-garancia. A gyanús érték nem vesz részt az összesítésben és a
másolásfelismerésben, a gyanús szöveg pedig nem `usable_for_ai`. Felülvizsgálat után:
- értéknél **feloldás**: újra beszámít; **megtartás**: végleg kimarad (`current=false`);
- szövegnél **feloldás**: használható; **megtartás**: `usage=restricted`.

### Kézi összevonás

1. `POST /merges/preview`: nem változtat semmit, és tokent ad, ami mindkét termék
   kapcsolat- és értékállapotához kötött.
2. `POST /merges` a tokennel és indoklással. Ha a token óta bármi változott:
   `stale_preview`. Két eltérő **ellenőrzött** érték esetén: `blocked`. Ha az előnézet
   figyelmeztetést ad (`variant_risk`), kifejezett `acknowledge_variant_risk: true` kell.
3. Az összevont termék `merged` állapotú lesz, `merged_into_id`-val. A kapcsolatok,
   azonosítók, állítások és szövegek a megmaradó termékhez kerülnek. A mozgatási napló a
   `knowledge_merges.moved` mezőbe kerül, és az automatikus újraépítés nem bontja meg.
4. `POST /merges/{id}/revert`: pontosan a napló alapján állítja vissza az állapotot,
   fordított sorrendben (LIFO). Ha egy későbbi összevonás érinti valamelyik terméket, előbb azt
   kell visszavonni (`later_merge_first`).

## API-szerződés (KNOWLEDGE-UI-02)

Előtag: `/api/v1/knowledge`. Minden új végponthoz `reference.manage` jog kell. A módosító
kérések a szokásos `X-CSRF-Token` és `Origin` védelemmel működnek, minden válasz `no-store`, és
a döntések auditnaplóba (`knowledge.*`) és tudásbázis-eseménybe kerülnek. Az `reason` mező
mindenhol 3–500 karakter, kötelező. A hibaválasz formátuma a megszokott
`{"error": {"code", "message"}}` (a `message` magyar szöveg).

### Bővült meglévő válaszok (csak új mezők)

- Termék (`GET /products/{id}`, listák): `merged_into_id` (int | null).
- Érték: `independent_sources` (int).
- `POST /enrichment-plan`: a `threshold` elhagyható (alapérték a `suggest_threshold`), és van
  új `texts` mező (legfeljebb 3 elem: `name`, `short_description`, `long_description`). Ha
  meg van adva, a válaszban `texts_available: {kind: {language: darab}}` szerepel. Ez csak
  darabszám, szöveg és forrás nincs benne. Ismeretlen szövegtípus: 422.

### Forráskapcsolatok és lineage

| Metódus, útvonal | Törzs | Válasz |
|---|---|---|
| `GET /source-relations?state=` | – | `[Relation]`; `state`: `suspected`, `below_threshold`, `confirmed_dependent`, `confirmed_independent` |
| `POST /source-relations/{id}/decision` | `{state: confirmed_dependent\|confirmed_independent, reason}` | `Relation`; az érintett értékek azonnal újraszámolódnak |
| `POST /source-relations/detect` | – | `{changed: int}` (kézi újrafuttatás) |
| `PUT /sources/{id}/lineage` | `{lineage_group: string\|null (≤64, [A-Za-z0-9._:-]), reason}` | `{id, lineage_group}` |

`Relation`: `id, source_a_id, source_b_id, shared_values, identical_values, identical_texts,
ratio (string), state, reason, decided_by, decided_at, updated_at`.

### Összevonás

| Metódus, útvonal | Törzs | Válasz |
|---|---|---|
| `POST /merges/preview` | `{survivor_id, merged_id}` | `Preview` |
| `POST /merges` | `{survivor_id, merged_id, preview_token, reason, acknowledge_variant_risk?: bool}` | `Merge` |
| `GET /merges?state=applied\|reverted&offset=` | – | `[Merge]`, legújabb elöl, 100-as lapok |
| `POST /merges/{id}/revert` | `{reason}` | `Merge` |

`Preview`: `survivor_id, merged_id, preview_token (64 hex), moves: {links, by_source},
values: [{attribute_key, outcome: same|new|would_conflict, survivor, merged}],
warnings: [{code: variant_attribute_differs|different_gtins|same_source_in_both, ...}],
blocking: [{code: verified_values_differ, attribute_key}], variant_risk: bool`.

`Merge`: `id, survivor_id, merged_id, state, variant_risk_acknowledged, moved: {links,
identities, observations, texts} (darabszám), reason, applied_by, applied_at, reverted_by,
reverted_at, revert_reason`.

Összevonási hibák: a megszokott boríték mellett `error.merge_error` (gépi kód) és
`error.details` is szerepel:

| HTTP | `merge_error` | Teendő a felületen |
|---|---|---|
| 422 | `same_product` | – |
| 404 | `not_found` | – |
| 409 | `not_active` | a termék már össze van vonva |
| 409 | `stale_preview` | új előnézet kérése |
| 409 | `blocked` (`details.blocking`) | előbb az ellenőrzött értéket kell rendezni |
| 409 | `variant_risk_not_acknowledged` (`details.warnings`) | kifejezett nyugtázás bekérése |
| 409 | `not_applied` | már vissza van vonva |
| 409 | `later_merge_first` (`details.later_merge_id`) | előbb a jelzett összevonást kell visszavonni |

### Szövegek

| Metódus, útvonal | Törzs | Válasz |
|---|---|---|
| `GET /products/{id}/texts?kind=&language=&usable=ai_generation&include_history=` | – | `[Text]` (alapból csak az aktuálisak) |
| `PUT /texts/{id}` | `{reason, verification?: unverified\|verified\|rejected, usage?: inherited\|reuse_allowed\|internal_only\|restricted, language?: kód\|unknown, pii_release?: bool}` | `Text` |

`Text`: `id, knowledge_product_id, link_id, source_id, source_key, kind, text, format,
language, language_confidence, language_method, verification, usage, pii_flags,
pii_reviewed_by, current, observed_at, superseded_at, usable_for_ai`.

### Személyesadat-felülvizsgálat

| Metódus, útvonal | Törzs | Válasz |
|---|---|---|
| `GET /pii-holds?offset=` | – | `{observations: [{type, id, knowledge_product_id, attribute_key, value, pii_flags, source_id}], texts: [{type, id, knowledge_product_id, kind, pii_flags, source_id}]}` |
| `POST /observations/{id}/pii-review` | `{release: bool, reason}` | `{id, released}`; már felülvizsgált: 409 |
| `PUT /texts/{id}` `pii_release` | lásd fent | – |

A visszatartott szöveg tartalma a `pii-holds` listában nem jelenik meg. Megnyitni a
`GET /products/{id}/texts` végponttal lehet, `reference.manage` joggal.

## Adatmodell (0016, a 0015-re épül)

- Új oszlopok:
  - `reference_product_sources.lineage_group`;
  - `knowledge_observations.identity_confidence`, `pii_flags`, `pii_reviewed_by`,
    `pii_reviewed_at`;
  - `knowledge_values.independent_sources` (alapérték 0).
- Új táblák: `knowledge_source_relations` (egyedi forráspár), `knowledge_merges`,
  `knowledge_texts` (MySQL-en MEDIUMTEXT; egyedi `link_id`+`kind`+`text_hash`).
- A migráció csak hozzáad. A 0014 és a 0015 változatlan, egyetlen Alembic-head van.
- Downgrade: elutasítja, mielőtt bármilyen DDL lefutna, ha van összevonás, szöveg- vagy
  személyesadat-döntés, forráskapcsolat-döntés vagy lineage-csoport. Ilyenkor a 0016 előtti
  mentést kell visszaállítani. Döntések nélkül a táblák és oszlopok törlődnek. A szövegek és a
  gyanús kapcsolatok újraépítéssel visszaállíthatók.

## Telepítés

1. Mentés az alkalmazás-adatbázisról (a `pinfo_db`-t nem érinti).
2. `alembic upgrade head` (0015 → 0016).
3. Egyszeri teljes újraépítés, hogy a meglévő termékekhez létrejöjjenek a szövegváltozatok, a
   személyesadat-jelzések és a forráskapcsolatok: `python -m app.knowledge rebuild`.
   A beállítások későbbi módosítása után a háttérfeladat automatikusan újraszámol; kézzel:
   `python -m app.knowledge rebuild --recompute`.
4. Visszaállítás: döntések nélkül `alembic downgrade 0015`; döntések után a mentés
   visszaállítása.

## Ellenőrzés

- `backend/tests/test_knowledge_02.py`: beállítások (jog, validáció, audit, újraszámolás),
  másolásgyanú (értékek és szövegek alapján), admin döntések, lineage, nyelvfelismerés és
  bővíthetőség, szövegváltozatok és előzmény, személyesadat-visszatartás és felülvizsgálat,
  változatvédelem, összevonás (előnézet, token, nyugtázás, tiltás, visszavonás, LIFO),
  jogosultság, 0016-os migráció.
- `scripts/mysql_knowledge02_check.py` (üres, loopback MySQL 8,
  `KNOWLEDGE02_FIXTURE_ACK=isolated-knowledge-02`): additív upgrade KNOWLEDGE-01 adatokon,
  MEDIUMTEXT, a másolásfelismerő self-join, összevonás és visszavonás MySQL-en, valamint a
  döntésvédett downgrade DDL nélküli elutasítása.
