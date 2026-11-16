# AGENTS.md – közös fejlesztési szabályzat

Ez a fájl minden AI-fejlesztőre kötelező, aki ebben a repóban dolgozik (Codex, Claude és bárki más). Az eszközspecifikus kiegészítések külön fájlokban vannak (pl. `CLAUDE.md`), de ezt a szabályzatot nem írhatják felül.

## Szerepek

| Szerep | Ki | Feladata |
|---|---|---|
| Tulajdonos | a projekt gazdája (ember) | Jóváhagyja a feladatokat és a PR-okat, merge-el, engedélyezi a VPS-telepítést. |
| **Vezér** | ChatGPT | Koordinál: feladatokat oszt ki, fájlgazdát jelöl, Alembic-revíziót oszt ki, integrál. |
| Fejlesztő | Codex, Claude | A kiosztott feladatot a saját ágán valósítja meg, és PR-t nyit. |

Ha egy utasítás ellentmond ennek a fájlnak, a fejlesztő megáll, és a Vezértől vagy a Tulajdonostól kér döntést.

## Kötelező szabályok

1. **Külön ág és munkakönyvtár.** Minden AI saját Git-ágon és saját munkakönyvtárban (külön klón vagy `git worktree`) dolgozik. Ágnevek: `codex/<feladat>` és `claude/<feladat>`. A régebbi `feat/…` és `fix/…` ágakat nem írjuk újra.
2. **Tilos közvetlenül a `main` ágra pusholni.** A `main` csak a Tulajdonos által jóváhagyott PR-on keresztül változik. Az AI nem merge-el, és nem force-pushol más ágára.
3. **Egy fájlnak egyszerre egy fejlesztője van.** A fájlgazdát a Vezér jelöli ki (lásd: *Aktuális munkamegosztás*). Más gazdájú fájlhoz csak a Vezér előzetes jóváhagyásával lehet nyúlni. Ha erre szükség lenne, a fejlesztő a PR-leírásban írja le a kért változtatást.
4. **A másik fejlesztő munkáját tilos felülírni.** Nem lehet visszaállítani, újraformázni vagy „rendbe tenni” más módosításait, és más ágát sem lehet rebase-elni vagy módosítani. Ütközésnél a fejlesztő megáll, és jelzi a Vezérnek.
5. **Az Alembic-revíziókat a Vezér koordinálja.** Migráció csak kiosztott sorszámmal készülhet (`backend/migrations/versions/00NN_…`). A meglévő migrációk (`0001`–`0007`) változatlanok. A downgrade-nek működnie kell.
6. **Minden PR teszteléssel készül.** A teljes backend-tesztcsomagnak le kell futnia, és új viselkedéshez új teszt kell. Hibajavításhoz regressziós teszt kell, ami a javítás nélkül elbukna.
7. **A meglévő funkciók és adatok megmaradnak.** Nincs adatvesztő migráció, és nincs csendes viselkedésváltozás. Meglévő API-mező csak a Vezér döntésével törölhető vagy nevezhető át. A fiókok, munkamenetek és importadatok a frissítés után is érvényesek maradnak.
8. **A `pinfo_db` referencia-adatbázis csak olvasható.** Nem lehet bele írni, migrációt futtatni rajta vagy DDL-t küldeni neki. Az alkalmazás táblái kizárólag az alkalmazás-adatbázisba (`adatdusito_dev`) kerülnek.
9. **VPS-telepítés csak külön jóváhagyással.** AI nem futtat parancsot a VPS-en, és nem módosít ott Nginx-, tűzfal-, tanúsítvány- vagy `.env`-beállítást. A szükséges lépéseket a PR-ban kell leírni, a végrehajtásról a Tulajdonos dönt. Cloud fixture-t (`scripts/cloud-fixture.*`) soha nem lehet VPS-en vagy meglévő adatbázison futtatni.
10. **Minden feladat végén:** PR-link, a commitok listája, a teszteredmények (parancs és összesítés) és egy rövid változásösszefoglaló. Ha van, ide tartoznak a telepítéskor szükséges kézi lépések és a nyitott kérdések is.

## Aktuális munkamegosztás

A Vezér frissíti. Az `AGENTS.md` közös szabályzat, minden fejlesztőre kötelező; szerkesztője a táblázat szerint Claude, a tartalmi döntéseket a Vezér hozza. Utolsó módosítás: CATEGORY-03C (#29, a Vezér 2026-11-15-i döntése), 2026-11.

| Terület | Fájlgazda |
|---|---|
| `backend/app/security.py`, biztonsági backend-tesztek (`backend/tests/test_login_protection.py`, `test_password_hash_capacity.py`, `test_deploy_nginx.py`, `test_restricted_session_gate.py`, `test_dependency_*.py`) | Claude |
| Python-függőségfájlok: `backend/requirements*.{txt,in,lock}`, `backend/scripts/compile-requirements.sh`, `backend/scripts/check_requirements.py`, `backend/Dockerfile`, `backend/.dockerignore`; a CI backend-, browser- és menu-export jobjainak telepítési lépései | Claude |
| `deploy/nginx/*` (külső Nginx deploykonfiguráció) | Claude |
| CATEGORY-02A: `backend/app/product_models.py`, `product_catalog.py`, `product_backfill.py`, `workspace_views.py`, az `import_engine.py` termék-/forrásattribútum-része, az `import_api.py` futáskorlát-ellenőrzése, a `settings_api.py`/`system_config.py` `classification` csoportja, `backend/migrations/versions/0009_product_classification.py`, `backend/tests/test_product_classification.py`, `test_category02a_migration.py`, `docs/design/CATEGORY-02A-API.md` | Claude |
| CATEGORY-02C (donoraudit): a `product_catalog.py` és a `workspace_views.py` `pending_review` donorokat kizáró része, `backend/reference_data/donor_review.json`, a `test_product_classification.py` 02C-tesztjei | Claude |
| CATEGORY-03A: `backend/app/product_parameters.py`, `parameter_views.py`, `product_jobs.py`, a `product_models.py` paramétermodelljei, `backend/migrations/versions/0010_product_parameters.py`, `backend/tests/test_product_parameters.py`, `test_category03a_migration.py`, `docs/design/CATEGORY-03A-API.md`, `docs/category-03a-open-decisions.md`, `scripts/mysql_category03a_check.py` | Claude |
| CATEGORY-03C: `backend/app/bulk_operations.py`, `bulk_views.py`, a `product_models.py` kiválasztási, műveleti és jóváhagyási modelljei, `backend/migrations/versions/0011_bulk_preparation.py`, `backend/tests/test_bulk_preparation.py`, `test_category03c_migration.py`, `docs/design/CATEGORY-03C-API.md`, `scripts/mysql_category03c_check.py` | Claude |
| `backend/app/worker.py`: az `app.product_jobs` Celery-regisztrációja (#18) | Claude (csak ez a bekötés; más `worker.py`-változást integrációnál egyeztetni kell) |
| SECURITY-01 érintett pontjai: `backend/app/api.py` login-végpont, `backend/app/auth_api.py` `throttle()`/`failure_limit()` és a passkey/MFA korlátozási hívások, `backend/app/oidc_api.py` és `backend/app/registration.py` korlátozási sorai, `backend/tests/conftest.py` stubok, `backend/tests/test_security_integration.py`, `.env.example` biztonsági változói | Claude (csak ebben a feladatban) |
| `AGENTS.md`, `CLAUDE.md` | Claude (a tartalmi döntéseket a Vezér hozza) |
| `frontend/**` (React UI/UX, Cloud & Teal design, ikonok, súgók, komponensek, `frontend/nginx.conf`), ezen belül a `frontend/src/parameters/**` és a frontend API-adapterek; a böngészős integrációs tesztek | Codex |
| Minden más | a Vezér feladatonként jelöli ki; kijelölés nélkül nem módosítható |

## Fejlesztési és tesztelési parancsok

```bash
python3.12 -m venv .venv && .venv/bin/pip install --no-deps -r backend/requirements.lock -r backend/requirements-test.lock
PYTHONPATH=backend .venv/bin/pytest -q backend/tests          # kötelező minden PR előtt
(cd frontend && npm ci && npm run build)                      # frontendváltozásnál
.venv/bin/pip install -r scripts/browser-requirements.txt     # böngészőtesztekhez (Chromium)
```

A tesztek SQLite-ot és hamis Redist használnak, valódi adatbázishoz nem kapcsolódnak. A CI (`.github/workflows/ci.yml`) ugyanezeket futtatja.

## Biztonsági alapelvek

- A hitelesítés, a CSRF, a jogosultság-ellenőrzés és a belépési korlátozás csak szigorodhat. Gyengíteni csak a Vezér kifejezett döntésével lehet.
- Titok nem kerülhet Gitbe (`.env`, jelszó, token, SMTP-adat). Új beállítás a `.env.example`-be kerül, biztonságos alapértékkel.
- Hibaválasz nem tartalmazhat jelszót, request bodyt, tokent vagy szolgáltatói hibaüzenetet.
- Az `Origin`/CSRF-védelmet és a `no-store` fejlécet minden új végpontnak meg kell tartania.

## Konvenciók

- A felhasználói felület és a hibaüzenetek magyarul, a kód, az azonosítók és a commitüzenetek angolul készülnek.
- Commitonként egy logikai változás, a tesztek és a dokumentáció a hozzá tartozó committal együtt.
- A PR-leírás tartalmazza: cél, változások, tesztek, telepítési teendők, kockázatok és visszaállítás.
- A dokumentáció a `docs/` mappába kerül. A README-t csak a Vezér kijelölésével lehet módosítani.
