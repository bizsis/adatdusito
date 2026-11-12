# VPS telepítési terv – kizárólag fejlesztői környezet

## 1. Kötelező felmérés, változtatás nélkül

SSH: root@167.86.70.129, 22-es port. Előbb ellenőrizd a szerver hostkulcsát megbízható csatornán.
Jelszó és privát kulcs csak biztonságos hozzáférési beállításba kerülhet.

A szerveren: `cat /etc/os-release`, `free -h`, `df -h`, `ss -lntup`,
`systemctl --no-pager status nginx mysql docker`, `docker ps`, `docker compose version`,
`nginx -t`, `nginx -T`, `certbot certificates`.
A teljes Nginx-konfigurációt helyben vizsgáld meg; érzékeny részeket ne másolj naplóba.
Ellenőrizd a dev.pinfo.hu A/AAAA rekordját, a 80/443 és a 8080 port foglaltságát,
a tűzfalat, a MySQL bind-address értékét, és a Docker-hálózatot.
MySQL-adminnal: `SELECT VERSION(); SHOW DATABASES;` és a három referencia-tábla
`SHOW CREATE TABLE` eredménye, valamint a meglévő jogosultságok ellenőrzése.
A pinfo.hu aktuális HTTP/HTTPS működéséről készüljön változtatás előtti ellenőrzés.

## 2. Adatbázis és hozzáférés

A meglévő MySQL-t ne telepítsd újra, ne indítsd újra felmérés és szükség esetén jóváhagyás nélkül.
Készíts mentést a releváns konfigurációkról; a referencia-adatokat ne módosítsd.
Az admin hozza létre az `adatdusito_dev` adatbázist utf8mb4 karakterkészlettel.
Külön felhasználók szükségesek; az alábbi jogosultságok csak a felmért Docker-forráshostról:

```sql
GRANT ALL PRIVILEGES ON adatdusito_dev.* TO 'adatdusito_app'@'<ellenőrzött forráshost>';
GRANT SELECT ON pinfo_db.emag_categories TO 'adatdusito_ref'@'<ellenőrzött forráshost>';
GRANT SELECT ON pinfo_db.emag_category_parameters TO 'adatdusito_ref'@'<ellenőrzött forráshost>';
GRANT SELECT ON pinfo_db.emag_parameter_values TO 'adatdusito_ref'@'<ellenőrzött forráshost>';
```

Ezek sablonok, nem automatikusan futó SQL-ek. A CREATE USER parancshoz egyedi, biztonságosan
kezelt jelszó kell; ne használd a '%' hostot. Ellenőrizd a SHOW GRANTS eredményét:
a referenciafelhasználó ne kapjon globális jogot, szerepkört vagy írási jogosultságot.
Írással ne teszteld a referencia-hozzáférést. Az alkalmazás olvasási tranzakciót is használ,
de az elsődleges védelem a MySQL-jogosultság.
A migráció ugyanazt a fejlesztői DB-felhasználót használja; később külön migrátori jogosultság javasolt.
Ne használj admin/root DB-hitelesítést az alkalmazáshoz.

A host.docker.internal a Docker bridge gatewayre mutat. Ha a MySQL csak 127.0.0.1-en figyel,
a konténerek nem érik el: a felmérés alapján külön megoldás és a meglévő MySQL-konfiguráció
módosítása előtt jóváhagyás szükséges. A 3306 portot ne nyisd ki az internetre.

## 3. Alkalmazás

Telepíts külön könyvtárba. Hozd létre a `.env` fájlt 0600 jogosultsággal,
a mintában szereplő jelszavakat cseréld; URL-kódold a speciális karaktereket.
A REDIS_URL maradjon redis://redis:6379/0.
`docker compose config --quiet`, majd `docker compose up -d --build`.
Ellenőrizd: `docker compose ps -a`, `docker compose logs --tail=100`,
`bash scripts/smoke.sh`. A migrációs konténer 0 kóddal álljon le.
A smoke teszt valódi Celery-feladatot küld és ellenőrzi a pong eredményt.

## 4. Nginx és HTTPS – aktiválás csak felmérés után

A deploy/nginx fájlok előkészített sablonok. Nem kerültek a VPS-re.
Meglévő fájlt ne írj felül. Meglévő szolgáltatás konfigurációjának módosítása,
leállítása vagy Nginx reload előtt kérj jóváhagyást a konkrét diff és nginx -t alapján.

Először csak az új HTTP-vhost kerüljön külön fájlba, az ACME-webroot
/var/www/letsencrypt legyen létrehozva. Sikeres `nginx -t` és jóváhagyott reload után
ellenőrizd a challenge fájl kiszolgálását. A tanúsítványt webroot módban igényeld:
`certbot certonly --webroot -w /var/www/letsencrypt -d dev.pinfo.hu`.
A szükséges kapcsolattartási emailt az üzemeltető adja meg; az ÁSZF-et az üzemeltető fogadja el.
Ezután aktiválható a külön HTTPS-vhost, új nginx -t és jóváhagyott reload után.
Ne használd a meglévő pinfo.hu vhostot vagy a certbot automatikus Nginx-átírását.
Ellenőrizd a megújítás időzítőjét, a `certbot renew --dry-run` eredményét és a
megújítás utáni jóváhagyott Nginx reload mechanizmusát.

Végső ellenőrzés: HTTPS-tanúsítvány és átirányítás, frontend, /api/health/live,
/api/health/ready, Celery smoke, valamint pinfo.hu előtte/utána ellenőrzése.
Hiba esetén csak az új projekt konténereit állítsd le; a MySQL-hez és a meglévő
pinfo.hu-konfigurációhoz ne nyúlj. Adatbázist visszaállításkor se törölj automatikusan.
Éles adatbázist és éles alkalmazást ez az eljárás nem telepít.
