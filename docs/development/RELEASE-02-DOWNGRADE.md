# RELEASE-02 – MySQL-biztos 0009–0011 downgrade (B1)

- Forrás: [#35](https://github.com/bizsis/adatdusito/issues/35).
- A hiba leírása: RELEASE-01 (#34, `docs/development/RELEASE-01-READINESS.md`, B1).
- Állapot: 2026-11-16.
- Nem volt `main`-merge, staging- vagy VPS-telepítés, és a `pinfo_db`-be sem írtunk.

## Hiba és ok

MySQL 8-on a 0009, a 0010 és a 0011 downgrade adat nélkül is elbukott ezzel a hibával:

```text
1553 Cannot drop index …: needed in a foreign key constraint
```

MySQL-en egy idegen kulcshoz kell egy olyan index, amelynek a kulcs oszlopa az első oszlopa. A downgrade-ek viszont előbb az indexet dobták el, és csak utána a táblát vagy a kulcsot. A 0009 downgrade ráadásul félbemaradt: három táblát már eldobott, a revízió 0009 maradt, és a séma használhatatlanná vált. SQLite-on (a CI-ban) a hiba nem jön elő.

## Javítás (csak a downgrade-ágak)

| Migráció | Változás |
|---|---|
| 0009 | A `category_maps` és a `product_source_categories` előtt nincs külön `drop_index`. A `supplier_products`-on előbb az `fk_product_source_category` kulcs, utána az `ix_supplier_products_source_category_id` index esik el. |
| 0010 | A `product_parameter_values` és a `parameter_aliases` előtt nincs külön `drop_index`. |
| 0011 | Az öt új tábla előtt nincs külön `drop_index`. A `product_jobs` kezelése: lásd lent. |

**0011, `product_jobs`.** A tényleges MySQL-séma (`information_schema`) szerint:

- 0010-en a 0009-ben név nélkül létrehozott `tenant_id → tenants` kulcsot a MySQL implicit `tenant_id` indexe szolgálja ki;
- a 0011 `uq_product_job_idempotency (tenant_id, kind, idempotency_key)` indexe ezt az implicit indexet csendben kiváltja.

A downgrade ezért MySQL-en a következő sorrendben halad:

1. `fk_product_job_created_by` eldobása;
2. a név nélküli `tenant_id` kulcs eldobása (a nevét a séma alapján keresi meg);
3. a unique index és a három oszlop eldobása;
4. a kulcs név nélküli visszavétele.

Így a MySQL ugyanazt az implicit indexet és kulcsnevet hozza létre: a 0010-es séma pontosan az eredeti, és egy későbbi 0011 upgrade ismét kiváltja az indexet.

Egy korábbi változat, amely az indexet explicit `CREATE INDEX`-szel állította vissza, az első kört átvitte, de a `0011 → 0010 → 0011 → 0010` lépésnél elbukott. Az explicit index ugyanis megmarad, és a séma eltér. A regresszió ezt az esetet is lefedi.

SQLite-on a 0011 változatlanul a korábbi batch-utat használja.

**Nem változott:**
- az upgrade-ágak;
- a `down_revision` lánc;
- a döntésvédelmek (0009: kategóriadöntés; 0010: paraméterdöntés; 0011: jóváhagyás);
- a meglévő adatok.

## Függőségek

- **PR-lánc:** #18 → #26 → #29 → **ez a PR**.
  - A bázis a `claude/category-03c-bulk` (#29, `369fc98`), ezért a diff csak a három downgrade-ágat és az új szkriptet mutatja.
  - A merge sorrendje: a #29 után, és a 0009–0011 első telepítése **előtt**.
- **A #34-gyel** (RELEASE-01 dokumentáció) független. A két PR ütközés nélkül összefésülhető: helyben ellenőrizve (`329146a` + `7b46a2b`). A #34-et ez a PR nem írja felül; a runbook pontosítása lent, külön szakaszban található.
- **A Codex #32 integrációs ágának** a #29 mellett ezt a PR-t is be kell vennie, mielőtt a migrációs láncot MySQL-en visszaállítási próbának veti alá.

## MySQL-regresszió

`scripts/mysql_release02_downgrade_check.py`:

- csak loopback hoston és üres adatbázison fut;
- a kimenet csak revíziókat, darabszámokat, rövid hasheket és sémaeltéréseket tartalmaz;
- minden szinten a **teljes sémát** veti össze az első felfelé lépéskor rögzített referenciával: oszlopok (típus, NULL, alapérték), indexek (oszlopok, egyediség), idegen kulcsok és azok `ON UPDATE/DELETE` szabályai;
- emellett összeveti a 0009 előtti adatok lenyomatát (termékek, importsorok, felhasználók, tagságok, szerepkörök) és a jogkatalógust.

Futtatás (eldobható MySQL: `RELEASE-01-READINESS.md`, 7. fejezet):

```bash
export APP_DATABASE_URL='mysql+pymysql://app:local-only@127.0.0.1:3307/adatdusito_dev'
cd backend && PYTHONPATH=. ../.venv/bin/python ../scripts/mysql_release02_downgrade_check.py --rounds 3; echo "exit=$?"
```

**Eredmény a javítás után** (MySQL 8.0.46, 2000 termékkel seedelt 0008, kb. 14 s):

- 3 kör, mindegyikben:
  - `0011 → 0010 → 0009 → 0008 → 0011`;
  - egyenként `0011 ↔ 0010`, `0010 ↔ 0009`, `0009 ↔ 0008`.
- Utána a döntésvédett downgrade-ek szintenként:
  - 0011: jóváhagyás;
  - 0010: paraméteralias;
  - 0009: kategóriatérkép.

  Mindhárom **megtagadva**, a séma és az adatok változatlanok.
- Végül `→ 0008 → 0011`.

```text
OK  first upgrade -> 0011 (reference)      -> 0011
OK  round 1: -> 0010                       -> 0010
OK  round 1: -> 0009                       -> 0009
OK  round 1: -> 0008                       -> 0008
OK  round 1: -> 0011                       -> 0011
OK  round 1 step: 0011 -> 0010             -> 0010
OK  round 1 step: 0010 -> 0011             -> 0011
…   (a 2. és a 3. kör azonos)
OK  guard 0011: preparation approval       refused
OK  guard 0010: parameter alias            refused
OK  guard 0009: category map               refused
OK  final -> 0008                          -> 0008
OK  final -> 0011                          -> 0011
{"mysql": "8.0.46-0ubuntu0.24.04.5", "rounds": 3, "checks": 56, "failed": 0}
exit=0
```

**Ugyanez a javítás nélkül** (`369fc98` migrációk, `--rounds 1`): `exit=1`.

- Az első downgrade (`0011 → 0010`) `OperationalError`-ral bukik, a revízió 0011 marad.
- Mindhárom szint jelzi a sémaeltérést, a jogkatalógus pedig 42 sor marad a várt 40/38/37 helyett.

**A #34 szkriptje a javított fán** (`mysql_release01_check.py`, helyben összefésülve: `329146a` + `7b46a2b`): `exit=0`.

- `downgrade_0011_without_approval`: `succeeded`, a revízió 0010;
- `downgrade_0011_with_approval`: továbbra is `guard`;
- mind a 6 elvárás teljesül.

**SQLite:**

- `test_category02a/03a/03c_migration.py`: 3 passed (ezek downgrade-et és ismételt upgrade-et is futtatnak);
- teljes backend: `PYTHONPATH=backend .venv/bin/pytest -q backend/tests --ignore-glob='*browser*'` → **416 passed**;
- a böngészőtesztek a CI-ban futnak.

## A runbook pontosítása (kiegészíti a RELEASE-01 5.6 pontját)

- **A sikeres downgrade technikai képesség, nem engedély adatvesztésre.** Ha már keletkezett a 0011-hez tartozó adat – jóváhagyás, kiválasztás, előnézet vagy alkalmazott tömeges művelet –, illetve 0010/0009 döntés, a downgrade **üzletileg tilos**. A védelmek jóváhagyásnál, paraméterdöntésnél és kategóriadöntésnél technikailag is megtagadják. Ilyenkor a helyreállítás **mentésből** történik (RELEASE-01, 5.2 és 5.6).
- A downgrade az adatmentes köztes állapotokra szolgál (pl. friss telepítés után azonnali visszalépés), és csak a Tulajdonos döntésével futhat.
- **A B2 nem változott:** a MySQL-en félbeszakadt *upgrade* (nem tranzakciós DDL) nem futtatható újra, és downgrade-del sem javítható. Helyreállítás csak mentésből.
- A javítás előtti állapot (`369fc98` és korábbi) migrációival MySQL-en továbbra se fusson `alembic downgrade`.
- Még nincs staging- vagy VPS-telepítés.

## Kockázatok és visszaállítás

- **A 0011 MySQL-downgrade** egy pillanatra eldobja a `product_jobs.tenant_id` kulcsot. A kulcs visszavételekor a MySQL ellenőrzi a meglévő sorokat; tenant nélküli feladatsor (`tenant_id IS NULL`) megengedett.
- **Kódszintű visszaállítás:** a commit revertje. Az upgrade-ek változatlanok, ezért telepített sémát a javítás nem érint.
