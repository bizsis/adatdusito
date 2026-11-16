# RELEASE-01 – Kiadási felkészültség: migráció, worker, üzemeltetés

Forrás: [#33](https://github.com/bizsis/adatdusito/issues/33). Állapot: 2026-11-16.

Ez a dokumentum **utasítás és ellenőrzési jegyzőkönyv, nem végrehajtás**. Nem volt `main`-merge, VPS- vagy staging-telepítés, és meglévő adatbázisba sem írtunk. Minden mérés egy eldobható, helyi MySQL 8.0.46 szerveren futott, ugyanabban a konténerben (loopback, 256 MB buffer pool). A `pinfo_db` adatbázist semmi nem érintette.

## 1. Összefoglaló

| | Megállapítás | Súly |
|---|---|---|
| **B1** | **A 0009, a 0010 és a 0011 downgrade MySQL-en adat nélkül is elbukik.** Hiba: `1553 Cannot drop index …: needed in a foreign key constraint`. SQLite-on (CI) működik, ezért a tesztek nem jelzik. A 0009 downgrade **félbemarad**: három táblát eldob, az `alembic_version` 0009 marad, és utána sem a downgrade, sem az `upgrade head` nem fut le. | **Blokkoló** a #18/#26/#29 visszaállítási tervére. A javítás egyeztetésre vár (8. fejezet). |
| **B2** | **A félbeszakadt 0011 nem futtatható újra.** MySQL-en a DDL nem tranzakciós: a hiba után három tábla és három `product_jobs` oszlop bent marad, az `alembic_version` 0010. Az újrafuttatás hibája: `Duplicate column name 'created_by'`. Ugyanez igaz a 0009-re és a 0010-re is. | A runbookban kezelve: helyreállítás csak mentésből (5.6). |
| R1 | A jogok kiosztása megfelel a [#29 döntésének](https://github.com/bizsis/adatdusito/pull/29#issuecomment-6903415484). A beépített ügyféladmin-sablon megkapja a négy tenant-jogot, a feldolgozó és az egyedi szerepkörök nem. **Ahol a tenant az ügyféladmin-sablont 0009 előtt szerkesztette (helyi másolat), ott az adminok sem kapják meg** – a jogot nekik delegálni kell. | Üzemeltetési teendő (5.5) |
| R2 | Alkalmazás- és adatbázis-verzió eltérését semmi nem ellenőrzi induláskor. Új kód 0011 nélkül: a `ProductJob` ORM-modell már az új oszlopokat kérdezi le. Régi worker új kóddal: a `products.operation` feladatot nem ismeri. | Sorrend a runbookban (5.3) |
| R3 | Elakadt feladatot csak az API (`/resume`) vagy a CLI (`python -m app.product_jobs`) folytat. Nincs ütemezett újraindítás. | Runbook (5.4), monitorozás |
| R4 | A lejárt kiválasztások tételei (`product_selection_items`, akár 250 000 sor) nem törlődnek. | Nem blokkoló, külön feladat |
| R5 | A 250 000-es kiválasztás nincs mérve (a meglévő mérés 60 000 termék). | Terv: 6. fejezet; futtatás csak jóváhagyás után |

## 2. Vizsgált buildek (pontos SHA-k)

| PR | Ág | Fej-SHA | Bázis |
|---|---|---|---|
| — | `main` | `80b0dce5b5270eb5de1ccecbfef5427ce35aa2c3` | — |
| [#18](https://github.com/bizsis/adatdusito/pull/18) | `claude/category-02a-backend` | `e946b93a0428f485a7131c157ced4a6f81773f13` | `main` |
| [#25](https://github.com/bizsis/adatdusito/pull/25) | `claude/category-02c-audit` | `47d0cc66490c1cb7a0301bdf342e4a12a06159e6` | #18 |
| [#26](https://github.com/bizsis/adatdusito/pull/26) | `claude/category-03a-parameters` | `c05746d3b34cb2f0638dc6ece19988d6a9c37483` | #18 |
| [#29](https://github.com/bizsis/adatdusito/pull/29) | `claude/category-03c-bulk` | `369fc989804a7c94964e93a9e73d53e84d1f3df5` | #26 |
| [#31](https://github.com/bizsis/adatdusito/pull/31) | `claude/auth-totp-deterministic-test` | `4ffcfb22a2a476948dc322839a65a558ce04ad9f` | `main` |

**Helyi integráció** (nincs pusholva, a #32 Codex-ágot nem érinti): `369fc98` + merge `47d0cc6` + merge `4ffcfb2`. Mindkét merge ütközés nélkül ment.

- A #25 csak auditot tartalmaz: dokumentáció, riport, `test_category_457_audit.py`, `scripts/mysql_category02a_check.py`, `scripts/report_category_457.py`. **Nincs benne migráció, és sem a worker, sem az alkalmazáskód nem változik.**
- A #31 csak tesztet módosít.

## 3. Ellenőrzési mátrix

Jelölés: ✅ ellenőrizve · ❌ hibát talált · ⚠️ részben, vagy feltétellel · ⛔ nincs ellenőrizve.

| Terület | Állapot | Bizonyíték |
|---|---|---|
| Lánc: `0008 → 0009 → 0010 → 0011`, egyetlen head | ✅ | `down_revision` láncolat. `alembic heads` = 0011. |
| Upgrade MySQL-en, meglévő adattal (2000 termék, importsorok, felhasználók, tagságok, szerepkörök, kötések) | ✅ | Az előtte és utána vett lenyomat minden lépés után **bájtra azonos** (`mysql_release01_check.py`). |
| Ismételt `upgrade head` | ✅ | No-op, az adatok azonosak. |
| A 0009 MySQL-időigénye nagy táblán | ⚠️ | A #25 mérése szerint 50 000 terméken 0,97 s. Az alkalmazás-engine `read_timeout` értéke 5 s, ezt egyetlen DDL sem lépheti túl. Nagyobb éles táblánál előmérés kell (5.1). |
| Új jogkódok a `permissions` táblában | ✅ | `products.classify`, `products.parameters`, `parameters.global_aliases.manage`, `products.bulk`, `products.prepare.approve`. |
| `role_permissions` | ✅ | A migrációk nem adnak hozzá sort (0 új sor). |
| Effektív jogok a 0011 után | ✅ | Superadmin: mind az 5. Beépített ügyféladmin-sablon: a 4 tenant-jog. Feldolgozó és egyedi szerepkör: egyik sem. |
| A `system_admin` szerepkör | ⚠️ | Frissített és friss MySQL-adatbázisban sem kapja meg az új jogokat (0007 rögzített lista). A teszt-fixture (`create_all` + kódbeli `defaults()`) viszont megadja. Ez **eltérés a teszt és az éles séma között**, de megfelel a #29 döntésének. |
| Ügyféladmin helyi sablonmásolattal | ⚠️ | Nem kapja meg az új jogokat (R1). |
| 0011 downgrade-védelem jóváhagyás mellett | ✅ | `RuntimeError` keletkezik, a revízió 0011 marad, nincs változás. |
| 0011 downgrade jóváhagyás nélkül | ❌ | `1553 ix_preparation_item_product`. Az első utasítás bukik, a séma változatlan marad. |
| 0010 downgrade | ❌ | Eldobja az `ix_product_parameter_emag` indexet, majd elbukik az `ix_product_parameter_state`-nél. A revízió 0010 marad. Az `upgrade head` innen lefut, de az index hiányzik. |
| 0009 downgrade | ❌ | Eldobja a `product_jobs`, `product_events` és `product_classifications` táblát, majd elbukik. A revízió 0009 marad. Az ismételt downgrade hibája: `1146 product_events doesn't exist`. Az `upgrade head` a 0011-nél bukik. **Csak mentésből állítható helyre.** |
| Félbeszakadt 0011 (szimulált hiba a 4. táblánál) | ❌ | Három tábla és három oszlop marad bent, a revízió 0010. Újrafuttatás: `1060 Duplicate column`. |
| Worker-regisztráció | ✅ | `worker.py`: `celery.conf.imports = ("app.import_engine", "app.product_jobs")`. A `product_jobs` importálja a `bulk_operations`-t. Feladatok: `products.reapply_category_map`, `products.parameter_run`, `products.operation`. |
| Lease, folytatás, megszakítás | ✅ (kód) / ⛔ (élő) | Lease 5 perc, kötegenként megújul. `acks_late` és `reject_on_worker_lost`. A lejárt lease után a feladat `stalled`. A tesztek lefedik (#26, #29). Valódi Redis-szel és workerrel nem futott. |
| Futáskorlát és automatikus folytatás | ⚠️ | 50 000 termék/futás. Utána `pending` állapot és új `delay()`. Ha a Redis ekkor nem érhető el, a feladat `pending` marad: kézi `/resume` vagy CLI kell. |
| Tenant-izoláció, CSRF, jogosultság az új végpontokon | ✅ (teszt) | #29: `test_bulk_preparation.py`. Élő környezetben nincs ellenőrizve. |
| Teljes backendcsomag a helyi integráción | ✅ | 429 passed (7. fejezet). |
| Böngészőtesztek, frontend | ⛔ | A Codex #32 feladata. |
| 250 000-es kiválasztás terhelése | ⛔ | Csak terv (6. fejezet). |
| Valódi staging, VPS | ⛔ | Nem a feladat része. |

## 4. Worker- és feladat-áttekintés

- **Indítási sorrend** (`compose.yaml`): `redis` (healthy) → `migrate` (`alembic upgrade head`, sikeres kilépés) → `backend` és `worker`. Ezért egy sima `docker compose up -d` **magától migrál**, a mentés előtt is. A runbook ezt kerüli: előbb mentés, utána külön `run --rm migrate`.
- **Régi és új kód keveredése:**
  - **új backend 0011 nélkül:** a `ProductJob` lekérdezése az új oszlopok miatt elbukik, ez a 02A/03A feladatokat is érinti;
  - **régi worker új backenddel:** a `products.operation` üzenetet nem ismeri, az üzenet elvész, a feladat `pending` marad;
  - **új worker régi sémán:** ugyanaz az ORM-hiba.

  Ezért a backend és a worker **csak együtt, a migráció után** indulhat (5.3).
- **Elakadás:** a `running` állapotú feladat lease-e lejár (5 perc), ezután `stalled`. Folytatása:
  - `POST /api/v1/workspace/product-jobs/{id}/resume` – a létrehozó, vagy aki a feladatfajta jogaival rendelkezik;
  - `docker compose exec backend python -m app.product_jobs` – minden `pending` vagy elakadt 02C/03A/03C feladatot sorra futtat.

  Automatikus ütemezett folytatás **nincs**.
- **Redis-láthatóság:** `acks_late` mellett a Redis alapértelmezett `visibility_timeout` értéke 1 óra. Egy futás legfeljebb 50 000 termék; a mért 60 000-es alkalmazás 2 futásban 644 s volt, vagyis kb. 9 perc/futás, így ez belefér. A párhuzamos újrakézbesítést a lease kiszűri (`claim()`).
- **Futás közbeni jogvisszavonás:** az `apply` minden íráskötege előtt újraellenőrzi a jogot (#29 teszt).

## 5. Staging- és élesítési runbook (csak utasítás)

A végrehajtásról a Tulajdonos dönt. Előfeltételek:

- a #18 → #26 → #29 sorrendben merge-elt `main`;
- a #25 és a #31 opcionális, mert nem érintik a sémát;
- a **B1 javítása**, vagy annak tudomásulvétele, hogy a visszaállítás **csak mentésből** lehetséges;
- jóváhagyott karbantartási ablak.

Az alábbi parancsok a VPS-en, a compose-projekt könyvtárában futnak, és **csak a staginggel kezdve**.

### 5.1 Előellenőrzés (csak olvasás)

```bash
git rev-parse HEAD                                                    # a jóváhagyott merge-SHA
docker compose run --rm migrate alembic current                       # elvárt: 0008 (head)
docker compose run --rm migrate alembic heads                         # elvárt: 0011 (head)
docker compose exec backend python -c "from app.db import engine; from sqlalchemy import text; c=engine().connect(); print(c.scalar(text('SELECT COUNT(*) FROM supplier_products')))"
```

- Ha a `supplier_products` több mint 200 000 sor, előbb a mentés eldobható másolatán mérni kell a 0009 időigényét (5 s-os `read_timeout`).
- Szabad lemezhely: legalább a mentés kétszerese.

### 5.2 Mentés és visszaállíthatóság

```bash
docker compose stop frontend backend worker
# csak az alkalmazás-adatbázis; pinfo_db NEM
mysqldump --single-transaction --routines --triggers --set-gtid-purged=OFF adatdusito_dev | gzip > adatdusito_dev-pre0009-$(date +%Y%m%d%H%M).sql.gz
```

- **A mentést a migráció előtt vissza kell tölteni egy külön, üres sémába, és ellenőrizni kell** (`docs/operations/OPERATIONS.md`): `alembic_version` = 0008, és egyeznek a sorszámok (`users`, `tenants`, `supplier_products`, `import_rows`).
- A titkosítási kulcsfájlt (`APP_ENCRYPTION_KEY_FILE`) külön kell megőrizni.

### 5.3 Migráció és indítás

```bash
docker compose run --rm migrate                                       # alembic upgrade head
docker compose run --rm migrate alembic current                       # elvárt: 0011 (head)
docker compose up -d backend worker                                   # együtt; a migrate itt no-op
docker compose up -d frontend
```

**Ha a migráció hibával áll meg:** nem szabad újrafuttatni, és downgrade-et sem szabad indítani (B1, B2). A helyreállítás az 5.6 szerint, mentésből történik.

### 5.4 Backfill és feladatok

```bash
docker compose exec backend python -m app.product_backfill --batch 500       # 0009 előtti termékek; folytatható, idempotens
docker compose exec backend python -m app.product_jobs                       # elakadt 02C/03A/03C feladatok
docker compose logs --since 10m worker | grep -E "products\.(operation|parameter_run|reapply_category_map)"
```

- A backfill lefutásáig a régi termékek a keresésben nem jelennek meg; szűrővel és lapozással elérhetők.
- A 03A paraméterfutást (`POST /api/v1/workspace/parameter-runs`) tenantonként, jóváhagyás után kell indítani.

### 5.5 Smoke-teszt és tenant-jogok

1. `GET /api/health/live` és `GET /api/health/ready` → 200. A worker naplójában benne van a három feladat (`[tasks]` lista).
2. Tesztbérlőben, ügyféladminnal: `GET /api/v1/workspace/products` → 200. Kiválasztás → előnézet → `GET /product-jobs/{id}` → `completed`. **Alkalmazás csak tesztbérlőn.**
3. Feldolgozó szerepkörrel a `parameter-bulk-previews/{id}/apply` → 403.
4. **Helyi admin-sablonmásolatok listája** (csak olvasás):

   ```sql
   SELECT owner, code FROM access_roles WHERE owner LIKE 'tenant:%' AND code = 'tenant_admin';
   ```

   Ezekben a tenantokban az adminok nem kapják meg automatikusan a `products.classify/parameters/bulk/prepare.approve` jogot. A delegálásról tenantonként a Tulajdonos dönt.
5. A 3 `pending_review` donor továbbra is blokkolt: a besorolásban nem jelenik meg automatikus dúsítási forrásként.

### 5.6 Hibajelzés és visszaállítás

- **Hibajelek:**
  - 5xx a `/workspace/product-*` végpontokon;
  - `stalled` feladatok (`state='running' AND lease_until < NOW()`);
  - `Received unregistered task` a worker naplójában;
  - `OperationalError 1054/1146` a backend naplójában (séma és kód eltérése).
- **Kódhiba, a séma rendben:** a `main` előző SHA-jára vissza **nem** lehet lépni a 0011-es sémán, mert az új jogok és táblák megmaradnak, a régi kód pedig nem ismeri őket. Javító kiadás kell.
- **Downgrade TILOS:**
  - ha van `preparation_approvals` sor (a 0011 védelme amúgy is megtagadja);
  - ha van kategóriadöntés vagy paraméterdöntés (a 0009/0010 védelme);
  - **továbbá a B1 javításáig MySQL-en egyáltalán ne fusson `alembic downgrade`**, mert a 0009-nél félbemarad, és tönkreteszi a sémát.
- **Visszaállítás:**

  ```bash
  docker compose stop frontend backend worker
  # a jelenlegi állapot megőrzése (bizonyíték), majd a validált mentés visszatöltése
  mysqldump --single-transaction adatdusito_dev | gzip > adatdusito_dev-failed-$(date +%Y%m%d%H%M).sql.gz
  gunzip < adatdusito_dev-pre0009-….sql.gz | mysql adatdusito_dev
  git checkout <előző jóváhagyott SHA> && docker compose build backend
  docker compose up -d
  ```

  A mentés óta keletkezett importok és döntések elvesznek: ez a visszaállítás határa, erről a Tulajdonos dönt.

## 6. Terheléstest-terv: 60 000 → 250 000 kiválasztás (nem futtatva)

Cél: igazolni vagy cáfolni, hogy a 250 000 tételes kiválasztás, előnézet, alkalmazás, ellenőrzés és jóváhagyás belefér a korlátokba:

- 30 s proxy-időkorlát a kérésen belüli lépésekre;
- 5 s `read_timeout` utasításonként;
- 5 perces lease kötegenként.

**250 000-es bizonyítékot ez a dokumentum nem állít.**

- **Környezet:**
  - eldobható MySQL 8.0.x a loopbacken, üres `adatdusito_dev`; nem VPS, nem `pinfo_db`;
  - konténer- vagy cgroup-korlát: 2 vCPU, 4 GB RAM, `innodb_buffer_pool_size=1G`, 20 GB ideiglenes lemez;
  - a méréseket nem szabad párhuzamosan futtatni.
- **Lépcsők:** 60 000 (a meglévő mérés megismétlése, kalibráció) → 120 000 → 250 000. Bármely lépcső hibája vagy időkorlát-túllépése esetén megállunk, és nem lépünk tovább.
- **Eszköz:** a meglévő `scripts/mysql_category03c_check.py --products N`. Ez a 0011-ig migrál, seedel, és lefuttatja a kiválasztást, előnézetet, alkalmazást, ellenőrzést, jóváhagyást, újramérést, visszavonást és a védett downgrade-et.
- **Mérendő:**
  - lépésidők;
  - a leghosszabb egyedi SQL-utasítás (`performance_schema.events_statements_history_long`, küszöb: 5 s);
  - csúcs-RSS;
  - InnoDB sorzár-várakozás;
  - a `product_selection_items` és a `product_operation_items` mérete MB-ban.
- **Elfogadás:**
  - a kérésen belüli kiválasztás és jóváhagyás 30 s alatt marad;
  - nincs 5 s fölötti utasítás;
  - a háttérfeladatok futásonként 50 000 alatt vannak, a lease megújul;
  - `source_overwrites` = 0.
- **Becsült erőforrásigény:**
  - kb. 250 000 × 30 paraméter = 7,5 millió `product_parameter_values` sor;
  - a 60 000-es arányból becsülve az alkalmazás kb. 45 perc, az előnézet kb. 10 perc, az ellenőrzés kb. 18 perc;
  - lemez kb. 5–8 GB.

  Ez becslés, nem mérés.
- **Indítás:** csak a Vezér vagy a Tulajdonos külön jóváhagyásával.

## 7. Reprodukálható offline ellenőrzés

Csak eldobható, helyi szerveren. Példa Ubuntu 24.04 konténerben, a repó gyökeréből:

```bash
apt-get install -y mysql-server-8.0                       # a rendszerszolgáltatást nem használjuk
M=/srv/release01-mysql; mkdir -p $M/data $M/run && chown -R mysql:mysql $M
mysqld --no-defaults --user=mysql --datadir=$M/data --initialize-insecure
mysqld --no-defaults --user=mysql --datadir=$M/data --socket=$M/run/s.sock --port=3307 --bind-address=127.0.0.1 --mysqlx=OFF --innodb-buffer-pool-size=256M &
mysql --socket=$M/run/s.sock -uroot -e "CREATE DATABASE adatdusito_dev CHARACTER SET utf8mb4; CREATE USER 'app'@'127.0.0.1' IDENTIFIED BY 'local-only'; GRANT ALL ON *.* TO 'app'@'127.0.0.1'"
export APP_DATABASE_URL='mysql+pymysql://app:local-only@127.0.0.1:3307/adatdusito_dev'
cd backend && PYTHONPATH=. ../.venv/bin/python ../scripts/mysql_release01_check.py; echo "exit=$?"
```

- Az `app` felhasználónak globális jog kell, mert a szkript a félbeszakadt-0011 próbához újra létrehozza az eldobható adatbázist. A `guard()` csak loopback hostot és üres adatbázist fogad el.
- **Eredmény a `369fc98` állapoton** (`exit=1`, mert a B1 fennáll):

  ```text
  upgrade_0009/0010/0011, rerun_upgrade_head : preserved_data_identical = true
  permissions_present                        : mind az 5
  role_permissions_rows_for_new_codes        : 0
  effective: superadmin 5 · tenant_admin (sablon) 4 · processor 0 · helyi admin-másolat 0 · egyedi szerepkör 0
  downgrade_0011_with_approval               : guard, version 0011
  downgrade_0011_without_approval            : OperationalError 1553 ix_preparation_item_product, version 0011
  interrupted_0011                           : version 0010; 3 tábla + 3 product_jobs oszlop bent maradt
  rerun_0011_after_interruption              : OperationalError 1060 Duplicate column 'created_by'
  ```

- **A 0010 és a 0009 downgrade külön** (üres adatbázis, `alembic upgrade 0010`, majd `alembic downgrade 0009`; ugyanígy a `0009 → 0008`): mindkettő `1553`-mal bukik. A visszamaradt állapotot a 3. fejezet írja le.
- **Teljes backendcsomag a helyi integráción** (`369fc98` + `47d0cc6` + `4ffcfb2`):

  ```bash
  PYTHONPATH=backend .venv/bin/pytest -q backend/tests --ignore-glob='*browser*'
  ```

  Eredmény (2026-11-16): **429 passed** (303,8 s). A böngészőtesztek a CI-ban és a #32-ben futnak.

## 8. A B1 javítási javaslata (egyeztetésre; nincs commitolva)

Ok: MySQL-en egy idegen kulcshoz index kell, aminek a vezető oszlopa a kulcs oszlopa. A downgrade előbb az indexet dobná el, és csak utána a táblát vagy a kulcsot. A javaslat **csak a downgrade ágakat** érinti, az upgrade-hez és a meglévő adatokhoz nem nyúl:

1. **0011, 0010, 0009:** az egész táblát eldobó lépések előtt nincs `op.drop_index`; a `drop_table` a saját indexeit is eldobja.
2. **0009 `supplier_products`:** előbb az `fk_product_source_category` kulcsot kell eldobni, utána az `ix_supplier_products_source_category_id` indexet.
3. **0011 `product_jobs`:** előbb `create_index("ix_product_jobs_tenant_id", ["tenant_id"])`, mert a `uq_product_job_idempotency` a `tenant_id` kulcsot is kiszolgálja. Utána az `fk_product_job_created_by` kulcs, végül a unique megszorítás eldobása.

Ezt az eldobható MySQL-en egy átmeneti másolaton kipróbáltuk: két teljes `0011 → 0008 → 0011` kör, mindkettő sikeres, az adatlenyomat azonos, a 0011 védelme továbbra is megtagad. **Egy köztes változat (csak az 1–2. pont) a 0011-nél félbemaradt.** Ezért a javítás külön PR-t igényel, amelyben:

- **MySQL-regressziós ellenőrzés** kell: a `mysql_release01_check.py` `exit=0`, továbbá a 0010 és a 0009 downgrade külön is;
- a SQLite-alapú migrációs tesztek változatlanul zöldek maradnak;
- a 0009–0011 fájlok gazdája Claude, de **a meglévő migrációk módosításához a Vezér döntése kell** (AGENTS.md 5. pont).

## 9. Kockázatok és visszaállítás

| Kockázat | Hatás | Kezelés |
|---|---|---|
| B1: downgrade MySQL-en | félbemaradt séma, adatvesztés a job-, esemény- és besorolási táblákban | A javításig nincs downgrade; visszaállítás mentésből (5.6). |
| B2: félbeszakadt migráció | nem futtatható újra | Mentés a migráció előtt, visszatöltés; nincs kézi DDL-javítgatás. |
| `compose up` mentés előtt migrál | nincs visszaállítási pont | Runbook 5.2–5.3 sorrendje. |
| Kód és séma eltérése | 5xx, elveszett feladatüzenet | A backend és a worker együtt, a migráció után indul. |
| Helyi admin-sablonmásolat | az adminok nem érik el az új funkciókat | Lista (5.5), delegálás tenantonként. |
| Elakadt feladat | a művelet nem fejeződik be | `/resume` vagy CLI, a `stalled` állapot monitorozása. |
| Növekvő `product_selection_items` | lemezhasználat | Később takarító feladat (külön döntés). |
| 250 000 nincs mérve | időkorlát- vagy erőforrás-túllépés | 6. fejezet; addig nincs ilyen ígéret. |

Ez a dokumentum és az ellenőrző szkript nem változtat futó kódot, sémát vagy adatot. Visszaállítás: a PR revertje.
