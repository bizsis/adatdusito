# KNOWLEDGE-02 – terv: konfigurálható confidence, másolásvédelem, kézi összevonás, szövegváltozatok

**Ez tervdokumentum, nem megvalósítás.**

- **Alap:** a Tulajdonos 2026-11-17-i döntései a KNOWLEDGE-01 három nyitott kérdéséről.
- **Kiindulási állapot:** RC-04 = `codex/knowledge-ui-01` @ `5b1f295`: KNOWLEDGE-01 `0014` + KNOWLEDGE-UI-01 `0015`.
- **Változatlan marad:**
  - a `0014` és a `0015` migráció;
  - a KNOWLEDGE-01 működése és a `/api/v1/knowledge` végpontok viselkedése;
  - a KNOWLEDGE-UI-01 `/api/v1/knowledge-admin` szerződése.
- **Minden bővítés additív.**

## 1. Döntések és következményeik

| Döntés | Következmény a tervben |
|---|---|
| A 0,6 / 0,5 / 0,9 alapértékek és a 0,8-as küszöb maradnak, de később adminisztrációs felületen konfigurálhatók lesznek | Új `knowledge` beállításcsoport a meglévő `system_config` / `settings_api` mechanizmusban (**migráció nélkül**). A változás audit naplózott, és a confidence-értékek újraszámítását váltja ki. |
| Egymástól másoló források ne növelhessék indokolatlanul a megbízhatóságot | A források függőségi csoportokba („leszármazási család”) kerülnek. Egy családon belül a megfigyelések **egy forrásnak** számítanak. A gyanús másolást a rendszer automatikusan felismeri; ez a confidence-et csak csökkentheti, növelni soha nem tudja. |
| Kézi, rendszergazdai összevonás előnézettel, jóváhagyással, auditnaplóval, visszavonással; bizonytalan automatikus összevonás továbbra sincs; a változatok ne olvadjanak össze | Előnézet → tokenes jóváhagyás → végrehajtás, a visszavonáshoz szükséges teljes mozgásnaplóval. A változatkockázat külön figyelmeztetés és kifejezett nyugtázás nélkül blokkoló. A változatvédelem az automatikus márka + név egyezésre is kiterjed. |
| A nevek és leírások változatai is kerüljenek a tudásbázisba: eredeti szöveg, nyelv, forrás, ellenőrzési állapot, felhasználási jog; minden változat megmarad; később ezekből készülnek a magyar AI-leírások | Új `knowledge_texts` tábla. A szövegek **nem konszolidálódnak**: minden forrásváltozat külön, verziózott sor. A tényleges felhasználási jog a forrásjog, a szövegszintű felülbírálás és a személyesadat-gyanú együttes eredménye. Külön lekérés adja vissza az AI-generáláshoz felhasználható szövegeket. |

## 2. Migráció (külön egyeztetés szükséges)

Új adatmodell-elem csak új migrációval jöhet. **Javasolt sorszám: `0016`** (`0015 → 0016`); a kiosztás a Tulajdonos vagy a Vezér döntése. Additív bővítés:

| Elem | Tartalom |
|---|---|
| `reference_product_sources.lineage_group` | `VARCHAR(64) NULL` – a rendszergazda által megadott leszármazási család (pl. `enger`). Üres: önálló forrás. |
| `knowledge_source_relations` | `source_a_id`, `source_b_id` (rendezett pár), `shared_values`, `identical_values`, `identical_texts`, `ratio`, `state` (`detected`\|`confirmed_dependent`\|`confirmed_independent`), `decided_by`, `decided_at`, `updated_at`; egyedi pár |
| `knowledge_observations.identity_confidence` | `NUMERIC(5,4) NULL` – a link confidence-e a megfigyelés idején. Ebből a beállítás változásakor újraszámolható a confidence. |
| `knowledge_values.independent_sources` | `INT NOT NULL DEFAULT 0` – a független (családonként egyszer számolt) források száma |
| `knowledge_merges` | `survivor_id`, `merged_id`, `state` (`applied`\|`reverted`), `preview_token`, `variant_risk_acknowledged`, `moved` (JSON: link-, identitás- és megfigyelés-azonosítók, a merged termék előző állapota), `reason`, `applied_by/at`, `reverted_by/at`, `revert_reason` |
| `knowledge_texts` | `knowledge_product_id`, `link_id`, `source_id`, `kind` (`name`\|`short_description`\|`long_description`), `text` (MEDIUMTEXT), `text_hash` (sha256), `format` (`plain`\|`html`), `language`, `language_confidence`, `language_method` (`heuristic`\|`declared`\|`admin`), `verification` (`unverified`\|`verified`\|`rejected`), `usage` (`inherited`\|`reuse_allowed`\|`internal_only`\|`restricted`), `pii_flags` (JSON), `current`, `observed_at`, `superseded_at`, `decided_by`, `decided_at`; egyedi `(link_id, kind, text_hash)` |

**A meglévő `0014`-es mezők felhasználása:**
- összevonásnál a `knowledge_products.status = merged` és a `merged_into_id`;
- a forrásonkénti megbízhatóság felülbírálása a `reference_product_sources.trust_level`.

**Downgrade:**
- a táblákat a saját indexeikkel együtt dobja el (MySQL-biztos, a RELEASE-02 tanulsága szerint);
- megtagadja a futást, ha alkalmazott összevonás, szövegdöntés vagy megerősített forrásreláció létezik, és mindezt az első DDL előtt ellenőrzi (a `0015` mintája szerint).

## 3. Konfigurálható confidence és másolásvédelem

**Beállítások** (`system_config` csoport: `knowledge`; alapértékek = a mai viselkedés):

```json
{"trust_reference": 0.6, "trust_tenant": 0.5, "trust_approved_correction": 0.9,
 "suggest_threshold": 0.8, "confidence_cap": 0.95,
 "copy_detection": {"min_shared_values": 50, "identical_ratio": 0.9, "min_identical_texts": 20},
 "variant_attributes": ["méret", "szín", "kivitel", "változat", "size", "color", "colour",
                        "variant", "kiszerelés"]}
```

- **API:**
  - `GET /api/v1/system/settings` (meglévő, kiegészül a `knowledge` csoporttal);
  - `PUT /api/v1/system/settings/knowledge` (új, a `classification` csoport mintájára).
  - Jogosultság: `system.settings.manage`. Validáció: 0 ≤ trust ≤ 1, a küszöb a plafon alatt.
- **Hatás:**
  - a módosítás `settings.change` auditot ír;
  - `knowledge.rebuild(recompute=True)` futást ütemez, amely a tárolt `identity_confidence` és az új trust-értékek alapján számolja újra a megfigyeléseket és az értékeket. Linkeket és döntéseket nem módosít.

**Másolásvédelem:**
1. **Kifejezett család:** az azonos `lineage_group`-ba tartozó források egy forrásnak számítanak.
2. **Automatikus felismerés** (az újraépítés végén, forráspáronként):
   - a közös klaszterekben vizsgálja, hány azonos tulajdonság nyers értéke **szövegre pontosan** egyezik (`identical_values / shared_values`);
   - és hány hosszú leírás (`text_hash`) azonos.
   - A küszöb felett `detected` reláció jön létre, és a pár egy családnak számít.
3. **Rendszergazdai döntés:** `confirmed_dependent` (marad egy család) vagy `confirmed_independent` (újra külön számít; tudatos, auditált döntés).
4. **Számítás:**
   - `combine()` a különböző családokra fut, családon belül a legnagyobb confidence-et veszi;
   - az `independent_sources` mező a független családok számát mutatja.
   - **Az automatikus felismerés csak csökkentheti a confidence-et.** A `verified` állapotot továbbra is csak emberi döntés adhatja.

**API:**
- `GET /api/v1/knowledge/source-relations?state=` – a jelentett párok számokkal;
- `POST /api/v1/knowledge/source-relations/{id}/confirm` – `{state: confirmed_dependent|confirmed_independent, reason}`;
- `PUT /api/v1/knowledge/sources/{id}/lineage` – `{lineage_group, reason}`. Saját végpont, hogy a Codex `/knowledge-admin` forrásszerkesztése változatlan maradjon; a felület mellette jelenítheti meg.

## 4. Kézi összevonás

**Előnézet:** `POST /api/v1/knowledge/merges/preview`, bemenet: `{survivor_id, merged_id}`. Semmit nem módosít.

Válasz:
- `preview_token` (a két klaszter aktuális állapotának hash-e);
- `moves`: linkek, identitások és megfigyelések száma forrásonként;
- `values`: tulajdonságonként `same` / `new` / `would_conflict`, a jelöltekkel;
- `warnings[]`;
- `blocking[]`.

**Blokkoló esetek (409):**
- ugyanaz a termék;
- már összevont klaszter;
- **két egymásnak ellentmondó, ellenőrzött (`verified`) érték** ugyanarra a tulajdonságra – előbb fel kell oldani.

**Változatkockázat (figyelmeztetés, kifejezett nyugtázás nélkül blokkol):**
- eltérő érvényes GTIN-ek;
- eltérő érték egy változatjellegű tulajdonságon (a `variant_attributes` lista, a nevek alapján);
- a két klaszterben ugyanannak a forrásnak egy-egy rekordja van (egy forrás egy terméket egyszer listáz).

**Végrehajtás:** `POST /api/v1/knowledge/merges`, bemenet: `{survivor_id, merged_id, preview_token, reason (kötelező), acknowledge_variant_risk?}`.
- Ha az állapot az előnézet óta változott, eltérő token: 409.
- **Tranzakción belül:**
  - a linkek, identitások és megfigyelések átkerülnek;
  - a merged termék `status = merged`, `merged_into_id` beállítva;
  - a túlélő értékei újraszámolódnak;
  - a merged termék saját értékei és döntései **érintetlenül megmaradnak**, mert a visszavonás ezekre áll vissza;
  - `knowledge_merges` sor jön létre a mozgásnaplóval, `merge_applied` esemény és `knowledge.merge` audit készül.
- **Az automatikus újraépítés** nem bonthatja szét és nem helyezheti át a kézi döntéssel áthelyezett linkeket (a meglévő `decided_by` szabály).

**Visszavonás:** `POST /api/v1/knowledge/merges/{id}/revert`, bemenet: `{reason}`.
- A mozgásnapló alapján pontosan visszaállítja a linkeket, identitásokat és megfigyeléseket. A merged termék újra aktív, és mindkét fél újraszámolódik.
- **Ha egy későbbi összevonás a túlélőt érinti, 409:** előbb azt kell visszavonni (LIFO).
- Az összevonás utáni, a túlélőn hozott emberi döntések megmaradnak, és a visszavonás eseménye hivatkozik rájuk.
- Esemény: `merge_reverted`; audit: `knowledge.merge_revert`.

**Lista:** `GET /api/v1/knowledge/merges?state=&offset=`.

**Változatvédelem az automatikus linkelésben** (viselkedésszigorítás):
- A márka + név egyezés akkor sem köt, ha a rekord és a cél klaszter egy változatjellegű tulajdonságban eltér.
- Ilyenkor új klaszter jön létre, és `variant_candidate` esemény keletkezik.
- A GTIN- és MPN-egyezés nem változik.

## 5. Nevek és leírások (`knowledge_texts`)

**Források:**
- referenciatermékek: `name`, `short_description`, `long_description` (az RC-03 `shareable` mezői);
- ügyfélforrások: a beszállítói termék `name` és `description` mezője.

A KNOWLEDGE-UI-01 webes feltöltései a `reference_products`-on keresztül automatikusan beérkeznek.

**Tárolás:**
- **Minden változat külön sor**, nincs konszolidáció.
- Azonos szöveg ugyanattól a forrásrekordtól nem ismétlődik (`text_hash`).
- Változáskor az előző `current = false` lesz, és megmarad.

**Nyelv:**
- Heurisztikus felismerés (magyar, angol, román, német: ékezetek és stopszavak), `language_confidence` és `language_method = heuristic` mellett.
- A rendszergazda felülírhatja (`admin`).
- Külső szolgáltatás nincs. Új függőség csak külön döntéssel jöhet.

**Formátum:** HTML esetén az eredeti HTML marad; a felhasználáskor egyszerű szöveges kivonat is képezhető.

**Személyes adat:** az e-mail-, telefon- és adószám-mintákat a rendszer `pii_flags`-be jelöli. Jelölt szöveg az AI-felhasználásból kizárt, amíg a rendszergazda felül nem vizsgálja. Teljes körű DLP-garanciát nem vállalunk, ahogy a KNOWLEDGE-UI-01 sem.

**Felhasználási jog** (tényleges = mind teljesül):
- a forrás jogosult és engedélyezett (`approved_enrichment`, `enrichment_enabled`, `contribution = automatic`);
- a szöveg saját `usage` értéke nem `internal_only` vagy `restricted`;
- nincs nyitott `pii_flags`;
- `verification` nem `rejected`.

**API:**
- `GET /api/v1/knowledge/products/{id}/texts?kind=&language=&usable=ai_generation` – `usable=ai_generation` mellett csak a fentiek szerint felhasználható, nem elutasított szövegek, forrással és jogalappal;
- `POST /api/v1/knowledge/texts/{id}/verify|reject` – `{reason}`;
- `PUT /api/v1/knowledge/texts/{id}` – `{usage?, language?, pii_reviewed?, reason}`.

**Enrichment-terv:** a `/enrichment-plan` opcionális `texts: ["name","long_description"]` kérésére `texts_available` darabszámot ad vissza nyelvenként, felhasználható szövegekre. Szövegtartalmat más tenantnak nem ad ki, csak összesítést. A szöveges tartalmat a későbbi, szerveroldali AI-generálási lépés kapja meg közvetlenül.

## 6. Egyeztetés a KNOWLEDGE-UI-01-gyel (Codex)

- **A `/api/v1/knowledge-admin` szerződés nem változik.** A forráslista DTO-ja kiegészülhet (additívan) a `lineage_group` és a `relations_detected` mezővel; erről a Codexszel egyeztetni kell, a végpontot a Codex tartja fenn.
- **Új felületi elemek** (KNOWLEDGE-UI-02, Codex), mind a fenti `/api/v1/knowledge` végpontokra:
  - beállítások;
  - forráscsalád és relációk;
  - összevonás (előnézet, nyugtázás, végrehajtás, visszavonás);
  - szövegváltozatok fül.
- **A meglévő hookot nem kell módosítani:** az importot követő ütemezés marad a `knowledge_bridge.schedule_source` → `knowledge.schedule`; a szövegek ugyanebben a futásban frissülnek.
- **DTO-kiegészítések (additív):**
  - `value_dto.independent_sources`;
  - a terméklap `merged_into_id`, `texts_summary{kind: {language: count}}` és `merges[]` mezői.

## 7. Megvalósítási sorrend (javaslat)

| Szakasz | Tartalom | Előfeltétel |
|---|---|---|
| K2-A | `knowledge` beállításcsoport és újraszámítás (migráció nélkül) | – |
| K2-B | `0016`: forrásrelációk, `identity_confidence`, `independent_sources`, családalapú `combine`, változatvédelem az automatikus linkelésben | a migrációs sorszám kiosztása |
| K2-C | kézi összevonás (`knowledge_merges`) | K2-B |
| K2-D | `knowledge_texts`, nyelv, PII-jelölés, AI-felhasználási lekérés | K2-B |
| UI-02 | Codex felületei | K2-A…D API-jai |

**Tesztelés szakaszonként:**
- SQLite API-tesztek (jogosultság, CSRF, 404/409/422, audit);
- másolási forgatókönyvek: két forrás azonos szövegekkel, illetve független egyezéssel;
- összevonás: előnézet, tokenütközés, változatkockázat, ellenőrzött ütközés, visszavonás és LIFO;
- szövegek: változatok megőrzése, nyelv, PII, jogosultság;
- a teljes KNOWLEDGE-01 és KNOWLEDGE-UI-01 regresszió;
- MySQL-lánc `0015 ↔ 0016` és a meglévő MySQL-ellenőrzések;
- valódi méretű próba az Engermarket-exporttal eldobható adatbázison.

## 8. Nyitott kérdések a Tulajdonos felé

1. **A `0016` migrációs sorszám kiosztása** (vagy más szám).
2. **A másolásfelismerés küszöbei:** 50 közös érték, 90% azonosság, 20 azonos hosszú leírás. Megfelelők-e kiindulásnak?
3. **Nyelvkészlet:** elég-e első körben a magyar, angol, román és német?
4. **A személyes adatot gyanítható szövegek:** felülvizsgálatig kizártak az AI-felhasználásból. Egyetért-e ezzel?
