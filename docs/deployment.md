# Fejlesztői VPS kézi frissítése

**Aktuális kiadás: CODEX 03A, Alembic 0003.** A konkrét frissítési parancsok a [CODEX 03A frissítés](#codex-03a-frissítés) részben vannak. Az alábbi CODEX 02 eljárás a korábbi kiadás átadási előzménye.

Ez dokumentált átadás, **nem automatikus telepítés**. A meglévő MySQL-, UFW-, Docker-hálózat-, Nginx- és HTTPS-konfigurációhoz nem szükséges módosítás. A pinfo.hu és az éles környezet érintetlen marad.

## 1. Változtatás előtti ellenőrzés

PuTTY-ban, a már működő VPS-en:

```bash
cd /opt/adatdusito
git status -sb
git remote -v
git diff -- compose.yaml
docker compose ps -a
docker network inspect adatdusito-dev-net --format '{{json .IPAM.Config}}'
curl --fail --silent --show-error https://dev.pinfo.hu/api/health/ready
```

A `.env` fájlt ne jelenítsd meg, ne másold naplóba vagy Gitbe. Ellenőrizd helyben, hogy mindkét DB-URL a `172.28.10.1:3306` címet, a megfelelő külön felhasználót és adatbázist használja. A referenciafelhasználó joga továbbra is csak SELECT legyen a három megadott táblára. A meglévő referenciaadatbázis-menetés `/root/backups/pinfo_db_before_adatdusito.sql.gz` nem helyettesíti az alkalmazás-adatbázis friss mentését.

**Állj meg, ha nem várt Git-eltérés vagy szolgáltatásprobléma van.** Meglévő szolgáltatás leállításához vagy konfiguráció felülírásához előbb a konkrét eltérés alapján kérj jóváhagyást.

A VPS eredeti, helyi Compose-változása az external hálózat blokkja volt; ez most a GitHubon is szerepel. Ha emiatt a pull megtagadná a frissítést, előbb ellenőrizd, hogy valóban csak ez a titokmentes változás van a fájlban. Megőrzéshez használható:

```bash
git stash push -m "VPS external network before CODEX 02" -- compose.yaml
git rev-parse stash@{0}
```

Jegyezd fel a stash azonosítóját. A frissítés után hasonlítsd össze a megőrzött verziót az új fájllal. Ne alkalmazd vissza vakon a stash-t, és ne töröld, amíg az eltéréseket nem ellenőrizted. Ne használd a `git reset --hard` parancsot.

## 2. Mentés és kódfrissítés

Készíts jogosultságvédett mentést a `.env` fájlról és az `adatdusito_dev` adatbázisról; a mentés kerüljön a checkouton kívülre. Példa a DBA számára, interaktív jelszóbekéréssel:

```bash
set -o pipefail
umask 077
mysqldump -u root -p --single-transaction adatdusito_dev | gzip > /root/backups/adatdusito_dev_before_codex02.sql.gz
```

A fájlnév ne írjon felül korábbi mentést; szükség esetén válassz új nevet. Ellenőrizd a parancs sikerét és a tömörített mentés épségét (`gzip -t`). A referencia-adatbázishoz ne futtass író SQL-t vagy migrációt.

```bash
git pull --ff-only origin main
docker compose config --quiet
```

Ellenőrizd az external hálózat és a port változatlanságát. Az új `.env.example` csak minta: a működő `.env` fájlt ne másold felül vele. A biztonsági alapértékek HTTPS-hez megfelelőek; szükség esetén az alábbi **nem titkos** beállításokat kézzel, a meglévő értékeket megőrizve add meg:

```text
APP_ORIGIN=https://dev.pinfo.hu
COOKIE_SECURE=true
```

## 3. Build, migráció, új alkalmazásverzió

Az alábbi parancsok az új alkalmazáskonténerekre hatnak; ne futtasd őket a működő környezet felmérése és az üzemeltető jóváhagyása nélkül:

```bash
docker compose build
docker compose run --rm --no-deps migrate alembic upgrade head
docker compose run --rm --no-deps migrate alembic current
docker compose up -d --no-build
docker compose ps -a
```

Elvárt Alembic-verzió: **0002**. A 0001 változatlan. A 0002 létrehozza a users, tenants, roles, permissions, role_permissions, memberships, login_sessions, audit_events és system_settings táblákat, valamint a szerepkörök és jogosultságok kezdőadatait. Nem hoz létre alapértelmezett felhasználót. Ismételt upgrade nem módosít már alkalmazott migrációt.

Nincs szükség `docker compose down`, volume-törlés, új Docker-hálózat, MySQL-újratelepítés vagy Nginx-reload végrehajtására. A `compose.cloud.yaml` fájlt a VPS-en ne használd.

## 4. Első Superadmin és ellenőrzés

```bash
docker compose exec backend python -m app.bootstrap --email SAJAT_ADMIN_EMAIL --name "Rendszergazda"
bash scripts/smoke.sh https://dev.pinfo.hu
```

A program a jelszót kétszer, rejtetten kéri be, legalább 12 karakterrel. Nincs alapértelmezett jelszó, jelszó-argumentum vagy jelszó-kiírás. Már létező Superadmin esetén a parancs megtagadja az ismételt inicializálást.

Böngészőből ellenőrizd:

1. Sikeres és sikertelen belépés; kijelentkezés után védett adatok elutasítása.
2. Új ügyfél, ügyféladmin és második ügyfél létrehozása, elkülönült felhasználólistákkal.
3. Kategóriakeresés, alkategóriák, hiányzó szülő figyelmeztetés, kötelező/opcionális paraméterek és értéklapozás.
4. Adminisztrációs napló, szolgáltatásállapot és `/api/v1/docs` elérhetősége.
5. Cookie: Secure, HttpOnly, SameSite=Strict. A pinfo.hu szolgáltatása változatlanul működjön.

A referenciák kizárólag SELECT lekérdezéssel kerülnek olvasásra; író próbát ne végezz a valódi pinfo_db-n.

## Visszaállítás

Ne futtass automatikus downgrade-et: az eltávolítaná az új identitástáblákat. Sikertelen kiadásnál az üzemeltető a korábban feljegyzett commit/image és az alkalmazás-adatbázis mentése alapján készítsen konkrét visszaállítási tervet. A referencia-adatbázist és a meglévő hálózatot ne módosítsa. A GitHubra feltöltött kód nem jelenti a VPS telepítését vagy ottani ellenőrzését.

## CODEX 03A frissítés

A meglévő hálózat és a `.env` megőrzésével, a fenti Git-eltérésellenőrzés és alkalmazás-adatbázismentés után:

```bash
cd /opt/adatdusito
git status -sb
git pull --ff-only origin main
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps migrate alembic upgrade head
docker compose run --rm --no-deps migrate alembic current
docker compose up -d --no-build
bash scripts/smoke.sh https://dev.pinfo.hu
docker compose exec -T backend python -m app.reference_report
```

Elvárt verzió: **0003**. Csak a `reference_sources` és `reference_observations` alkalmazástáblák újak; a `0001` és `0002` változatlan. Új Superadmin inicializálása nem szükséges. A forrásregiszter kezdőrekordjai forrástípusokat jelölnek, nem sikeres webshopletöltést. A pinfo_db, a Compose external hálózat és a VPS szolgáltatáskonfigurációi nem változnak.

Böngészőben ellenőrizd a strukturális szülők megnyitását, a termékbesorolhatóság jelölését, a teljes szülőutat, a fel/le navigációt, a keresést és a forráslefedettségi részt. A 1496 → 79 kapcsolat és a 46 televízióparaméter a valódi adatokon külön ellenőrizhető. A hiányzó 2661 szülőhöz nem készül helyettesítő rekord. A valós gyökérmélységet és a paraméterkészlettel rendelkező kategóriák számát az élő jelentésből vesd össze az átadott 4, illetve 1807 értékkel.

A teljes webshopfa nem töltődött le a felhőbeli hálózati tiltás miatt. A technikai forrásvizsgálat külön, kézzel megismételhető a `scripts/research_reference_sources.py` eszközzel, megfelelő hozzáférés esetén; nem része automatikus telepítésnek vagy időzített szinkronnak. Részletek: [codex03a.md](codex03a.md).

## Valós magyar webshop-menü beépítése

A legújabb kiadás a 13 valós magyar főcsoportot jeleníti meg a kategóriaböngésző első szintjén. Az új adatforrás a repositoryban verziózott, validált menü-snapshot; a pinfo_db változatlan. Új migráció nincs (a meglévő 0003 alkalmazásadatmodell szükséges). A márka-, kampány- és szűrőhivatkozások nem kategóriák. Kezdetben nincs kitalált Marketplace-megfeleltetés: a bizonyítatlan elemek paraméterszáma ismeretlen, nem nulla.

A kézi frissítés és a célzott kiegészítő gyűjtő parancsai: [verified-webshop-navigation.md](verified-webshop-navigation.md). Ne írj át eMAG-azonosítókat, ne kapcsolj össze menü-ID-t és Marketplace-ID-t pusztán számegyezésből.
