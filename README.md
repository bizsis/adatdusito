# Adatdúsító · CODEX 05

**Aktuális működés:** a felhasználó által jóváhagyott magyar kategóriafa rögzített: 13 főcsoport, összesen 584 pont. A forrásadatbázis paramétereket és értékeket biztosít; `is_allowed` jelzője nem módosítja a fa láthatóságát vagy a paraméter-hozzárendelést. Új forráskategóriák nem bővítik a felhasználói fát. A már betöltött értékeket nem kell újraimportálni vagy aktiválni. [CODEX 05: rögzített fa, egységes paraméterszerkesztő, lefedettség](docs/codex05.md).

A saját adatkönyvtár importjának, ellenőrzésének és helyreállításának korábbi útmutatója: [CODEX 04](docs/codex04.md).

Magyar nyelvű, többügyfeles adminfelület FastAPI, React/TypeScript, Celery/Redis és a meglévő MySQL 8.0 használatával.

## Funkciók

- Cookie-alapú bejelentkezés, kijelentkezés, 8 órás szerveroldali munkamenet és saját jelszócsere.
- Scrypt jelszóhash (N=131072, r=8, p=1), CSRF-védelem, Redis-alapú belépési korlátozás.
- Superadmin, ügyféladminisztrátor, adatfeldolgozó és ellenőrző szerepkör; backend által ellenőrzött jogosultságok.
- Ügyfelek, felhasználók, tagságok és adminisztrációs napló. Tenantváltás mindig ellenőrzött tagsággal.
- Közös kategóriafa, automatikus név-/környezetalapú összerendelés, keresés, kötelező/opcionális paraméterek és kurzorral lapozott értéklisták. A pinfo_db továbbra is csak olvasható importforrás.
- Reszponzív adminfelület, rendszerállapot, bejelentkezéssel védett OpenAPI dokumentáció: `/api/v1/docs`.

Nincsenek alapértelmezett belépési adatok. Az első Superadmin interaktív paranccsal jön létre:

```bash
docker compose exec backend python -m app.bootstrap --email admin@example.hu --name "Rendszergazda"
```

Az emailt és a nevet cseréld a sajátodra. A jelszót a program rejtetten kéri be; ne add át argumentumban vagy környezeti változóban.

## Meglévő VPS-infrastruktúra

A projekt a `/opt/adatdusito` könyvtárban működő fejlesztői infrastruktúrát használja. A `compose.yaml` a már létező `adatdusito-dev-net` external hálózatot és a `127.0.0.1:8080` publikált portot tartja meg. Nem hoz létre MySQL-kiszolgálót, nem módosít tűzfalat, Nginxet vagy tanúsítványt. A meglévő MySQL a `172.28.10.1:3306` címen érhető el a konténerek számára.

A `.env` titkos, Gitből kizárt fájl. Az `APP_DATABASE_URL` kizárólag az `adatdusito_dev`, a külön SELECT-jogú `REFERENCE_DATABASE_URL` kizárólag a `pinfo_db` adatbázisra mutathat. HTTPS-nél `COOKIE_SECURE=true`, `APP_ORIGIN=https://dev.pinfo.hu`. A forrásadatbázishoz nincs író API vagy migráció; a saját katalógus új táblái az alkalmazás-adatbázisba kerülnek.

A `0001`–`0004` migráció változatlan. A `0005` hozza létre a saját, verziózott katalógust. [Aktuális kézi VPS-frissítés, teljes importellenőrzés és mentés](docs/codex04.md).

## Izolált felhőbeli fejlesztés

Python 3.12, Node 22.12+ és Docker Compose 2.24.4+ szükséges (`!override` támogatás).

```bash
cd /workspace/adatdusito
bash scripts/cloud-install.sh
bash scripts/cloud-start.sh
```

A `compose.cloud.yaml` külön `adatdusito-cloud` projektet, saját hálózatot és szintetikus MySQL-példányt használ; a felhőbeli HTTP-port 18080. A `.cloud-state/codex02` mappában generált hitelesítések és a tesztadatbázis volume-ja megőrzendők. A fixture-t **soha ne futtasd VPS-en vagy meglévő adatbázison**. A korábbi CODEX 01 felhőbeli tesztadatokhoz nem nyúlunk. A helyi HTTP-hez kizárólag az override állítja `false` értékre a Secure cookie-kapcsolót.

```bash
.venv/bin/pip install -r scripts/browser-requirements.txt
(cd frontend && npm ci && npm run build)
# Chromium szükséges a böngészőtesztekhez: /usr/bin/chromium
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests
# A felhőbeli stack esetén:
COMPOSE_FILE=compose.yaml:compose.cloud.yaml bash scripts/smoke.sh http://127.0.0.1:18080
```

Böngészőteszt: `pip install -r scripts/browser-requirements.txt`, majd a [tesztútmutató](docs/verification.md) szerint. Backend fejlesztői indítása: `cd backend && ../.venv/bin/uvicorn app.main:app --reload`; ehhez valódi, külön alkalmazás- és referencia-kapcsolat kell.

## Referenciaséma

- `emag_category_parameters.category_id → emag_categories.id` (belső azonosító).
- `emag_parameter_values.parameter_id → emag_category_parameters.id` (belső azonosító).
- `emag_categories.parent_id → emag_categories.emag_category_id` (külső eMAG-azonosító).

A parent_id szemantikáját az üzemeltető az eredeti szinkronizáló forráskódjából ellenőrizte. A 94 hiányzó szülő a referenciaadatok tulajdonsága: ezek elkülönített, felülvizsgálható elemek, nem új gyökerek. Főszinten kizárólag a 13 hitelesített főcsoport jelenik meg. Ciklusnál és túl mély láncnál szintén figyelmeztet. A több millió értékből legfeljebb 100 kérhető egy API-oldalon, a felület 50-et kér; nincs teljes értéklista-betöltés vagy teljes táblás összesítésszámítás.

[API és biztonsági szerződés](docs/api.md) · [Ellenőrzési jegyzőkönyv](docs/verification.md)


## Előzmény: CODEX 03A – egységes referenciafa

A kategóriaböngésző most megkülönbözteti a strukturális és a termékbesorolható kategóriákat. Az alapnézet a besorolható kategóriák teljes ismert szülőfája; a további nem törölt ágak ugyanannak a fának a megjelenítési szűrőjével érhetők el. A Deleted jelölésű rekordok rejtettek. A hiányzó és ciklikus szülőkapcsolatok jelzettek, kitalált pótlás nincs.

A `0003` migráció globális forrásnyilvántartást ad az alkalmazásadatbázishoz; nem másolja és nem módosítja a pinfo_db kategóriáit. A 0001/0002 változatlan. A korábbi aktív-only javítás működését ez a fázis szándékosan pontosítja: nem besorolható szülő most navigálható lehet, de a `/reference/categories/{id}/selection` végpont továbbra sem enged rá termékbesorolást.

[Adatmodell, forrásvizsgálat, lefedettség és korlátok](docs/codex03a.md). Az új publikus források letöltését a jelenlegi felhőbeli hálózati szabályzat tiltja; a teljes magyar webshopfa megszerzését nem állítjuk. Élő lefedettségi jelentés: `docker compose exec -T backend python -m app.reference_report`.

## A magyar eMAG vásárlói menüjének exportja saját gépről

A Marketplace gyökerei nem azonosak a 13 vásárlói főcsoporttal. A tényleges menüadatok begyűjtéséhez új, külön futó eszköz készült: `scripts/export_emag_menu.py`, illetve telepítés nélküli konzolos változata `scripts/emag_menu/menu_capture.js`. Adatbázisba egyik sem ír. [Windows/Chrome parancsok és kézi export](docs/emag-menu-export.md).

## Előzmény: valós webshop-menü, 13 főcsoport

A kategóriaböngésző most a Windowsról átadott, ellenőrzött ZIP 13 magyar főcsoportjával indul, az eredeti sorrendben. A márkák, kampányok és paraméterszűrők nem külön termékkategóriák. Az eredeti CODEX 03A még külön igazolást kért; ezt a CODEX 03B automatikus, név-/környezetalapú összerendelése és a CODEX 04 saját katalógusa váltotta fel. Puszta forrásazonosító-számegyezésből továbbra sincs összekapcsolás. [Feldolgozási bizonyíték, hiányok, kiegészítő gyűjtő és frissítés](docs/verified-webshop-navigation.md).
