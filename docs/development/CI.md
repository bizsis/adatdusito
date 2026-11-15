# Continuous integration

Status: **Implemented** in QUALITY-01 (`claude/quality-01`). This page describes the GitHub Actions configuration in `.github/workflows/`. The general testing guide is `docs/development/TESTING.md`, which is maintained by the DOCS-01 branch. The section proposed for it is at the end of this page.

## Workflows

### `ci.yml`: runs on pull requests, pushes to `main` and manual dispatch

| Job | What it checks | Blocking |
|---|---|---|
| `backend` | `backend/tests` + `scripts/tests`, except browser tests and the menu-export test. Dependencies are installed from `backend/requirements.lock` + `backend/requirements-test.lock` with `--no-deps`, then checked with `pip check` and `backend/scripts/check_requirements.py --resolve`. | yes |
| `browser` | `backend/tests/*_browser.py` + `scripts/tests/*_browser.py` (Playwright and Chromium) against a fresh `vite build` of the frontend | yes |
| `menu-export` | `scripts/tests/test_emag_menu_export.py`, installed with **only** `scripts/browser-requirements.txt` and the test lock (pytest), the way the Windows export tool is used | yes |
| `frontend` | `npx tsc --noEmit -p tsconfig.json` (explicit type check), then `npx vite build` | yes |
| `docker` | builds both images with BuildKit and the GitHub Actions layer cache, without pushing; checks that the backend image has no test packages or tests and that `pip check` passes | yes |
| `eslint` | lints `frontend/src` with an isolated toolchain and writes a report only | **no** (advisory) |
| `ci-ok` | one aggregated required status for branch protection | yes |

**Test partition.** Every test file runs in exactly one job:
- `backend`: everything that does not match `*_browser.py`, except the menu-export test
- `browser`: every file matching `*_browser.py`
- `menu-export`: the one remaining file

A new test file is therefore picked up automatically. A file that needs Chromium must be named `*_browser.py`.

**Concurrency and limits.**
- A newer push to the same PR cancels the previous run. Runs on `main` are never cancelled.
- Every job has a `timeout-minutes` limit, so a hung browser cannot use up the 6-hour default.

### `dependency-audit.yml`: non-blocking vulnerability report

Triggers:
- a PR that changes a dependency manifest
- a push to `main`
- every Monday at 04:37 UTC (new advisories appear without code changes)
- manual dispatch

It audits:

| Input | Tool |
|---|---|
| `backend/requirements.lock` (runtime, pinned, audited as-is) | `pip-audit --no-deps` |
| `backend/requirements-test.lock` (test-only, dev-only class) | `pip-audit --no-deps` |
| `scripts/browser-requirements.txt` | `pip-audit` |
| `frontend/package-lock.json` | `npm audit`, runs twice: once with `--omit=dev` (runtime) and once for everything |

`.github/scripts/ci_report.py audit` merges and deduplicates the results and sorts each finding into one class:

| Class | Rule | Expected action |
|---|---|---|
| **actionable** | runtime dependency (backend lock, except test-only packages; npm production dependency) with a published fix | upgrade, own PR with tests |
| runtime-nofix | runtime dependency, no fix published | assess exposure (often disputed or not reachable), monitor |
| dev-only | test or build tooling: `pytest`, `playwright`, npm `devDependencies` such as `vite` | upgrade when convenient; not on the production request path |

- The report appears in the job summary.
- Actionable rows also appear as warning annotations. Upgrades that cross a major version are marked as "major upgrade".
- The raw JSON reports are kept as an artifact for 14 days.
- The job never fails because of findings. Setting `FAIL_ON_ACTIONABLE: "true"` in the workflow makes actionable findings blocking once the backlog is cleared.

**Status after DEPENDENCY-01 (`claude/dependency-01`, based on `main` @ `25fa33c`).** The baseline on `1d613fe` reported 27 actionable runtime findings, 1 disputed no-fix finding and 2 dev-only packages. Every runtime finding was checked against the advisory text and the package changelog. The upgraded lock has **0 actionable** and **0 runtime-nofix** findings:

| Package | Before → after | Advisories closed | Reachability in this app | Compatibility notes |
|---|---|---|---|---|
| PyJWT | 2.10.1 → **2.15.1** | 16 with a fix (2.12.0–2.15.0) and the disputed CVE-2025-45768, which no longer matches | Google ID-token verification (`oidc_api.claims`): `PyJWKClient` with a fixed HTTPS URL, RS256 only. Tokens arrive from Google's token endpoint over TLS, so most HMAC/JWK-confusion advisories were not exploitable, but `crit` handling, non-Base64URL signature segments and JWKS refresh/DoS behaviour applied. | No API change for the calls used. Since 2.11 `iss` must be a string. Covered by `test_dependency_oidc_jwt.py`, which uses the real `PyJWKClient` path. |
| python-multipart | 0.0.20 → **0.0.32** | 6 (fixes in 0.0.22–0.0.31) | Every multipart upload (supplier import, export reference workbook) and urlencoded form goes through Starlette into this parser: header-count, preamble/epilogue, negative Content-Length and separator DoS issues were reachable without login on Form endpoints. The path-traversal advisory needs `UPLOAD_KEEP_FILENAME`, which is not used here. | 0.0.32 adds only a boundary-scan speed-up over 0.0.31. 0.0.33 is not used (drops Python 3.10, changes `parse_options_header` output). Covered by `test_dependency_multipart.py`. |
| starlette | 0.49.3 → **1.3.1** | 5 | **Host/path injection into `request.url` was reachable**: `security.identity()` compares `request.url.path` with the safe paths of restricted sessions (forced password change, pending MFA), and a forged Host header unlocked other endpoints (SECURITY-02 moved the gate to the ASGI scope path, see `security.route_path`). Also the urlencoded `max_fields` bypass. `HTTPEndpoint` and Windows `StaticFiles` are not used. | Must be upgraded together with FastAPI. |
| fastapi | 0.121.1 → **0.141.1** | — (needed for Starlette ≥ 1.0) | — | 0.141.1 is the newest FastAPI released while 1.3.1 was the current Starlette. Breaking changes since 0.121 were checked: no `on_event`, no `fastapi.security` classes, Pydantic v2 only. JSON bodies now require `Content-Type: application/json` (0.132), which the frontend always sends. Covered by `test_dependency_starlette.py`. |

**SECURITY-02:** test tools no longer ship in the images. pytest is **9.0.3** in the test-only lock, so PYSEC-2026-1845 is closed. Remaining dev-only finding: **vite 7.2.2 → 7.3.8**, frontend-owned.

### Python dependency files (backend)

| File | Role | Installed by |
|---|---|---|
| `backend/requirements.txt` | runtime **inputs**: direct imports of `backend/app`, exact pins | — (input of the lock) |
| `backend/requirements.lock` | complete runtime set: 49 pins, with `# via` provenance | backend/worker image (`pip install --no-deps` + `pip check`), CI |
| `backend/requirements-test.in` | test inputs (`pytest`) | — (input of the test lock) |
| `backend/requirements-test.lock` | **only** the packages tests add on top of the runtime lock: `pytest`, `pluggy`, `iniconfig`, `pygments` | CI and local test runs, never the image |

- The backend image installs the runtime lock only, and `backend/.dockerignore` keeps `tests/` and the test files out of it.
- The CI `docker` job checks the built image: no `pytest`, `pluggy` or `iniconfig`, no `/app/tests`, `pip check` passes, and `app.main` imports.
- Local test setup:
  ```bash
  python3.12 -m venv .venv
  .venv/bin/pip install --no-deps -r backend/requirements.lock -r backend/requirements-test.lock
  .venv/bin/pip check
  ```

### Generating and checking the locks

- **Generate** with `backend/scripts/compile-requirements.sh`. It uses [uv](https://docs.astral.sh/uv/) and targets the image interpreter: CPython 3.12, `x86_64-manylinux_2_28`.
  - Existing pins in the lock files are kept as preferences, so only packages whose inputs changed move.
  - To upgrade a package on purpose: `UPGRADE="starlette fastapi" backend/scripts/compile-requirements.sh`.
  - The test lock is resolved with the runtime lock as a constraint. The script stops if test resolution would change a runtime pin.
- **Check** with `python backend/scripts/check_requirements.py --resolve`. The CI backend job runs it on every PR.
  - Offline:
    - `requirements.txt` pins equal the lock
    - no test tool is in the runtime lock
    - the runtime and test locks do not overlap
    - test inputs equal the test lock
  - `--resolve`: pip's resolver picks exactly the locked set, both for the runtime lock and for runtime + test.
- The offline part also runs as `backend/tests/test_dependency_locks.py`.
- **Audit:** `dependency-audit.yml` audits `requirements.lock` as runtime, and `requirements-test.lock` and `scripts/browser-requirements.txt` as dev-only.
  - Packages are never reclassified by name. A test tool that slips back into the runtime lock is reported as a runtime finding.

## Test reports and artifacts

- Every pytest job writes JUnit XML. `ci_report.py junit` turns it into the job summary: totals, failures with their first message line, and the 10 slowest tests. The summary costs no artifact storage.
- The raw reports (`reports/`, plus Playwright's `test-results/` if present) are uploaded **only when a job fails** and kept for 7 days.

## Caching, timing and reproducibility

| Item | Before | Now |
|---|---|---|
| Job layout | 1 serial job (~6 min 40 s: suite 5 min 36 s, then 2 Docker builds) + duplicate export run | 6 parallel jobs. Wall time ≈ the slowest job (browser). |
| pip / npm caches | yes | yes, keyed on the lock files |
| Playwright Chromium | downloaded on every run | cached (`~/.cache/ms-playwright`, key = Playwright version); OS packages still installed with `--with-deps` |
| Docker builds | no layer cache | BuildKit with `type=gha` cache per image |
| Runner image | `ubuntu-latest` (floats) | `ubuntu-24.04` |
| Python/Node | 3.12 / 22 | same; they match `backend/Dockerfile` and `frontend/Dockerfile`, with a comment in the workflow |
| Backend dependencies | installed with the resolver | `--no-deps` from the lock + `pip check`: fails if the lock is incomplete or inconsistent |
| Push trigger | `main`, `feat/codex-02-admin` (stale) | `main` only (branches are covered through their PRs) |

**Known reproducibility gaps.** Fixing them requires changes outside CI ownership:
1. `scripts/browser-requirements.txt` pins only `playwright`. Its dependencies (`pyee`, `greenlet`) are resolved freshly on every run. Pinning them is a change for the file's owner.
2. `backend/requirements.lock` has no hashes (`pip-audit` warns about this). Using `pip-compile --generate-hashes` would allow `--require-hashes` installs.
3. Third-party actions are referenced by major tag (`@v4`). Pinning them to commit SHAs, for example with Dependabot for `github-actions`, is recommended as a follow-up.

## ESLint: evaluation and integration plan

- **Current state.** The frontend has no ESLint configuration or dependency. Adding them would touch `frontend/package.json`, `frontend/package-lock.json` and a new `frontend/eslint.config.js`. These are Codex-owned files under active CODEX 09 refactoring, so this branch does not change them.
- **Interim solution.** `.github/linters/` contains an isolated, pinned toolchain: ESLint 9.39.5, typescript-eslint 8.72.2, react-hooks 5.2.0 and TypeScript 5.9.3. It has its own `package-lock.json` and a minimal config: recommended JS + TypeScript rules and the React hooks rules. The advisory `eslint` job lints `frontend/src` with it and writes the rule counts to the job summary. Nothing in `frontend/` is read except the sources.
- **Baseline on `1d613fe`:** 34 findings in total.
  - 24 `react-hooks/exhaustive-deps` warnings
  - 7 `@typescript-eslint/no-unused-vars` errors
  - 3 `no-empty` errors
  - Files: `main.tsx` 13, `ImportWorkspace.tsx` 8, `AccessWorkspace.tsx` 7, `AuthViews.tsx` 4, `ProductData.tsx` 1, `SystemSettings.tsx` 1
- **Integration** (for the frontend owner, after CODEX 09 lands):
  1. Add the five packages above as `devDependencies` in `frontend/package.json`, with the same versions.
  2. Move `.github/linters/eslint.config.mjs` to `frontend/eslint.config.js` and drop the `frontend/` prefix from the globs.
  3. Add `"lint": "eslint src"` to the npm scripts.
  4. Fix or explicitly disable the baseline findings. The hooks warnings need case-by-case review, not blanket fixes.
  5. In `ci.yml`, replace the `eslint` job with `npm run lint` in the `frontend` job, make it blocking, and delete `.github/linters/`.

## Running the CI jobs locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install --no-deps -r backend/requirements.lock -r backend/requirements-test.lock && .venv/bin/pip check
# backend job
PYTHONPATH=backend .venv/bin/pytest -q -ra backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
# browser job (needs Chromium: .venv/bin/python -m playwright install --with-deps chromium)
.venv/bin/pip install -r scripts/browser-requirements.txt
(cd frontend && npm ci && npx vite build)
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py
# frontend job
(cd frontend && npx tsc --noEmit -p tsconfig.json && npx vite build)
# advisory lint
npm ci --prefix .github/linters
.github/linters/node_modules/.bin/eslint -c .github/linters/eslint.config.mjs frontend/src
```

## Proposed update for `docs/development/TESTING.md` (DOCS-01)

This replaces the section "Current GitHub Actions observations" after both PRs are merged. It is not applied here to avoid a conflict with the open DOCS-01 PR.

> ## Continuous integration
> CI (`.github/workflows/ci.yml`, details in `docs/development/CI.md`) runs every test file exactly once, split across parallel jobs:
> - backend and tooling tests
> - browser tests (`*_browser.py`, Playwright/Chromium)
> - the standalone menu-export tool test
> - an explicit `tsc --noEmit` type check and production build
> - both Docker images
>
> ESLint runs as an advisory report until it is integrated into `frontend/package.json`. A separate weekly and on-change workflow (`dependency-audit.yml`) reports Python and npm vulnerabilities, classified as actionable, runtime-nofix or dev-only. It is non-blocking for now. Test reports are summarized in each job and uploaded as artifacts only on failure.
>
> Local equivalent of the backend job: `PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py`.
