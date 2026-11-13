# Adatdúsító · CODEX 02

Magyar nyelvű, többügyfeles adminfelület FastAPI, React/TypeScript, Celery/Redis és a meglévő MySQL 8.0 használatával.

## Funkciók

- Cookie-alapú bejelentkezés, kijelentkezés, 8 órás szerveroldali munkamenet és saját jelszócsere.
- Scrypt jelszóhash (N=131072, r=8, p=1), CSRF-védelem, Redis-alapú belépési korlátozás.
- Superadmin, ügyféladminisztrátor, adatfeldolgozó és ellenőrző szerepkör; backend által ellenőrzött jogosultságok.
- Ügyfelek, felhasználók, tagságok és adminisztrációs napló. Tenantváltás mindig ellenőrzött tagsággal.
- Csak olvasható eMAG-kategóriafa, keresés, adatlap, kötelező/opcionális paraméterek és kurzorral lapozott értéklisták.
- Reszponzív adminfelület, rendszerállapot, bejelentkezéssel védett OpenAPI dokumentáció: `/api/v1/docs`.

Nincsenek alapértelmezett belépési adatok. Az első Superadmin interaktív paranccsal jön létre:

```bash
docker compose exec backend python -m app.bootstrap --email admin@example.hu --name "Rendszergazda"
```

Az emailt és a nevet cseréld a sajátodra. A jelszót a program rejtetten kéri be; ne add át argumentumban vagy környezeti változóban.

## Meglévő VPS-infrastruktúra

A projekt a `/opt/adatdusito` könyvtárban működő fejlesztői infrastruktúrát használja. A `compose.yaml` a már létező `adatdusito-dev-net` external hálózatot és a `127.0.0.1:8080` publikált portot tartja meg. Nem hoz létre MySQL-kiszolgálót, nem módosít tűzfalat, Nginxet vagy tanúsítványt. A meglévő MySQL a `172.28.10.1:3306` címen érhető el a konténerek számára.

A `.env` titkos, Gitből kizárt fájl. Az `APP_DATABASE_URL` kizárólag az `adatdusito_dev`, a külön SELECT-jogú `REFERENCE_DATABASE_URL` kizárólag a `pinfo_db` adatbázisra mutathat. HTTPS-nél `COOKIE_SECURE=true`, `APP_ORIGIN=https://dev.pinfo.hu`. A referenciákhoz nincs író API vagy migráció.

A `0001` migráció változatlan; a `0002` kizárólag alkalmazástáblákat hoz létre. [Kézi VPS-frissítés és mentés](docs/deployment.md).

## Izolált felhőbeli fejlesztés

Python 3.12, Node 22.12+ és Docker Compose 2.24.4+ szükséges (`!override` támogatás).

```bash
cd /workspace/adatdusito
bash scripts/cloud-install.sh
bash scripts/cloud-start.sh
```

A `compose.cloud.yaml` külön `adatdusito-cloud` projektet, saját hálózatot és szintetikus MySQL-példányt használ; a felhőbeli HTTP-port 18080. A `.cloud-state/codex02` mappában generált hitelesítések és a tesztadatbázis volume-ja megőrzendők. A fixture-t **soha ne futtasd VPS-en vagy meglévő adatbázison**. A korábbi CODEX 01 felhőbeli tesztadatokhoz nem nyúlunk. A helyi HTTP-hez kizárólag az override állítja `false` értékre a Secure cookie-kapcsolót.

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
(cd frontend && npm ci && npm run build)
# A felhőbeli stack esetén:
COMPOSE_FILE=compose.yaml:compose.cloud.yaml bash scripts/smoke.sh http://127.0.0.1:18080
```

Böngészőteszt: `pip install -r scripts/browser-requirements.txt`, majd a [tesztútmutató](docs/verification.md) szerint. Backend fejlesztői indítása: `cd backend && ../.venv/bin/uvicorn app.main:app --reload`; ehhez valódi, külön alkalmazás- és referencia-kapcsolat kell.

## Referenciaséma

- `emag_category_parameters.category_id → emag_categories.id` (belső azonosító).
- `emag_parameter_values.parameter_id → emag_category_parameters.id` (belső azonosító).
- `emag_categories.parent_id → emag_categories.emag_category_id` (külső eMAG-azonosító).

A parent_id szemantikáját az üzemeltető az eredeti szinkronizáló forráskódjából ellenőrizte. A 94 hiányzó szülő a referenciaadatok tulajdonsága: a böngésző ezeket figyelmeztetéssel, gyökérszinten is megjeleníti. Ciklusnál és túl mély láncnál szintén figyelmeztet. A több millió értékből legfeljebb 100 kérhető egy API-oldalon, a felület 50-et kér; nincs teljes értéklista-betöltés vagy teljes táblás összesítésszámítás.

[API és biztonsági szerződés](docs/api.md) · [Ellenőrzési jegyzőkönyv](docs/verification.md)
