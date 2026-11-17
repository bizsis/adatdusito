# KNOWLEDGE-01 – Az Adatdúsító önállóan tanuló terméktudásbázisa

- **Ág:** `claude/knowledge-01`, az RC-03-ra (`d0e2c2c`) építve.
- **Migráció:** `0014` (a Tulajdonossal egyeztetve), a lánc `0011 → 0012 → 0013 → 0014`.
- **Felület:** a KNOWLEDGE-UI-01 webes adminisztrációs felületet a Codex készíti. Ez a dokumentum a közös API-szerződés.

## Elvek

- **Nincs párhuzamos terméktár.** A tudásbázis a meglévő rekordokat kapcsolja össze és konszolidálja:
  - a `reference_products` (RC-03 referenciatár);
  - a tenantok `supplier_products` rekordjai;
  - a 03A `product_parameter_values` értékei.

  Forrásnyilvántartásként a `reference_product_sources` szolgál.
- **Források:**
  - Minden engedélyezett referenciaforrás tanít: `approved_enrichment`, `enrichment_enabled` és `contribution = automatic`.
  - Tenantonként egy automatikusan létrejövő ügyfélforrás is tanít (`kind = tenant_import`, `tenant:<id>`, a tulajdonosi szabály szerint alapból aktív).
  - Ha egy forrás elveszíti az engedélyét, a következő újraépítéskor visszavonódnak a megfigyelései (`source_withdrawn` esemény).
- **Csak átvehető terméktudás tárolódik:**
  - a márka és a termékparaméterek (a referenciából az RC-03 `shareable` jelölésű paraméterei);
  - a 03A-ban kitöltött (`present`) eMAG-paraméterek.

  Ár, készlet, az áruházi cikkszám, vevőcsoport-adat és integrációs azonosító soha nem kerül be.
- **Hitelesség:** egy érték **soha nem válik hitelessé** pusztán attól, hogy több forrásban szerepel. A `verified` állapot csak emberi döntésből jöhet:
  - a tenant felhasználójának jóváhagyott, zárolt javításából (`origin = user`, `locked`);
  - adminisztrátori döntésből.

## Működés

1. **Azonosítás.** Sorrend:
   - érvényes (ellenőrzőszámos) GTIN;
   - márka + gyártói cikkszám;
   - márka + név.

   A kulcsok hajtogatva tárolódnak a `knowledge_identities` táblában. Érvénytelen GTIN (pl. `8,71999E+12`) nem azonosít.
2. **Összekapcsolás.** Egy rekord egy klaszterhez tartozik (`knowledge_links`: módszer és identitás-confidence).
   - Ha egy rekord azonosítói több klaszterre mutatnak, a legerősebb egyezés nyer, és `merge_candidate` esemény keletkezik; **automatikus összevonás nincs**.
   - **Ugyanazon a forráson belül** a márka + név egyezés nem köt össze két rekordot, mert ez változat (méret, szín), nem azonos termék. Ezt csak a GTIN teheti meg.
   - Az adminisztrátor által elhelyezett rekordot (`decided_by`) az automatika nem mozgatja.
3. **Megfigyelések** (`knowledge_observations`): rekordonként és tulajdonságonként egy aktuális állítás; a korábbiak `current = false` mellett megmaradnak.
   - **Kulcsok:** `brand`; `emag:<id>`; `unas:<csoport>/<név>`.
   - **Tanulás a megfeleltetésekből:** ha egy UNAS-paraméterhez jóváhagyott eMAG→UNAS megfeleltetés tartozik, a paraméter az `emag:<id>` kulcsot kapja. Így a referenciaexport és a tenantok paraméterei összehasonlíthatók.
   - **Mértékegységek:** mm/cm/m → cm, g/kg → kg, ml/l → l. A tenantoldali mértékegység a paraméter nevéből is kiolvasható, pl. `Szélesség (mm)`.
4. **Konszolidálás** (`knowledge_values`):
   - Az értékek normalizált alak szerint csoportosulnak.
   - **Megfigyelés-confidence:** a forrás megbízhatósága (`trust_level`, alapértelmezés: referencia 0,6, tenant 0,5, jóváhagyott javítás 0,9) × az identitás-confidence (GTIN 1, MPN 0,9, márka + név 0,6).
   - **Csoport-confidence:** `1 − Π(1 − c)` a különböző forrásokra, **legfeljebb 0,95**.
   - **Állapotok:**

     | Állapot | Mikor |
     |---|---|
     | `candidate` | egyetlen érték |
     | `conflict` | eltérő értékek; nyitott ellentmondás, a confidence megfeleződik |
     | `verified` | jóváhagyott javítás vagy adminisztrátori döntés |

     A `verified` értéket egy később érkező eltérő állítás nem írja felül: `verified_challenged` ellentmondás nyílik.
   - **Elutasított érték** (`rejected_values`) soha nem kerül vissza.
5. **Ellentmondások** (`knowledge_conflicts`):
   - A jelöltek forrásszámmal és confidence-szel szerepelnek.
   - Automatikusan akkor zárulnak le, ha a források egyezővé válnak.
   - Emberi döntéssel a feloldás `verified` állapotot eredményez.
6. **Felhasználás** (`enrichment_plan`):
   - `reuse`: ellenőrzött tény;
   - `suggest`: ellentmondásmentes jelölt a küszöb felett;
   - `research`: hiányzó, ellentmondásos vagy gyenge érték.

   A `research_avoided` azt mutatja, hány AI-kutatás spórolható meg. Más tenant rekordja vagy forrása nem jelenik meg.
7. **Visszakövethetőség:**
   - minden változásnak és döntésnek eseménye van (`knowledge_events`);
   - minden adminisztrátori döntés auditált (`audit_events`: `knowledge.*`);
   - a megfigyelések a forrásrekordig visszavezethetők (`link → member_kind/member_id`, `source_id`).
8. **Automatika és idempotencia:**
   - Referenciaimport után forrásszintű, beszállítói import után tenantszintű újraépítés kerül sorba (`knowledge.rebuild` Celery-feladat).
   - Broker nélkül ez nem lassítja az importot: a hiba naplózódik, és a következő futás pótolja.
   - Változatlan rekord nem ír semmit.

## API-szerződés (KNOWLEDGE-UI-01)

**Előtag:** `/api/v1/knowledge`.

- **Jogosultság:** az adminisztrációhoz `reference.manage` (rendszerszint) kell, az enrichment-tervhez `products.read`.
- **Védelem:** minden módosító hívás CSRF/Origin-védett, a válaszok `no-store` fejlécet kapnak.
- **Hibák:** 401/403 (jog), 404 (nincs ilyen), 409 (állapot), 422 (bemenet), magyar `error.message`-dzsel.

| Metódus és útvonal | Bemenet | Válasz |
|---|---|---|
| `GET /stats` | – | `products`, `links`, `values{candidate,conflict,verified}`, `open_conflicts`, `sources[{id,key,kind,usage_status,contribution,permitted,links}]` |
| `GET /products?q=&conflicts=&offset=&limit=` | `q`: név vagy azonosító (GTIN/MPN részlet); `conflicts=true`: csak nyitott ellentmondással; `limit` 1–100 | `{items[{id,status,display_name,brand,links,open_conflicts,…}], total, offset}` |
| `GET /products/{id}` | – | a termék, valamint `identities[{kind,value}]`, `links[{id,member_kind,member_id,source_id,source_key,tenant_id,method,confidence,decided_by}]`, `values[{id,attribute_key,label,value,value_norm,status,confidence,support_sources,observations,verification_basis,verified_by,verified_at,rejected_values,observations_detail[{id,link_id,source_id,source_key,value,unit,value_norm,origin,confidence,current,observed_at,superseded_at}]}]`, `conflicts[…]` |
| `GET /products/{id}/events?offset=` | – | `[{id,kind,value_id,link_id,actor_id,details,created_at}]` (100/lap) |
| `GET /conflicts?state=open\|resolved&offset=` | – | `[{id,value_id,knowledge_product_id,attribute_key,kind,candidates[{value_norm,display,sources,confidence,approved}],state,resolution,reason,resolved_by,resolved_at,created_at}]` |
| `POST /conflicts/{id}/resolve` | `{value_norm, reason?}`; a `value_norm` a jelöltek egyike | a feloldott ellentmondás és `value` (`verified`, `admin_decision`). 409: már lezárva; 422: ismeretlen jelölt |
| `POST /values/{id}/verify` | `{value_norm?, reason?}` | érték (`verified`). 409: nincs érték; 422: ismeretlen jelölt |
| `POST /values/{id}/reject` | `{reason?}` | érték: az elutasított alak a `rejected_values`-be kerül, és a következő jelölt lép a helyére |
| `POST /links/{id}/unlink` | `{reason?}` | `{link_id, knowledge_product_id}`: a rekord saját, végleges (`manual`) klasztert kap |
| `POST /rebuild` | `{source_id?}` vagy `{tenant_id?}` | megadott forrásnál vagy tenantnál szinkron `{queued:false, counters}`; teljes újraépítésnél `{queued:true}` a workerben |
| `POST /enrichment-plan` | `{gtin? , mpn?+brand? , brand?+name?, attributes[1..500], threshold=0.8}` | `{knowledge_product_id, match, reuse[], suggest[], research[{attribute_key, reason: unknown\|conflict\|low_confidence}], research_avoided}` |

**Eseménytípusok:**
- `product_created`, `linked`, `relinked`, `merge_candidate`, `unlinked`;
- `value_changed`, `value_verified`, `value_rejected`;
- `conflict_opened`, `conflict_resolved`;
- `source_withdrawn`.

**Javasolt képernyők:**
1. áttekintés (`/stats`);
2. terméklista és -kereső;
3. termékadatlap: értékek forrásonkénti megfigyelésekkel, eseménynapló, link bontása;
4. ellentmondás-sor feloldással;
5. forrásengedélyek. Ez már létező végpont: `PUT /api/v1/unas/reference-sources/{id}/usage`, ugyanazzal a `reference.manage` joggal.

## Ellenőrzés

- **`backend/tests/test_knowledge.py`** (11 teszt):
  - azonosítás (GTIN, MPN, márka + név, érvénytelen GTIN);
  - forrásközi összekapcsolás;
  - csak átvehető kulcsok;
  - idempotencia;
  - merge-jelölt automatikus összevonás nélkül;
  - változat ugyanabban a forrásban;
  - mértékegység-normalizált egyezés (0,8 confidence, nem `verified`);
  - ellentmondás és adminisztrátori feloldás;
  - tanulás a jóváhagyott javításból és az elutasításból;
  - enrichment-terv (reuse, suggest, research; tenant-felhasználóval, forrásadat nélkül);
  - forrásengedély visszavonása és kézi linkbontás;
  - normalizálás és confidence-szabályok;
  - `0014` additív migráció és védett downgrade.
- **Eldobható MySQL 8.0.46:**
  - lánc oda-vissza: `0014 → 0013 → 0011 → 0014 → 0013 → 0014`;
  - a meglévő MySQL-ellenőrzések: 56/56, `exit=0`, 7/7.
- **Valódi méretű próba** (az Engermarket-export, 18 454 termék, eldobható MySQL; tartós adatbázisba nem került adat):

  | Futás | Eredmény |
  |---|---|
  | 1. újraépítés | 18 454 rekord összekapcsolva, 74 543 megfigyelés, 74 540 érték; 420 s |
  | 2. újraépítés | 0 változás; 94 s (idempotens) |
  | Klaszterek | 18 453 (egy GTIN-duplikátum két cikkszámon összekapcsolva) |
  | Ellentmondások | 0 |

  A változat-szabály előtt ugyanez a futás 27 márka + név egyezést és 25 téves ellentmondást adott ugyanazon áruházon belül. Ez a valós adatban talált hiba vezetett a szabályhoz.

## Teljesítmény és üzemeltetés

- Az első teljes építés 18 454 referenciatermékre egy helyi gépen néhány perc; ezért fut háttérfeladatként.
- Az ismételt futás csak összehasonlít.
- A tenantokat import után inkrementálisan, csak a saját rekordjaikra építi újra.
- **Telepítés** (a Tulajdonos döntése):
  1. mentés;
  2. `docker compose run --rm migrate` (`0014`);
  3. a backend és a worker újraindítása;
  4. egyszeri `python -m app.knowledge rebuild` (vagy `POST /api/v1/knowledge/rebuild`).

## Nyitott kérdések

1. A forrás-megbízhatósági alapértékek (referencia 0,6, tenant 0,5, javítás 0,9) és a `suggest`-küszöb (0,8) üzleti hangolása.
2. A `merge_candidate` események kezelése: kell-e felületi összevonási művelet (a mostani változat szándékosan nem von össze)?
3. Mely tulajdonságok kerüljenek még a tudásba (pl. név- és leírásváltozatok), és milyen szabállyal.
