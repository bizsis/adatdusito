# CATEGORY-01A – Termékkategorizálás és paraméter-kiegészítés: felmérés és architektúraterv

- **Státusz:** tervjavaslat, review-ra. Nem implementáció, nincs migráció, nincs kódváltozás.
- **Kiindulás:** `main` @ `80b0dce`.
- **Méretezési cél:** **legfeljebb 50 000 termék** egy ügyfél (tenant) termékállományában. Ez a Tulajdonos 2026-11-15-i pontosítása, a #12-ben szereplő „10 000+” helyett.
- **Feladat:** [#12](https://github.com/bizsis/adatdusito/issues/12)

---

## 0. Vezetői összefoglaló

**Mit találtunk.**
- **Jól használható alapok:**
  - Az importmotor megbízható: folytatható, idempotens, bérleti zárral (lease) dolgozik, és változásnaplót vezet.
  - Van egy saját, verziózott eMAG-katalógusmásolat: 2,85 millió értékrekord, kötelező/szűrő jelölések, megengedett értékek.
  - Van egy jóváhagyott, 13 főcsoportos navigációs fa 412 termékkategóriával.
  - **A 412 kategória mindegyikéhez van ellenőrzött eMAG-paraméterdonor** (503 profil). Ez a legnagyobb meglévő érték: a „melyik eMAG-kategóriától kapja a paraméterhelyeket” kérdés kategóriaszinten már meg van oldva.
- **Ami hiányzik:**
  - **Nincs termék–kategória kapcsolat.** A termék saját kategóriája ma csak egy szöveg a termék JSON-adatában.
  - **Nincsenek termékparaméterek.** Az importban meg nem feleltetett oszlopok (például „Teljesítmény (W)”) **nem kerülnek a termékre**, csak az adott importsor nyers adatában maradnak. A mérésünk szerint egy későbbi import ezeknek az értékeknek a változását nem jelzi.
  - Nincs státusz, bizalmi érték, kézi felülírás-védelem, termékszintű verzió (optimista zár) és AI-adatcsomag.

**Mit javaslunk** (minimális változtatással, a meglévőre építve):
1. **Két külön kapcsolat.**
   - A **saját kategória** (forrás- vagy webshop-kategória) változatlanul megmarad, külön rekordként, mert egy ügyfélnél jellemzően csak néhány száz különböző kategóriaútvonal van.
   - A **belső besorolás** egy jóváhagyott navigációs kategóriára és annak eMAG-paraméterdonorjára mutat.
   - A donor kiválasztása soha nem módosítja a saját kategóriát.
2. **Kategóriaszintű térkép elsőként.** Az ügyfél saját kategóriáit (pl. 300 útvonal) egyszer rendeljük a belső fához. Utána 50 000 termék besorolása egy olcsó illesztés, nem 50 000 egyedi döntés. Ez adja a „kevés kezelői munka” célt.
3. **Paraméterhelyek a donorból, felülírás nélkül.**
   - A termék saját paraméterei megmaradnak.
   - A donor hiányzó paraméterei üres helyként adódnak hozzá.
   - Szinonima- és mértékegységszótár akadályozza meg a duplikációt.
   - A kézi és jóváhagyott értékek zároltak.
4. **Két ügyféloldali státusz:** *Automatikusan besorolt* / *Ellenőrzést igényel*. Belül a pontos eredet és bizalmi érték is megmarad.
5. **AI-adatcsomag termékenként.** Kis, strukturált JSON: azonosítók, besorolás, paraméterhelyek állapottal, zárolt mezők, kutatási kulcsok. Nem 50 000 termék egy promptban.

**Skálázás 50 000 termékre.**
- A jelenlegi motor 50 000 sort kb. 107 mp alatt dolgoz fel (SQLite, egy worker, kb. 465 sor/mp), MySQL-en várhatóan lassabban.
- A tervezett kötegelt feldolgozással az **import + besorolás + paraméterhely-kiegészítés célja 15 percen belül** a VPS-en, 512 MB alatti worker-memóriával. A számokat MySQL 8-on, a leírt módszerrel kell igazolni.
- Tárhely: teljes kitöltöttségnél kb. **1 GB adatbázis-növekedés** ügyfelenként 50 000 terméknél (4. fejezet).

**Javasolt ütemezés.** 8 kisebb PR, 2 migrációval (0009, 0010; a sorszámokat a Vezér osztja ki). Az első szállítható érték: a saját kategória megőrzése, a kategóriatérkép és a termékenkénti besorolás státusszal (PR 1–3).

**Döntés kell** (11. fejezet), többek között:
- a belső besorolás célpontja a 412 jóváhagyott navigációs kategória legyen (javasolt), vagy közvetlenül eMAG-kategória
- az automatikus besorolás megengedett hibaaránya
- az AI-nak átadható adatok köre (árak és készlet kizárása javasolt)

---

## 1. Hatókör és feltételezések

- Első kör: saját termékdúsítás, egy-két saját ügyfél (tenant), külső ügyfél és fizetés nélkül. A modell tenant-kompatibilis: minden új tábla `tenant_id`-t kap.
- Méret: legfeljebb 50 000 termék tenantonként. Termékenként 20–70 eMAG-paraméter (a 6 legnagyobb profil 17–70 paraméteres), tipikusan kb. 40.
- A `pinfo_db` csak olvasható. Az alkalmazás a saját, verziózott katalógusmásolatát (`catalog_*` táblák) használja; ez ma is így működik (`catalog_store.py`).
- A jóváhagyott 13 főcsoportos fa (ADR-002) a belső, ügyfél felé mutatott taxonómia. Nem hozunk létre vele versengő kategóriarendszert.

## 2. A jelenlegi állapot tételes felmérése

### 2.1 Táblák és kapcsolatok (alkalmazás-adatbázis)

| Terület | Tábla (kód) | Mit tud ma | Ami hiányzik a célhoz |
|---|---|---|---|
| Tenant | `tenants`, `workspace_companies`, `workspace_webshops` (`access_models.py`) | ügyfél, cég, webshop erőforrások | a termékek nincsenek cégekhez vagy webshopokhoz kötve (DATABASE.md „Known modeling gap”) |
| Beszállító | `import_suppliers` | tenantonként | — |
| Importprofil | `import_profiles` (verziózott JSON-konfiguráció) | oszlop → belső mező megfeleltetés, kulcsmező, pénzügyi jóváhagyás, automatikus újrafelhasználás eltérésdetektálással (`drift`) | **egy belső mezőhöz egy oszlop**; nincs „paraméteroszlop” fogalom |
| Importfutás | `import_runs` | állapotgép (`uploaded → awaiting_approval → processing → completed/partial/failed`), `cursor`, `lease_until` + `task_token` bérlet, számlálók | — |
| Forrásfájl | `import_file_chunks` | 60 KB-os darabokban az adatbázisban, 90 napos megőrzés után kézi törlés | — |
| Importsor | `import_rows` (`run_id`, `line`) | nyers sor (`raw`), normalizált mezők, eredet (`provenance`), hibák, termékhivatkozás | futásonként **kb. 2,1 KB/sor** (mérve); nincs megőrzési szabály |
| Termék | `supplier_products` (`tenant_id`, `supplier_id`, `identity_key` egyedi) | `data` JSON a ~35 belső mezővel (`import_parser.FIELDS`), köztük `category` (beszállítói kategória szövegként), `attributes` (egyetlen oszlop) | **nincs kategóriakapcsolat, nincs paraméter, nincs revízió**; a meg nem feleltetett oszlopok nem kerülnek ide |
| Változásnapló | `import_changes` | mezőszintű before/after futásonként | csak importból; nincs felhasználói vagy automatizált eredet |
| Export | `store_engines`, `store_export_profiles` | exportmező-adminisztráció | UNAS-szinkron nincs (UNAS-INTEGRATION.md) |
| Katalógus | `catalog_versions`, `catalog_categories`, `catalog_category_nodes`, `catalog_parameters`, `catalog_category_parameters`, `catalog_category_parameter_entries`, `catalog_parameter_values`, `catalog_source_mappings` | **saját, verziózott eMAG-másolat**: kategóriák, paraméterek, kategória–paraméter kapcsolat `is_mandatory`, `is_filter`, `allow_new_value`, `display_order` jelöléssel; 2 847 054 értékrekord; aktív verzió | mértékegység és szinonima nincs külön adatként (a mértékegység a paraméternévben van) |
| Navigáció | `reference_data/web_navigation.json`, `curated_taxonomy.json` (13 csoport, **583 pont, 412 termékkategória**) | jóváhagyott fa | globális, nem tenantonként |
| Paraméterdonor | `reference_data/reviewed_parameter_bindings.json` + `parameter_profiles.py` | **mind a 412 termékkategóriához ellenőrzött eMAG-donor**, 503 profil, 18 kategória többprofilos; név- és azonosító-ellenőrzés, adminisztrátori felülbírálás elsőbbsége | csak kategóriaszinten; termékhez nincs kötve |
| Kategória-felülbírálás | `category_overrides` | adminisztrátori donor-hozzárendelés vagy -tiltás a navigációs pontokra | globális; nem ügyfélszintű |
| Egyeztetési szabályok | `reference_data/category_matching_rules.json` | címke-aliasok, útvonal-aliasok, „nincs fuzzy” elv | navigáció ↔ eMAG irányban; termékkategóriára nem |
| Forrásbizonyíték | `reference_sources`, `reference_observations` | megfigyelés, bizonyíték, állapot | — |

### 2.2 API-k

- **Import:** `/api/v1/imports/*`, 25 végpont: beszállítók, profilok, futások, sorok, jóváhagyás, akciók, hibalista, termékek, termékváltozások, előnézet, exportprofilok.
- **Termékek (csak olvasás):** `/api/v1/workspace/products`, kurzoros lapozás 25-ösével.
- **Navigáció és paraméterek:** `/api/v1/reference/navigation/*`
  - `/{node}/parameters?profile_emag_id=`: a donorprofil paraméterei
  - `/{node}/assignment`: adminisztrátori donor-hozzárendelés
- **Katalógus és referencia:** `/api/v1/reference/*`, `catalog_store.parameters()` és `values()`, kötelező/szűrő szerinti szűréssel és értéklapozással.
- **Termékbesoroláshoz, termékparaméterhez, státuszhoz és felülíráshoz nincs API.**

### 2.3 Aszinkron feldolgozás

- Celery + Redis (`worker.py`), a `supplier.import` taszk `acks_late` és `reject_on_worker_lost` beállítással.
- A futás bérlete 5 perces, és `task_token` védi. A `cursor` miatt egy leállt futás folytatható, a már tartós sort nem alkalmazza újra.
- Soronként jelenleg kb. 4–5 adatbázis-művelet fut: sor létezésének ellenőrzése, termék `SELECT … FOR UPDATE`, termék insert/update, sor insert, esetleg változás insert. Commit 100 soronként.
- Korlátok: `IMPORT_MAX_ROWS` 250 000, `IMPORT_MAX_PRODUCTS` 100 000, `IMPORT_MAX_BYTES` 50 MB. Az 50 000-es cél ezekbe belefér.

### 2.4 Mért alapvonal (jelenlegi motor)

Szintetikus CSV: 31 oszlop (SKU, név, márka, kategória, ár + 26 paraméteroszlop), egyetlen worker, SQLite memóriában, Python 3.12. A módszer a 12. fejezetben van. A MySQL-mérés a PR 7 része.

| Mérés | 10 000 sor | 50 000 sor |
|---|---:|---:|
| Fájlméret | 1,8 MB | 8,9 MB |
| Első import | 21,5 s (464 sor/s) | 107 s (466 sor/s) |
| Újraimport, minden termék létezik, 26 paraméter változott | — | 83 s |
| Worker RSS-növekedés | ~0 MB | **+172 MB** (230 → 402 MB) |
| `import_rows` JSON futásonként | 20,9 MB | **104,7 MB** |
| `supplier_products.data` | 2,1 MB | 10,5 MB |

**Következtetések:**
- A feldolgozás lineáris. Az 50 000-es import egyetlen workerrel is perces nagyságrendű, így a kategorizálás és a paraméter-kiegészítés hozzáadása nem igényel architektúraváltást, csak kötegelést.
- **Az újraimportban a 26 paraméteroszlop minden értéke megváltozott, mégsem keletkezett termékszintű változás**, mert ezek az oszlopok nincsenek a terméken. Ez a legfontosabb funkcionális hiány a paraméter-kiegészítéshez.
- Az RSS-növekedést profilozni kell. Valószínű ok az ORM-munkamenet növekvő identitástérképe; kötegenkénti `expunge`/új munkamenet a javaslat.
- Az `import_rows` 50 000 soros futásonként kb. 105 MB, napi feed esetén havonta több GB. Megőrzési szabály kell (8.6).

### 2.5 Összefoglalva: mi működik, mi hiányzik

| Képesség | Állapot |
|---|---|
| Fájlfeltöltés, elemzés, oszlopmegfeleltetés, profil-újrafelhasználás, folytatható import, változásnapló | ✅ működik |
| Saját eMAG-katalógus kötelező/szűrő/megengedett értékekkel, verziózva | ✅ működik |
| Jóváhagyott belső fa + kategóriánkénti ellenőrzött paraméterdonor | ✅ működik (globálisan) |
| Saját kategória **külön, stabil entitásként** | ❌ csak szöveg a termék JSON-jában |
| Ügyfélszintű kategóriatérkép (saját → belső) | ❌ |
| Termékenkénti besorolás, státusz, bizalmi érték, alternatívák | ❌ |
| Forrásparaméterek a terméken | ❌ csak az importsor nyers adatában |
| Paraméterhelyek a donorból, szinonima- és egységszótár | ❌ |
| Kézi felülírás védelme, optimista ütközésvédelem, revízió | ❌ |
| AI-adatcsomag | ❌ |

## 3. Fogalmi modell: két külön kategóriakapcsolat

```
               (marad, sosem írjuk felül)
 termék ──► SAJÁT KATEGÓRIA ───────────────► exportban (UNAS/webshop) ez megy ki
   │        (forrás/webshop útvonal)
   │                 │ kategóriatérkép (ügyfélszintű, jóváhagyható)
   │                 ▼
   └──► BELSŐ BESOROLÁS ──► jóváhagyott navigációs kategória (412 közül)
            (státusz,             │ ellenőrzött donorprofil (503)
             bizalom,             ▼
             alternatívák)   eMAG PARAMÉTERDONOR ──► paraméterhelyek (kötelező/opcionális,
                             (eMAG kategória-ID)       megengedett értékek)
```

- **Saját kategória:** amit a felhasználó importált (beszállítói vagy saját webshop/UNAS útvonal). Külön rekord, a termék csak hivatkozik rá. A rendszer **soha** nem módosítja, és az export ezt használja.
- **Belső besorolás:** termékenként egy navigációs kategória és egy donor eMAG-kategória. A donor csak a paraméterhelyeket szolgáltatja.
  - Ha a navigációs pontnak egy donora van (394 kategória), a donor automatikus.
  - Ha több (18 kategória, pl. töltők és USB-kábelek), a donor termékenként választandó. A profilokat nem mossuk össze; ez a meglévő elv.
- **Ha nincs saját kategória:** a termék közvetlenül kap belső besorolást. Ilyenkor a saját kategória üres marad, és az export a belső kategória nevét is használhatja (ez **üzleti döntés**, 11. fejezet).
- **Elsőbbség:** a termékszintű zárolt döntés megelőzi az ügyfél jóváhagyott kategóriatérképét, az pedig a globális szabályokat és javaslatokat.

**Miért a jóváhagyott navigáció a célpont, és nem közvetlenül az eMAG-kategória?**
- A 412 kategória mindegyikéhez már van ellenőrzött donor.
- Az ügyfél felé a 13 csoportos fa jelenik meg (ADR-002).
- Kevesebb a választási lehetőség: 412 a kb. 2 700 eMAG-kategória helyett.
- Vészkijárat: ha egy termék nem illik egyik navigációs pontba sem, „Ellenőrzést igényel” státuszt kap. Adminisztrátori döntéssel közvetlen eMAG-donor is megadható (`navigation_node_id` üres, `donor_emag_category_id` kitöltve).

## 4. Javasolt adatmodell (minimális változtatás)

Minden új tábla az `adatdusito_dev` adatbázisba kerül, `tenant_id` mezővel. Az összetett indexek `tenant_id`-vel kezdődnek. eMAG-azonosítóként a **stabil külső eMAG-ID**-t tároljuk, nem a katalógusverzió belső ID-jét, és mellé a döntéskori `catalog_version_id`-t.

### 4.1 Meglévő táblák bővítése (0009)

| Tábla | Új oszlop | Cél |
|---|---|---|
| `supplier_products` | `revision INT NOT NULL DEFAULT 1` | optimista ütközésvédelem: minden írás `WHERE revision = :r` feltétellel fut |
| `supplier_products` | `source_category_id BIGINT NULL` → `product_source_categories.id` | a saját kategória stabil hivatkozása. A `data.category` szöveg is marad; nem töröljük. |
| `supplier_products` | `source_attributes JSON NULL` | a meg nem feleltetett forrásoszlopok utolsó értéke `{fejléc: nyers érték}` alakban. Az importmotor tölti, és a változásuk bekerül az `import_changes` naplóba. |

Visszatöltés: a meglévő termékek `source_attributes` értéke az utolsó `import_rows.raw` sorból és a futás fejléceiből állítható elő. Ehhez egy egyszeri, folytatható job kell (PR 1).

### 4.2 Új táblák

**`product_source_categories`** – az ügyfél saját kategóriái (0009)

| Oszlop | Megjegyzés |
|---|---|
| `id` PK, `tenant_id` | |
| `origin` | `supplier` / `webshop` / `manual` |
| `supplier_id` / `webshop_id` NULL | honnan származik |
| `path_text` (≤ 1000) | eredeti útvonal, változatlanul |
| `path_key` CHAR(64) | normalizált útvonal SHA-256-ja (kisbetű, szóközök, elválasztók egységesítve) |
| `external_id` NULL | ha a forrásnak van saját kategória-ID-ja |
| `created_at` | |
| egyedi index: (`tenant_id`, `origin`, `supplier_id`, `webshop_id`, `path_key`) | |

**`category_maps`** – ügyfélszintű kategóriatérkép (0009)

| Oszlop | Megjegyzés |
|---|---|
| `tenant_id`, `source_category_id` (PK együtt) | |
| `navigation_node_id` NULL | a 412 közül |
| `donor_emag_category_id` NULL | ha a navigációs pont többprofilos, vagy adminisztrátori közvetlen donor esetén |
| `state` | `suggested` / `approved` / `ambiguous` / `rejected` |
| `method` | `admin`, `rule:<id>`, `alias`, `copied_from_identifier`, `model:<verzió>` |
| `confidence` DECIMAL(4,3) NULL | |
| `alternatives` JSON | legfeljebb 3 jelölt pontszámmal |
| `decided_by`, `decided_at`, `revision`, `catalog_version_id` | |

**`product_classifications`** – termékenkénti belső besorolás (0009)

| Oszlop | Megjegyzés |
|---|---|
| `product_id` PK → `supplier_products.id`, `tenant_id` | |
| `navigation_node_id` NULL, `donor_emag_category_id` NULL | |
| `status` | `auto` (ügyfélnek: *Automatikusan besorolt*) / `review` (*Ellenőrzést igényel*) / `approved` / `manual`. Az utolsó kettő is *Automatikusan besorolt*-ként vagy külön „Jóváhagyva” címkével jelenik meg: UI-döntés. |
| `method`, `confidence`, `alternatives` JSON | mint fent |
| `locked` BOOL | `approved`/`manual` esetén mindig igaz: import és automatika nem írhatja felül |
| `basis_map_revision` NULL | melyik térképverzióból származott; a térkép módosulásakor a nem zárolt termékek újraszámolhatók |
| `revision`, `decided_by`, `decided_at`, `catalog_version_id` | |
| index: (`tenant_id`, `status`), (`tenant_id`, `navigation_node_id`) | |

**`parameter_aliases`** – szinonima- és mértékegységszótár (0010)

| Oszlop | Megjegyzés |
|---|---|
| `id`, `tenant_id` NULL | NULL = globális, csak adminisztrátor kezelheti |
| `label_key` | normalizált forráscímke, pl. `teljesitmeny`, `power` |
| `unit` NULL | forrásegység, pl. `W`, `kW`, `cm` |
| `emag_parameter_id` | célparaméter (stabil eMAG-ID) |
| `scope_emag_category_id` NULL | ha csak egy donorban érvényes (pl. „méret” egészen mást jelent ruhánál és tévénél) |
| `conversion` JSON NULL | pl. `{"factor": 1000, "to": "W"}`; csak ismert, determinisztikus átváltás |
| `state`, `decided_by` | |
| egyedi index: (`tenant_id`, `scope_emag_category_id`, `label_key`, `unit`) | |

**`product_parameter_values`** – paraméterhelyek és értékek (0010)

| Oszlop | Megjegyzés |
|---|---|
| `product_id`, `slot_key` (PK együtt), `tenant_id` | `slot_key` = `emag:<parameter_id>` vagy `src:<label_key>` (donorban nem szereplő forrásparaméter, amely megmarad) |
| `emag_parameter_id` NULL, `donor_emag_category_id` NULL | |
| `source_label`, `source_raw` NULL | eredeti fejléc és érték, változatlanul |
| `value` NULL, `unit` NULL, `value_id` NULL | normalizált érték; `value_id`, ha egy megengedett eMAG-értékkel egyezik |
| `origin` | `source` / `added_slot` / `user` / `ai` / `import_rule` |
| `state` | `present` / `missing` / `conflict` / `invalid` (pl. nem megengedett érték, ahol `allow_new_value = false`) |
| `mandatory` BOOL | a donorból, a gyors szűréshez denormalizálva |
| `locked` BOOL | kézi vagy jóváhagyott értéknél igaz |
| `evidence` JSON NULL | későbbi AI- vagy webes forrás: URL, idézet-hash, időpont |
| `revision`, `updated_by`, `updated_at`, `source_run_id`, `source_line` | |
| index: (`tenant_id`, `state`, `mandatory`), (`tenant_id`, `emag_parameter_id`) | |

**`product_events`** – revízió és adatváltozás-követés (0009, a `product_parameter_values` eseményei 0010-től)

| Oszlop | Megjegyzés |
|---|---|
| `id`, `tenant_id`, `product_id`, `revision` | |
| `kind` | `classification`, `parameter`, `field_override`, `import` |
| `actor_id` NULL, `job_id` NULL, `run_id` NULL | |
| `before`, `after` JSON | |
| `created_at` | index: (`tenant_id`, `product_id`, `id`) |

Az `import_changes` tábla változatlanul marad, a `product_events` ezt egészíti ki a nem importból származó eseményekkel. A UI-ban egy idővonalon jelennek meg.

**`product_jobs`** – a besorolás és paraméter-kiegészítés folytatható jobjai (0009)

Az `import_runs` mintáját követi: `tenant_id`, `kind`, `state`, `cursor` (utolsó feldolgozott `product_id`), `counters`, `lease_until`, `task_token`, `catalog_version_id`, `input_fingerprint`, `error`, `created_by`, időbélyegek.

### 4.3 Miért EAV a paraméterértékekhez, és nem termékenkénti JSON?

| Szempont | EAV-tábla (javasolt) | Termékenkénti JSON |
|---|---|---|
| „Hány terméknél hiányzik kötelező paraméter X kategóriában?” | indexelt lekérdezés | teljes tábla átolvasása, JSON-feldolgozás |
| Egy érték zárolása vagy felülírása, optimista zár | soronként | az egész dokumentum ütközik |
| AI-válasz részleges alkalmazása | soronként | dokumentum-merge |
| Méret 50 000 termék × 40 helyen | 2 M sor | 50 000 nagyobb sor |
| Írási költség | kötegelt upsert | kevesebb sor |

A kezelői munka lényege a „mi hiányzik, mi ütközik” szűrés és az értékszintű zárolás, ezért EAV-t javaslunk. A nyers forrásoszlopok ezzel szemben JSON-ként maradnak a terméken (`source_attributes`), mert azokat csak megőrizzük és összevetjük.

### 4.4 Kézi felülírás és eredet

- Kategória: `product_classifications.locked`.
- Paraméter: `product_parameter_values.locked` + `origin = user`.
- Alapmezők (név, leírás stb.): **első körben nem** írhatók felül az alkalmazásban. Ha később kell, egy `product_field_overrides` tábla (`product_id`, `field`, `value`, `locked`, `revision`) következik, ugyanezzel a mintával.
- Szabály minden automatikus íróra (import, szabály, AI): a `locked = true` sort soha nem írja. Ha az új forrásérték eltér a zárolt értéktől, `conflict` jelzés és esemény keletkezik, az érték nem változik.

## 5. A kategóriaegyeztetés döntési elve

Sorrend termékenként; az első találat dönt:

1. **Zárolt termékdöntés** (`approved`/`manual`) → marad. Új import nem írja felül.
2. **Jóváhagyott kategóriatérkép** a termék saját kategóriájára → `status = auto`, `method = map`. Ha a térkép `ambiguous` (egy saját kategória több belső kategóriát fed le, pl. „Kiegészítők”), akkor a 3–5. lépés jön, de csak a térkép által megengedett jelöltek közül.
3. **Azonosító-egyezés:** ugyanabban a tenantban egy jóváhagyott besorolású termék ugyanazzal a GTIN-nel vagy (márka + MPN) párossal → `auto`, ha egyetlen ilyen besorolás van; ellentmondás esetén `review`. Név alapján **nincs** összevonás (ez a meglévő elv).
4. **Determinisztikus szabályok:**
   - a saját kategóriaútvonal normalizált tokenjei a navigációs nevekhez és útvonal-aliasokhoz (a `category_matching_rules.json` mintájára, ügyfélszintű aliasokkal bővíthetően)
   - terméktípus- és kulcsszószabályok a névre és a márkára
   - Csak akkor `auto`, ha **egyetlen** jelölt marad, és a szabály nem „gyenge”. Különben `review`, legfeljebb 3 alternatívával.
5. **Javaslat** (későbbi fázis: szövegbeágyazás vagy AI) → mindig `review` státusz alternatívákkal, amíg a kalibráció mást nem igazol.

**Hatékonyság.** Az 1–4. lépés zöme kategóriaszinten fut. Egy új ügyfélnél először a saját kategóriák (pl. 300) kapnak javaslatot, az operátor ezeket hagyja jóvá. Ez néhány száz döntés 50 000 helyett, és utána a termékek tömegesen öröklik a besorolást. A kevés kezelői munkát ez biztosítja.

**Küszöbök és kalibráció.** A bizalmi értékek kezdetben **nem empirikusan validáltak**, ezért az indulásnál csak az 1–3. lépés és a 4. lépés egyértelmű szabályai adnak `auto` státuszt. A kalibrációs terv:
1. **Aranyhalmaz:** legalább 1 000 termék kézi besorolással, rétegzetten. Minden főcsoportból, a többprofilos kategóriákból és a „nehéz” saját kategóriákból is (pl. „Egyéb”, „Akció”). Két független értékelő, az eltéréseket egyeztetjük.
2. **Mérés módszerenként és pontszámsávonként:** precizitás, lefedettség (hány % kap `auto`-t), és a hibák kategóriapárjai.
3. **Küszöb:** az a legalacsonyabb pontszám, ahol a precizitás **Wilson-alsó határa** eléri a célt. Például ≥ 98% `auto`-precizitás; a célértéket a 11. fejezet szerint az üzlet dönti el.
4. **Élő mérés:** az `auto` besorolások kézi javítási aránya kategóriánként és hetente. Ha a cél fölé emelkedik, az adott módszer vagy kategória automatikusan `review` módba kerül.
5. **Újrakalibrálás** katalógusverzió-váltáskor, új szabálykészletnél, illetve negyedévente.

**Nem egyértelmű kategória.**
- A termék `review` státuszt kap a 3 legjobb alternatívával.
- **Donor csak egyértelmű besorolás után** rendelődik hozzá. Bizonytalan esetben nem adunk hozzá paraméterhelyeket, mert rossz donor rossz helyeket hozna, és azokat később takarítani kellene.
- Többprofilos navigációs kategóriánál (18) a donort szabály választja (pl. „kábel” vagy „töltő” kulcsszó). Ha ez nem sikerül, `review`, és a profilok nem keverednek.

### 5.1 eMAG-paraméterdonor keresése a saját kategória módosítása nélkül

1. A donor a **besoroláson** él (`product_classifications.donor_emag_category_id`), a saját kategóriát nem érinti.
2. A donor forrása a navigációs pont ellenőrzött profilja (`parameter_profiles.resolve_profiles`). Az adminisztrátori felülbírálás itt is elsőbbséget élvez (`category_overrides`).
3. Ha az ügyfél saját kategóriája egy navigációs pontnál szűkebb, és létezik pontosabb eMAG-kategória, a kategóriatérkép közvetlen donort is rögzíthet (`category_maps.donor_emag_category_id`). Ez csak jóváhagyással lehetséges, és a navigációs fa nem változik.
4. A donor eMAG-azonosító **stabil külső ID**. Katalógusverzió-váltáskor egy ellenőrző job jelzi, ha a donor megszűnt vagy átnevezték (a `resolve_profiles` figyelmeztetéseinek mintájára). Csendes helyettesítés nincs.

## 6. Paraméter-kiegészítés

Termékenként, a donor ismeretében:

1. **Helyek:** a donor `catalog_category_parameter_entries` sorai (név, kötelező, szűrő, `allow_new_value`, sorrend).
2. **Forrásparaméterek illesztése** (a `source_attributes` és a megfeleltetett `attributes` mező):
   - a. Címke normalizálása: kisbetű, ékezet nélkül, zárójeles egység leválasztva, pl. „Teljesítmény (W)” → `teljesitmeny` + `W`.
   - b. `parameter_aliases` keresése: ügyfélszint → globális → donorspecifikus hatókör.
   - c. Pontos egyezés a donor paraméternevével normalizálva.
   - d. Ha egyik sem talál, a paraméter **forrásparaméterként megmarad** (`slot_key = src:<label>`), és nem dobjuk el.
3. **Érték:**
   - A nyers érték mindig megmarad.
   - A normalizált érték csak determinisztikus átalakítással készül: szám, ismert egységátváltás, egyezés a megengedett értékkel.
   - Ha a donor nem enged új értéket, és nincs egyezés: `state = invalid`, az érték megmarad, és ellenőrzést igényel.
4. **Hiányzó helyek:** a donor minden olyan paramétere, amelyhez nincs érték, `state = missing` üres helyként kerül be (kötelező jelöléssel).
5. **Duplikáció tilalma:** termékenként egy `emag:<id>` hely van. Ha két forrásoszlop ugyanarra a paraméterre illeszkedik és eltérő értékű, `conflict` lesz, nem két hely.
6. **Felülírás tilalma:**
   - `present` állapotú, nem zárolt értéket új forrásérték csak akkor ír felül, ha ugyanabból a forrásoszlopból érkezik (a beszállítói feed frissít). Ez eseményt is ír.
   - Zárolt értéket semmi nem ír felül.
   - Donorváltáskor (átsorolás) a régi donor üres helyei törlődnek, a kitöltött értékek `src:` helyként megmaradnak.

## 7. AI-ra átadható termékenkénti adatcsomag (javaslat)

Termékenként egy JSON, jellemzően 5–15 KB. Kötegben több termék is mehet egy kérésben, de mindegyik külön objektumként, és a válasz termékenként azonosított.

```json
{
  "schema": "adatdusito.product-enrichment/1",
  "product_ref": "p_8f3c2a...",            
  "revision": 7,
  "catalog_version_id": 12,
  "language": "hu",
  "identity": {"gtin": "5900000000000", "mpn": "XYZ-100", "brand": "Példa", "model": "XYZ 100",
               "name": "Példa XYZ 100 vezeték nélküli porszívó"},
  "own_category": {"path": "Háztartás > Takarítás > Porszívók", "read_only": true},
  "classification": {"navigation_node_id": "web-item-…", "navigation_path": ["Háztartási gépek", "…", "Porszívók"],
                     "donor_emag_category_id": 123, "status": "review", "confidence": null,
                     "alternatives": [{"navigation_node_id": "…", "score": null}]},
  "parameters": [
    {"slot": "emag:4521", "name": "Teljesítmény", "unit": "W", "mandatory": true,
     "allowed_values": {"mode": "open"}, "value": "650", "origin": "source", "state": "present",
     "locked": false, "source": {"label": "Teljesítmény (W)", "raw": "650"}},
    {"slot": "emag:4530", "name": "Porzsák típusa", "mandatory": false,
     "allowed_values": {"mode": "closed", "sample": ["Porzsákos", "Porzsák nélküli"], "lookup": "values/4530"},
     "value": null, "state": "missing", "locked": false},
    {"slot": "emag:4533", "name": "Szín", "value": "Fekete", "origin": "user", "state": "present",
     "locked": true}
  ],
  "unmatched_source_attributes": [{"label": "Garancia", "raw": "2 év"}],
  "forbidden_changes": ["own_category", "identity.gtin", "slots.locked", "price", "stock"],
  "research": {"keys": ["gtin", "mpn+brand"], "preferred_sources": ["manufacturer", "supplier"],
               "max_sources": 3, "require_citation": true},
  "response_contract": "adatdusito.product-enrichment-result/1"
}
```

**A válasz** (`…-result/1`) termékenként és helyenként tartalmaz:
- javasolt értéket
- forrás-URL-t
- rövid idézet-hash-t (nem teljes szöveget)
- bizalmi értéket
- indoklást

Javasolhat besorolás-alternatívát is, de **nem módosíthat**: az alkalmazás validálja a választ (megengedett értékek, zárolt helyek, egységek), és minden elfogadott javaslat `origin = ai` + `evidence` mezővel kerül be. Kategóriánál ez mindig `review`.

**Adatvédelem:**
- Az ár, a beszerzési ár, a készlet és a beszállító neve **alapértelmezésben nem kerül** a csomagba.
- A `product_ref` nem a belső ID, hanem tenantonként sózott hash.
- A csomagot egy szerveroldali builder állítja össze a jogosultságellenőrzött tenant-hatókörből.

**Költségkorlát:** a „research” csak a `missing`/`invalid`/`conflict` helyeket tartalmazó termékekre fut, és a csomag `input_fingerprint`-je alapján változatlan termékre nem ismétlődik (AI-ENGINE.md „research only when justified by changes”).

## 8. Skálázási terv 50 000 termékre

### 8.1 Feldolgozási lánc

`import` → `besorolás (product_jobs:classify)` → `paraméterhelyek (product_jobs:slots)` → (később) `AI-csomag`.

- Mindegyik lépés önálló, folytatható job: bérlet + `task_token` + `cursor = utolsó product_id`, a meglévő `ImportRun` mintájára.
- Az import végén csak a **változott** termékek kerülnek a következő lépés sorába (`ImportChange` vagy `source_attributes` delta alapján).

### 8.2 Kötegelés és streaming

- **Kötegméret:** 500 termék, kulcskészletes lapozással (`WHERE product_id > :cursor ORDER BY product_id LIMIT 500`). Nincs `OFFSET`, nincs teljes betöltés.
- **Kötegenként:**
  - 1 lekérdezés a termékekre
  - 1 a besorolásokra
  - 1 a meglévő paraméterhelyekre (`IN (…)`)
  - kategória- és aliasszótár memóriában tenantonként (kb. néhány ezer sor)
  - donorparaméterek LRU-cache-ben (412 kategória × kb. 40 paraméter)
- **Írás:** kötegelt upsert (`INSERT … ON DUPLICATE KEY UPDATE … WHERE locked = 0 AND revision = …`; MySQL-en `VALUES()`/alias forma, SQLite-tesztben dialektusfüggő ág) és egy commit kötegenként.
- **Import:** a soronkénti 4–5 lekérdezés helyett kötegelt előtöltés (`identity_key IN (…)`, meglévő `ImportRow` sorok egy lekérdezéssel) és kötegelt beszúrás. Ezzel a kerekítési utak (round-trip) száma kb. 10×-esére csökken. A meglévő idempotencia (`ImportRow` PK) és bérlet változatlanul marad.
- **Memória:** kötegenként új ORM-munkamenet vagy `expunge_all()`. Az XLSX `read_only=True` és a CSV streamelése már ma is így működik.

### 8.3 Idempotencia és újraindíthatóság

- Minden írás kulcsa determinisztikus: (`product_id`), (`product_id`, `slot_key`). Az ismételt köteg ugyanazt az eredményt adja.
- A `cursor` csak a commit után lép. Ha a worker elvész, a bérlet lejár, és a köteg újrafut.
- Egy jobot az `input_fingerprint` azonosít (tenant, katalógusverzió, térképrevízió, szabálykészlet-verzió). Ugyanazzal a fingerprinttel futó job nem indul újra.

### 8.4 Optimista ütközésvédelem

- A UI minden írásnál elküldi a termék vagy sor `revision` értékét. Eltérés esetén 409 a válasz, a friss állapottal.
- Az automata írók csak `locked = 0 AND revision = :r` feltétellel írnak. Ha ütközés van, a sort kihagyják, és a következő futás újra kiértékeli.
- Tömeges jóváhagyás (pl. egy kategóriatérkép-tétel) tranzakciónként legfeljebb 500 terméket ír, és jobként fut.

### 8.5 Indexek (a 4. fejezet táblái mellett)

- `supplier_products (tenant_id, source_category_id)`
- `product_classifications (tenant_id, status, navigation_node_id)`
- `product_parameter_values (tenant_id, state, mandatory)` és (`tenant_id`, `emag_parameter_id`)
- `product_events (tenant_id, product_id, id)`
- A listanézet kulcskészletes lapozással fut (a meglévő `/workspace/products` kurzoros mintájára).

### 8.6 Becsült erőforrásigény (50 000 termék, egy tenant)

| Tétel | Becslés | Alap |
|---|---:|---|
| `product_parameter_values` | 2 M sor × kb. 250 B ≈ **0,5 GB** + indexek kb. 0,3 GB | 40 hely/termék; mérendő |
| `product_classifications` | 50 000 × kb. 300 B ≈ 15 MB | |
| `source_attributes` | ≈ 50 000 × 1 KB ≈ 50 MB | a 26 oszlopos mérés alapján |
| `product_events` | eseményenként kb. 300 B; első kitöltéskor kb. 2 M esemény kötegelve (≈ 0,6 GB) | **javaslat:** a kezdeti kitöltés egyetlen összesítő eseményt kapjon termékenként, így ez kb. 15 MB |
| `import_rows` | **105 MB / 50 000 soros futás** (mérve) | megőrzés: az utolsó 3 futás + 30 nap, régebbiek tömörített archívba vagy törlésre (döntés) |
| Worker-memória | cél < 512 MB | mérve: a mai import +172 MB 50 000 sornál, kötegeléssel korlátos |
| Futásidő | cél: import + besorolás + helyek < 15 perc egy workerrel | a mai import kb. 2 perc SQLite-on; MySQL-en mérendő |

### 8.7 Tenant-elválasztás és adatvédelem

- Minden új táblában `tenant_id` mező van, és minden lekérdezés a meglévő `tenant(who)` és jogosultsági (`products.read`/`imports.manage`) mintával szűr.
- A tesztek kötelezően ellenőrzik, hogy egy idegen tenant terméke nem olvasható és nem írható.
- Globális szótár (`parameter_aliases.tenant_id IS NULL`) csak adminisztrátori joggal írható, és nem tartalmaz ügyfélértéket, csak címkét és egységet.
- Az AI-csomag builder csak engedélyezett mezőket ad át (7. fejezet).
- A jobok tenantonként külön sorban futnak, és egy tenant nem foglalhatja le az összes workert. Ehhez egyidejűségi korlát kell a `product_jobs` állapotgépen, tenantonként egy futó job.

## 9. Javasolt PR-bontás

| # | Gazda | Tartalom | Migráció | Elfogadás (ellenőrizhető) |
|---|---|---|---|---|
| 1 | Claude | `product_source_categories`, `category_maps`, `product_classifications`, `product_events`, `product_jobs`; `supplier_products.revision`, `source_category_id`, `source_attributes`; az importmotor menti a forráskategóriát és a meg nem feleltetett oszlopokat, és eseményt ír a változásukról; visszatöltő job | **0009** | migráció fel és le üres és adatos MySQL 8-on; a meglévő termékek és változásnapló érintetlen; a 2.4 újraimport-tesztben a 26 oszlop változása látszik; tenant-izolációs tesztek |
| 2 | Claude | besorolási szolgáltatás (5. fejezet 1–4. lépés), kategóriatérkép-javaslat, `product_jobs:classify`; API: lista és szűrés státuszra, termékbesorolás módosítása `revision` értékkel, kategóriatérkép jóváhagyása | — | determinisztikus tesztek minden lépésre; a zárolt döntést import nem írja felül (regressziós teszt); 409 revízióütközésnél; 50 000 szintetikus termék < 3 perc SQLite-on |
| 3 | Codex | UI: kategóriaoszlop, két státusz, szűrés, alternatívák, kategóriatérkép tömeges jóváhagyása | — | böngészőteszt: kézi módosítás után új import nem változtat |
| 4 | Claude | `parameter_aliases`, `product_parameter_values`; slot-kitöltés (6. fejezet), egységnormalizálás, `product_jobs:slots`; API | **0010** | nincs duplikált hely; zárolt érték változatlan; konfliktus jelzése; a donor váltásakor a kitöltött értékek megmaradnak |
| 5 | Codex | UI: paraméterek, hiányzó/kötelező szűrés, kézi szerkesztés, zárolás | — | böngészőteszt |
| 6 | Claude | kalibrációs eszköz: aranyhalmaz-import, metrikák, Wilson-alsó határ, riport | — | reprodukálható riport a fixture aranyhalmazon |
| 7 | Claude | importmotor kötegelése, profilozás, MySQL 8 benchmark (CI-ben opcionális éjszakai job) | — | 50 000 sor MySQL-en: célidő és RSS < 512 MB; az eredmény bit-azonos a soronkénti motorral (golden-teszt) |
| 8 | Claude | AI-csomag builder (csak export, AI-hívás nélkül) + válaszvalidátor | — | séma-validáció; tiltott mezők hiánya; zárolt hely nem módosítható a validátoron át |

A sorrendi függőség: 1 → 2 → 3, valamint 1 → 4 → 5. A 6., 7. és 8. a 2. után párhuzamosítható.

## 10. Migrációk és kockázataik

| Migráció | Tartalom | Kockázat | Csökkentés |
|---|---|---|---|
| 0009 | 5 új tábla + 3 oszlop a `supplier_products` táblán | 50 000+ sorú `ALTER TABLE` a MySQL-ben; zárolási idő | MySQL 8 `ALGORITHM=INSTANT` a NULL-os és alapértékes oszlopokra; előtte mentés; próba másolaton |
| 0009 visszatöltés | `source_attributes` az `import_rows` alapján | hosszú futás; a régi futásoknál hiányzó fejléc | folytatható job, nem a migrációban; a hiányzó adat `NULL`, nem kitalált |
| 0010 | 2 új tábla | a `product_parameter_values` mérete | csak új tábla, a meglévőt nem érinti; a kitöltés jobként, kötegelve |
| Mindkettő | downgrade | adatvesztés az új táblákból | a downgrade csak üres vagy archivált állapotban fusson; dokumentált |

## 11. Nyitott üzleti döntések

1. **A belső besorolás célpontja:** a 412 jóváhagyott navigációs kategória (javasolt), vagy közvetlenül az eMAG-kategória (kb. 2 700)?
2. **Az automatikus besorolás elfogadható hibaaránya:** pl. ≤ 2% (98%-os precizitás). Ez határozza meg a kalibrált küszöböt.
3. **A jóváhagyás láthatósága:** a jóváhagyott vagy kézi besorolás az ügyfélnek „Automatikusan besorolt” vagy külön „Jóváhagyva” címkét kapjon?
4. **Termékek saját kategória nélkül:** az export a belső navigációs kategóriát használja helyette, vagy maradjon üres?
5. **Mértékegység-átváltás:** szabad-e automatikusan átváltani (pl. kW → W), vagy csak jelezni?
6. **Megőrzés:** `import_rows` (javaslat: utolsó 3 futás + 30 nap) és `product_events` (javaslat: 1 év).
7. **AI-adatkör:** árak, készlet és beszállító kizárva (javaslat); a leírás mehet-e teljes szöveggel?
8. **Kalibrációs aranyhalmaz:** ki címkéz, mennyi idő áll rendelkezésre (kb. 1 000 termék ≈ 8–12 munkaóra két értékelővel)?
9. **Több beszállítós termékazonosság:** ugyanaz a GTIN két beszállítónál egy termék legyen, vagy kettő? Ma kettő (`identity_key` beszállítónként). A besorolás másolása (5. fejezet, 3. lépés) ezt nem dönti el, csak felhasználja.

## 12. Mérési módszer (reprodukálható)

**Szintetikus generátor:**
- determinisztikus mag (seed)
- 31 oszlop: SKU, név, márka, kategória-útvonal (300 különböző × 7 alkategória), ár, 26 numerikus paraméteroszlop mértékegységgel a fejlécben
- második változat: ugyanazok a kulcsok, minden paraméter megváltozik

**Futtatás:**
- **Alapvonal (2.4):** az importteszt-fixtúrával (`backend/tests/test_supplier_import.py`: `upload`, `approve`, `advance`), SQLite memóriában, Python 3.12, egyetlen folyamatban. Mérés: `time.perf_counter`, `resource.getrusage().ru_maxrss`, és `SUM(LENGTH(...))` a JSON-oszlopokra.
- **Elfogadási mérés (PR 7):**
  - eldobható MySQL 8 konténer, a VPS-ével azonos verzió és `innodb_buffer_pool_size`
  - 1 Celery worker
  - mérve: sor/s, kötegenkénti p95-időtartam, RSS, `information_schema.TABLES` adat- és indexméret
  - `EXPLAIN` a 8.5 lekérdezéseire
  - a listanézet p95-válaszideje 50 000 terméknél

Az eredményt minden PR a saját leírásában közli; regresszió esetén (>20% lassulás) a PR nem olvasztható be.

---

### Hivatkozott kód
`backend/app/import_models.py`, `import_engine.py`, `import_parser.py`, `import_api.py`, `workspace_views.py`, `models.py` (catalog_*), `catalog_store.py`, `parameter_profiles.py`, `fixed_navigation.py`, `web_navigation.py`, `unified_categories.py`, `reference_data/*.json`, `docs/architecture/DATABASE.md`, `docs/modules/AI-ENGINE.md`, `docs/modules/IMPORT-ENGINE.md`, `docs/decisions/ADR-002-reference-taxonomy.md`, `docs/reviewed-parameter-profiles.md`.
