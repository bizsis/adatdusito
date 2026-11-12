# Adatdúsító – fejlesztői infrastruktúra

FastAPI / React–TypeScript / Celery–Redis / meglévő MySQL 8.0.
Üzleti funkció és éles telepítés még nincs.

## Helyi fejlesztés

Python 3.12, Node 22.12+ és Docker Compose szükséges.
`bash scripts/cloud-install.sh` a Codex /workspace/adatdusito könyvtárában telepít és tesztel.
Más gépen ugyanazok a parancsok a projekt gyökeréből futtathatók.

- Backend: `cd backend && ../.venv/bin/uvicorn app.main:app --reload`
- Frontend build: `cd frontend && npm ci && npm run build`
- Teljes stack: töltsd ki a `.env.example` alapján létrehozott, Gitből kizárt `.env` fájlt, majd `docker compose up -d --build`.
- Telepítési ellenőrzés a projekt gyökeréből: `bash scripts/smoke.sh`.
- Backendtesztek: `PYTHONPATH=backend .venv/bin/pytest -q backend/tests`.

A frontend konténer Nginxen szolgálja ki a React buildet, és továbbítja az /api kéréseket.
Csak a 127.0.0.1:8080 port publikált. Redis és backend csak a Compose-hálózaton érhető el.
Nincs MySQL-szolgáltatás a Compose-ban: a meglévő szervert használja.
A worker két folyamatot használ; a Redis sor jelenleg nem tartós (csak infrastruktúra-próbára).

`/api/health/live`: folyamatállapot. `/api/health/ready`: alkalmazás-DB, három referenciatábla,
Redis és worker. Hibánál 503; hitelesítési adatot nem ad vissza.
A migráció külön, egyszer lefutó konténer; csak sikeres migráció után indul az alkalmazás.
Az első migráció csak az Alembic verziókövetését hozza létre, üzleti táblákat nem.

A telepítési eljárás: [docs/deployment.md](docs/deployment.md).
Az ellenőrzések eredménye: [docs/verification.md](docs/verification.md).

## Codex felhőkörnyezet

Telepítés: `bash scripts/cloud-install.sh`. Indítás: `bash scripts/cloud-start.sh`.
A `compose.cloud.yaml` kizárólag a felhőbeli próbához ad hozzá külön MySQL-konténert,
három üres referenciatáblával. Nincs valódi eMAG-adat a tesztkörnyezetben.
Ezt az override-ot a VPS-en **ne használd**. A jelszavak véletlenszerűen generálódnak,
a Gitből kizárt `.cloud-state` könyvtárba kerülnek; ne töröld külön a DB állapotától.
A felhőben futó HTTP-szolgáltatás nem jelenti a dev.pinfo.hu telepítését.
