# RELEASE-03 – Kötelező MySQL 8 migrációs CI-job

Forrás: [#38](https://github.com/bizsis/adatdusito/issues/38). A job a [#36](https://github.com/bizsis/adatdusito/pull/36) (RELEASE-02) javítására épül, gazdája Claude, és csak erre a jobra vonatkozik. A többi CI-jobot nem módosítja.

## Mit fog meg?

A többi backend-teszt SQLite-on fut, ezért nem látja a MySQL-specifikus DDL-hibákat. Ilyen volt a RELEASE-02 B1 hibája: a 0009–0011 downgrade `1553`-as hibával bukott, mert egy idegen kulcshoz tartozó indexet a kulcs előtt próbált eldobni.

A `mysql-migrations` job egy eldobható MySQL 8 konténerben futtatja a láncot, és **minden szinten a teljes sémát és a 0009 előtti adatokat** veti össze az első felfelé lépéskor rögzített állapottal. Így elbukik, ha:

- egy downgrade vagy re-upgrade MySQL-en hibát dob (pl. `1553`, `1091`, `1060`);
- egy lépés után **részleges séma** marad: hiányzó vagy felesleges tábla, oszlop, index, idegen kulcs, vagy eltérő `ON UPDATE/DELETE` szabály;
- a 0009 előtti adatok (termékek, importsorok, felhasználók, tagságok, szerepkörök) vagy a jogkatalógus egy kör után eltér;
- egy döntésvédelem nem tagadja meg a downgrade-et, vagy megtagadja ugyan, de közben módosít valamit. A védelmek: 0011 jóváhagyás, 0010 paraméteralias, 0009 kategóriatérkép.

**Mit nem fog meg:**

- teljesítményt nagy táblán: a 250 000-es terhelési teszt külön feladat;
- félbeszakadt *upgrade*-et (B2): ezt nem szimulálja, mert a helyreállítás mentésből történik;
- az éles MySQL-verzióval vagy -beállításokkal való eltérést: a konténer `mysql:8.0`, a pontos verzió a naplóban szerepel.

## Mikor fut, és meddig tart?

- **Minden PR-on és minden `main` pushnál**, a többi jobbal párhuzamosan.
- **Blokkoló:** a `CI result` (`ci-ok`) összesítő `needs` listájában szerepel, így bármely bukása pirosra állítja.
- **Időtartam:** helyben a 3 körös ellenőrzés kb. 14 s, a negatív kontroll kb. 8 s. A hosted futás a konténerindítással együtt néhány perc; a pontos értéket a PR rögzíti.
- **Időkorlát:** a job `timeout-minutes: 15`. A MySQL-konténer egészség-ellenőrzése 5 s-onként, legfeljebb 36-szor fut; a segédszkript ezen felül 120 s-ig vár.

## Lépések

1. **Service-konténer** `mysql:8.0`, `--memory=1g`, a `127.0.0.1:33306` porton.
   - Üres `adatdusito_dev` adatbázis, tesztcélú root-jelszóval. Ez a jelszó nem production secret, és GitHub-titokban sincs.
   - A konténer a jobbal együtt megszűnik.
   - A `pinfo_db`, a VPS és valódi adat nem érhető el.
2. **Telepítés:** csak a futtatókörnyezet zárolt függőségei (`backend/requirements.lock`: alembic, SQLAlchemy, PyMySQL).
3. **`mysql_ci_db.py` segéd:** várakozik a szerverre; `reset` módban újra létrehozza az üres `adatdusito_dev` adatbázist. Csak a `127.0.0.1`-en és csak ezen a néven dolgozik.
4. **Regresszió:** `scripts/mysql_release02_downgrade_check.py --rounds 3`.
   - 2000 terméket seedel a 0008-ra.
   - Három kört fut, mindegyikben a teljes `0011 → 0010 → 0009 → 0008 → 0011` kört és az egylépéses `↔` lépéseket.
   - Ezután a döntésvédett downgrade-ek, majd `→ 0008 → 0011`.
   - Kilépési kód: 0 csak hibátlan futásnál.
   - A napló utolsó sora titokmentes JSON: MySQL-verzió, körök, ellenőrzések és hibák száma, futási idő, és szintenként egy sémalenyomat (az `information_schema` pillanatképének SHA-256 előtagja).
5. **Negatív kontroll:** a migrációkat ideiglenes másolatba teszi, és a 0010 downgrade-be visszaírja a **pontos B1 előtti** két `drop_index` sort.
   - Ezzel a szkriptnek pontosan `exit 1`-gyel kell bukni, és a naplóban szerepelnie kell az `1553`-nak. Ha nem, maga a job bukik.
   - Ez igazolja, hogy az ellenőrzés valóban jelez, nem csak zöld.
6. **RELEASE-01 ellenőrzés** (`scripts/mysql_release01_check.py`): csak akkor fut, ha a fájl az ágon van.
   - A fájl a #34 PR-ral érkezik. Ezen az ágon nincs, ezért ez a lépés csak `::notice::` üzenetet ír, és **nem állítja, hogy lefutott**.
   - Integrációs előfeltétel: amint a #34 és ez a PR egy ágon van, a lépés automatikusan lefut, és a hibája is blokkoló.
7. **Összesítés:** a GitHub Step Summary szakaszba kerülnek az OK/ERR darabszámok és a JSON-sorok. Hiba esetén a naplók 7 napig artifactként megmaradnak.

## Helyi ellenőrzés (a hosted futás előtt)

A job `run` blokkjait kiemelve, eldobható, helyi MySQL 8.0.46-on futtattuk le, ugyanazokkal a parancsokkal:

| Lépés | Eredmény |
|---|---|
| regresszió, 3 kör | `checks 56, failed 0`, 14,0 s, `exit 0` |
| sémalenyomatok | `0008 2d7cf379f428add9`, `0009 f4aebc5d320cff5b`, `0010 89374986112d40b8`, `0011 7bb84020684f2cc0` |
| negatív kontroll | `exit 1`, `1553 Cannot drop index 'ix_product_parameter_state'`, utána részleges séma jelezve (hiányzó `ix_product_parameter_emag`). A lépés sikeres. |
| regresszió hibás repó-migrációval (átmenetileg visszaírt B1) | a lépés `exit 1`, tehát a job és a `CI result` is piros lenne |
| RELEASE-01 lépés ezen az ágon | `::notice::`, a fájl nincs jelen |

A negatív kontroll első változata csak egyetlen indexet dobott el. Ez **nem** okozott hibát, mert a `tenant_id` kulcsot a másik index is kiszolgálta. A kontroll saját ellenőrzése ezt jelezte, ezért most a pontos eredeti sorokat írja vissza.

A hosted futás URL-je és eredménye a PR-leírásban van. A korábbi 56/56-os eredmény helyi mérés, nem a hosted CI eredménye.

## Visszaállítás és mentés: a job korlátai

- A zöld MySQL-job a migrációk **technikai** visszaléphetőségét bizonyítja üres, illetve seedelt, döntés nélküli adatbázison. **Nem engedély** éles downgrade-re (RELEASE-02 runbook).
- Ha MySQL-en a DDL részben sikerül – egy félbeszakadt upgrade vagy downgrade –, **a production-helyreállítás nem automatikus downgrade**, hanem a validált mentés visszatöltése a RELEASE-01 runbook 5.2 és 5.6 pontja szerint.
- A job a VPS-en semmit nem futtat, és staging-telepítést sem végez.

## Ütemezés és függőségek

- **Lánc:** #18 → #26 → #29 → #36 → **ez a PR**.
- A végső integrációban a #34 és a #37 változásaival együtt kell tesztelni: ekkor a 6. lépés is lefut.
- A #36 korábbi zöld CI-je MySQL-job nélkül értendő.
