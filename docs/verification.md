# CODEX 02 – ellenőrzési jegyzőkönyv

Dátum: 2026-11-13 (Europe/Budapest). Helyszín: izolált Codex felhőkörnyezet; **VPS-telepítés nem történt**.

## Eredmények

| Ellenőrzés | Eredmény |
| --- | --- |
| Backend pytest | **31 sikeres teszt**, 1 Starlette/AnyIO deprecation warning |
| Eredeti CODEX 01 tesztek | Továbbra is sikeresek |
| TypeScript + Vite build | Sikeres |
| Ruff alapellenőrzés (E9/F) az új backend-/tesztkódon | Sikeres |
| Docker Compose build, TLS-ellenőrzés és ideiglenesen mountolt CA | Sikeres backend-, migrátor-, worker- és frontend-image |
| MySQL 8.0 Alembic upgrade | **0002**, sikeres; ismételt upgrade is sikeres |
| Migráció és ORM-metaadat összevetése MySQL-en | Nincs eltérés |
| Szintetikus referenciafelhasználó SHOW GRANTS | USAGE és SELECT a három referencia-táblára |
| MySQL-alapú API-integráció | Belépés, CSRF, tenantizoláció, adminjogok, napló, kategóriafa, belső ID-kapcsolatok és kurzoros értéklapozás sikeres |
| Interaktív Superadmin-bootstrap | Docker TTY-val sikeres; jelszó nem szerepel argumentumban vagy kimenetben |
| Böngészőpróba Chromiumon | Asztali 1440×1000 és mobil 390×844 sikeres; nincs JavaScript-hiba vagy vízszintes oldal-túlcsordulás |
| Backend/Redis/worker/referencia readiness + Celery ping | Sikeres |
| GitHub Actions | Workflow hozzáadva backendteszthez, frontendbuildhez és Docker-buildekhez; távoli futás eredményét ez a jegyzőkönyv nem állítja |
| Valódi dev.pinfo.hu / VPS | Nem telepítettük és nem ellenőriztük újra |

## Tesztelt határok

- Hibás, ismeretlen és inaktív felhasználó belépése elutasított; a hiba nem árulja el a fiók létezését.
- HttpOnly/Secure/SameSite cookie, hash-elt sessiontoken, lejárat, logout, jelszócsere és visszavonás ellenőrzött.
- CSRF nélküli, nem ASCII CSRF-tokenes és idegen Originről érkező módosítás elutasított.
- Tenantadmin másik ügyfél listáját nem olvashatja/módosíthatja; Superadmin-jogot nem oszthat ki; megosztott fiók globális jelszavát nem írhatja át.
- Az utolsó aktív Superadmin és ügyféladmin védett; a szerep változása a következő kérésre érvényes.
- Adatfeldolgozó és ellenőrző referenciaadatot olvashat, adminfunkciót nem hívhat.
- A kategóriák külső eMAG-szülőazonosítója különbözik a belső ID-tól; hiányzó szülő belső-ID-ütközés esetén sem kapcsolódik tévesen. Ciklus és hiányzó szülő jelzett.
- Egy paraméter eMAG-ID-ja több kategóriában is előfordul: az értékek mindig a belső paraméter-ID szerint kerülnek lekérdezésre.
- 125 mesterséges paraméterérték lapozása tesztelt, ismétlés/kimaradás nélkül; az API legfeljebb 100 elemet enged kérni.
- A referencia API csak SELECT SQL-t ad ki; az engine megtagadja az író/DDL utasítást, az alkalmazás-migráció metadata-ja nem tartalmaz referencia-táblát.
- A kezdeti tesztfixture MySQL-klienskódolását javítottuk (`SET NAMES utf8mb4`); a javítás után az ékezetes felület és adatmegnevezések böngészőben is sikeresen ellenőrzöttek.

## Ismétlés

```bash
cd /workspace/adatdusito
bash scripts/cloud-install.sh
bash scripts/cloud-start.sh
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
```

A böngésző és az API-integrációs tesztekhez az izolált cloud adatbázisban létrehozott **teszt** Superadmin szükséges. Első alkalommal:

```bash
docker compose -f compose.yaml -f compose.cloud.yaml exec backend python -m app.bootstrap --email SAJAT_TESZT_EMAIL --name "Teszt admin"
.venv/bin/pip install -r scripts/browser-requirements.txt
```

Az integrációs eszköz kizárólag a helyi 18080-as portot használja. A tesztbelépési adatok egy checkouton kívüli, 0600 jogosultságú JSON-fájlban legyenek (`email`, `password` mezők); ne használj valódi VPS-belépést. Ez csak a teszteszköz inputja, nem alkalmazásbeállítás vagy alapértelmezett fiók.

```bash
.venv/bin/python scripts/verify_integration.py --credentials /BIZTONSAGOS_UTVONAL/test.json
.venv/bin/python scripts/browser_smoke.py --credentials /BIZTONSAGOS_UTVONAL/test.json
```

A böngészőteszt `/usr/bin/chromium` böngészőt használ; más gépen ezt az elérési utat szükség szerint módosítani kell. A tesztadatok az izolált cloud DB-ben megmaradnak, minden integrációs futás egyedi tesztügyfélneveket készít. A belépési limit a teszteszközökre is vonatkozik; sok ismételt futás után várd meg a 15 perces ablak végét, vagy használj külön tesztfiókot.

A jelen futás képernyőképei: `/tmp/adatdusito-codex02-browser/`. A repo nem tartalmaz jelszófájlt, `.env`-et, helyi DB-állapotot vagy képernyőképen rögzített valódi ügyféladatot.

## Átadás

A `compose.yaml` a megadott, működő VPS-konfigurációból csak az external `adatdusito-dev-net` blokkot emeli be a korábbi GitHub-verzióhoz. Meglévő szolgáltatás, port és VPS-hálózati paraméter nincs átírva. A felhőbeli teszthez kizárólag a külön `compose.cloud.yaml` indít szintetikus MySQL-t, másik Compose-projekttel és helyi porttal.

A 0001 migráció változatlan. Az új 0002 csak az `adatdusito_dev` adatbázist érintheti. A valódi referenciaadatbázis sémáját és a parent_id jelentését az üzemeltető adta át; a valós 2,8 milliós adathalmazon teljesítménymérést nem végeztünk. Értékszöveg részszavas keresésénél a meglévő indexek miatt nagy paraméterhalmazon lassabb lekérdezés előfordulhat; referenciaindex-módosítás nem történt.

A kézi VPS-frissítés, mentés, inicializálás és utóellenőrzés parancsai: [deployment.md](deployment.md). A GitHub-kód átadása nem telepítés, és nem igazolja a távoli HTTPS-működést.
