# RELEASE-CANDIDATE-03 – TEMPLATE-01 + UNAS-REF-01 és a központi tudásbázis alapjai

- **Ág:** `claude/release-candidate-03`, alap: `codex/release-candidate-02` @ `0580a74`.
- **PR célága:** az RC-02.
- Nincs `main`-merge és nincs éles telepítés.

## Integráció

| Lépés | Commit | Megjegyzés |
|---|---|---|
| TEMPLATE-01 merge | `5904b4d` | `codex/template-01` @ `38b347d`, `--no-ff`, nem squash |
| UNAS-REF-01 merge | `d5c2308` | `claude/unas-reference-database` @ `8c9a24f`, `--no-ff`. Egy ütközés volt: `scripts/mysql_rc02_import_check.py` zárósora. Feloldás: az adatbázis az aktuális Alembic-headen van, és a `0012` az ősei között. |
| Migrációs lánc | `5a55749` | A `0013` `down_revision` értéke `"0012"`. Lánc: `0011 → 0012 → 0013`, egyetlen head (`0013`). |
| Sablon ↔ sématár | `b9f91bf` | `app/unas_registry.py` és egy minimális bekötés a `template_engine.build`-be |
| Tudásbázis-alapok | `7845c47` | a tulajdonosi döntés szerint, lásd lent |

**A Codex-fájlok közül csak a sablonbekötéshez szükséges két hely változott** a `template_engine.py`-ban (a tulajdonos integrációs megbízása alapján):
- az UNAS-munkamezők annotálása;
- a paraméteroszlop elhelyezése és a több donorra kiterjedő értékmásolás.

A TEMPLATE-01 mind a 16 eredeti tesztje változatlanul zöld.

## A sablongenerátor és a sématár

- **UNAS-munkamezők:** a legutóbb regisztrált UNAS-sémából kapnak metaadatot: `in_registry`, `unas_field_id`, `registry_requirement` és annak forrása. A fejlécük nem változik.
  - A TEMPLATE-01 saját `Alternatív Kategória 1.` mezője `in_registry: false` jelölést kap, mert az exportban `Alternatív Kategória 1` szerepel (pont nélkül).
- **eMAG-paraméter jóváhagyott megfeleltetéssel** az UNAS-fejlécet kapja (pl. `Paraméter: Szélesség||num|…`). Ha a cél már oszlop (forrásoszlop, UNAS-munkamező vagy egy másik donor ugyanoda mutató paramétere), **nem kerül be még egyszer**:
  - a kapcsolat a meglévő oszlopra kerül (`emag_parameters`);
  - a közös paraméteroszlop minden érintett donor sorainál átveszi az értéket.
- **Megfeleltetés nélkül, illetve üres sématárnál** a viselkedés pontosan a TEMPLATE-01-é.
- **Letöltés:** a CSV- és XLSX-fejléc egyedi; ezt teszt és MySQL-próba is ellenőrzi.

## Központi tudásbázis: a tulajdonosi döntés és az alapok (KNOWLEDGE-01 előtt)

| Követelmény | Most elkészült alap | KNOWLEDGE-01 feladata |
|---|---|---|
| Az engedélyezett források automatikusan aktívak | Az importált referenciaexport `approved_enrichment`, `usage_basis = owner_policy:2026-11-17`, `enrichment_enabled = true`. Az adminisztrátor `restricted`/`revoked` döntése auditált (`administrator_decision`), és az újraimport nem írja felül. | – |
| A jogosultság forrásszintű nyilvántartása | `usage_status`, `usage_basis`, `trust_level`, `contribution`, `tenant_id` (a tenant saját feltöltései forrásként) | a tenant-importok forrásként való automatikus felvétele |
| Ügyfélspecifikus, személyes vagy nem újrahasznosítható adat nem kerül át | mezőszintű `shareable` jelölés. **Átvehető:** terméknév, kategória, leírások, képek, mértékegységek, termékparaméterek, EAN. **Nem átvehető:** az áruház cikkszáma, ár, készlet, vevőcsoport, láthatóság, SEO, rendszerértékek, integrációs azonosítók (`CONNESTIC_ID`, `Forrás`). A vevőcsoport-oszlopok be sem kerülnek. | ugyanez a beszállítói importmezőkre |
| Azonos termékek felismerése | GTIN-index (ellenőrzőszámmal), márka és név; a megbízhatóság a találatban | kereszt-forrásos összevonás, további azonosítók |
| Eredet és megbízhatóság | forrás, import-futás, nyers sor és hash, `confidence`, `trust_level` | megbízhatósági modell |
| Bizonytalan vagy ellentmondásos érték nem hiteles | `reference_products.verification = unverified` alapból; a keresés csak javasol (`overwrites_supplier_data: false`), árat/készletet nem ad | összehasonlítás a meglévő tudással, jóváhagyásból és javításból tanulás, ellentmondások külön kezelése |

**Nem épült párhuzamos tanulórendszer.** A KNOWLEDGE-01 ezekre a táblákra és jelölésekre építhet. A `0013` helyben bővült, mert még egyetlen tartós adatbázison sem futott.

## Ellenőrzés

| Mi | Eredmény |
|---|---|
| Backend és eszközök (`PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py`) | a PR-leírásban |
| Frontend: `npm run lint`, `npm run test:lint` (3), `npm test` (14), `tsc --noEmit`, `vite build` | mind sikeres |
| Böngészőtesztek (helyben, teljes csomag) | a PR-leírásban |
| Alembic | egyetlen head `0013`; lánc `0011 → 0012 → 0013` (`test_single_alembic_head_and_0013_chain`) |
| MySQL 8.0.46 (eldobható, helyi) | `0013 → 0012 → 0011 → 0013 → 0011 → 0013` hibátlan; `mysql_release02_downgrade_check.py` 56/56; `mysql_release01_check.py` `exit=0`; `mysql_rc02_import_check.py` 7/7, benne a **TEMPLATE-01 MySQL-generálás és XLSX-letöltés** |
| Referenciaimport ismételhetősége (valódi export, eldobható MySQL) | 1. futás: 18 454 új, 0 hiba (82 s); 2. futás: 18 454 változatlan (39 s); a forrás `approved_enrichment` / `owner_policy:2026-11-17`; 50 átvehető mező |
| Sablon és sématár (`test_rc03_integration.py`) | regisztrált séma, három jóváhagyott megfeleltetési út, egyedi fejléc, értékmásolás két donorral, CSV- és XLSX-letöltés; üres sématárnál változatlan TEMPLATE-01-viselkedés |
| Docker image-ek | a CI-ban |

## Telepítés (a Tulajdonos döntése; most nem történik)

1. Mentés.
2. `docker compose run --rm migrate` (`0011 → 0012 → 0013`).
3. A backend, a worker és a frontend újraépítése.
4. Referenciaimport: `python -m app.reference_products import <fájl> --store-key engermarket-unas-hu --version 20261117-084322`.
