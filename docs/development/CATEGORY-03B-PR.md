## Eredmény

Refs #24, https://github.com/bizsis/adatdusito/issues/24#issuecomment-6902773899.
PR #27 most a **#26 / c05746d működő FastAPI API-jára épülő frontend-integráció**.
Base változatlanul #22 (`codex/category-02d-integration`, `a780c65`), head
`codex/category-03b-frontend`. A közös ellenőrző ág
`codex/category-03b-api-integration`; nincs main-merge és VPS-telepítés.

A produkciós adapter mind a tíz kész műveletet használja a közös session/CSRF/tenant
klienssel: termékáttekintés, tárolt paraméterek, szerveres preview/apply, kézi PATCH,
alias GET/POST/DELETE és háttérfutás indítás/állapot. Szigorú runtime DTO-ellenőrzés,
valódi 401/403/404/409/422/503 hibakezelés és friss betöltés szükséges írási hiba után.
Nyers forrás és kézi zárolás megmarad; `pending_review` nem készít automatikus
`emag:` helyet, többdonoros kategóriához explicit választás kell. Ez nem donorjóváhagyás.

Az egytermékes apply csak termékrevíziót küld, nem előnézeti tokent. A scoped
preview/apply job külön művelet, legfeljebb 50 000 termék/futás. A többfutásos
feldolgozás a valódi `has_more` / `next_start_after_product_id` alapján, külön
felhasználói indítással működik; a teljes termékállomány nincs 50 000-re korlátozva.
A UI nem számol hamis százalékot a futáskorlátból.

Az általános bulk snapshot/token/apply, külön előkészítési jóváhagyás, teljes
auditlapozás és univerzális allowed-values CRUD továbbra sincs produkcióba kötve.
Kötött listás helyen szabad értékadás tiltott; valódi forrásjelölt elfogadható.
A lokális PATCH/alias/job megerősítés nincs szerveres dry-runnak nevezve.

## API-eltérések / átadandó Claude-nak

A pontos reprodukciók és kezelések: `docs/development/CATEGORY-03B-STATUS.md`.
A tényleges konverziós factor decimális szöveg is; a review candidates harmadik
alakja `{source_key,header,raw}`; `pending_source` nincs kiszerializálva, ezért a
friss nyers forrást a termékrészletből, azonos explicit kulccsal olvassuk.
Saját kötelezőség, paramétertípus, kategóriamegkötés és általános allowed-value
kapcsolat hiányában nincs kitalált adat. Teljes job-total/resume/cancel sem garantált.
Backendfájlt, migrációt, dependency lockot nem változtat ez a PR.

## Ellenőrzés

Az alábbi parancsok a #26 backenddel egyesített, izolált közös tesztágra vonatkoznak.
A frontend-only PR-nál az új natív 03A tesztek dependency-skipet kapnak, amíg a
backend nincs a base-ben. Ez nem helyettesíti a közös tesztág futását.

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py
PYTHONPATH=backend .venv/bin/pytest -q -ra --durations=5 scripts/tests/test_parameter_api_browser.py
.venv/bin/pytest -q scripts/tests/test_emag_menu_export.py
(cd frontend && npm run lint && npm run test:lint && npm run build && npm audit --audit-level=moderate)
docker build -t adatdusito-ci-backend backend
docker build -t adatdusito-ci-frontend frontend
```

- Backend/eszközök: **410 passed**.
- Korábbi böngészős regresszió: **113 passed**, párhuzamos fájlcsoportokban
  (14 backend-browser + 74 script-browser + 21 CATEGORY-02D + 4 célzott CATEGORY-02D).
  A 32 paraméter-prezentációs mockteszt ebbe beleszámít.
- Új natív paraméter-API E2E: **21 passed**, 257,96 s, a végleges kinyitható
  termékparaméter-panellel együtt. Összes böngészőteszt: **134 passed**.
- Menüexport: **14 passed**.
- ESLint, TypeScript/Vite, Node 22 és **3 lintkonfigurációs teszt** sikeres.
- Backend/frontend Docker build sikeres; backend import/pip check és runtime-only
  csomagellenőrzés sikeres; frontend tesztharness nincs az image-ben.
- npm audit (dev függőségekkel együtt): **0 sérülékenység**.

A natív paramétertesztek valódi FastAPI/SQLite kérések, produkciós frontenddel,
390/1440 px-en. Mind a hét slotállapot, mértékegység-konverzió, zárolás,
feedfrissítés, donorvédelem, aliasjogok, hibakódok és tenantizoláció tesztelt.
Öt külön megjelölt transport-hibateszt hibás JSON-t injektál a valódi válasz után.
A 50 002 ténylegesen tárolt terméken két valódi worker-preview **50 000 + 2**
rekordot dolgoz fel paraméterírás nélkül; a scoped apply külön tesztje idempotens.
Az enqueue helyettesített, a workerfüggvény valódi; nincs Celery/Redis infraígéret.
A 32 meglévő paraméter-prezentációs teszt mock UI-regresszió, külön bizonyítékként.
**Saját MySQL-mérés nincs; az adatmennyiségi E2E SQLite.**

## Integráció és visszaállítás

A #26 backend és annak saját 0010 migrációja függőség; ebben a frontend-PR-ban
nincs új migráció. A tulajdonos dönt az integrációról/base-ről. A main, VPS, .env,
Compose, pinfo_db, fix kategóriafa változatlan. Visszaállítás a frontend-változás
visszavonása; szerveradatot nem töröl.

A GitHub GraphQL API HTTP 403-at ad ebből a környezetből. A PR szövegének
szerkesztési kísérlete sikertelen; ez a fájl a kész, átadható PR-leírás. A push
frissíti #27 kódját. Hosted CI csak ténylegesen megfigyelt eredménnyel nevezhető
sikeresnek, a helyi zöld ellenőrzéseket nem nevezzük hosted eredménynek.
