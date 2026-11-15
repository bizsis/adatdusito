# Continuous integration

Status: **Implemented** in QUALITY-01 (`claude/quality-01`). This page describes the GitHub Actions configuration in `.github/workflows/`. The general testing guide is `docs/development/TESTING.md`, which is maintained by the DOCS-01 branch. The section proposed for it is at the end of this page.

Frontend dependency and lint decisions are documented in [FRONTEND-02](FRONTEND-02.md).

## Workflows

### `ci.yml`: runs on pull requests, pushes to `main` and manual dispatch

| Job | What it checks | Blocking |
|---|---|---|
| `backend` | `backend/tests` + `scripts/tests`, except browser tests and the menu-export test. Dependencies are installed from `backend/requirements.lock` with `--no-deps`, then checked with `pip check`. | yes |
| `browser` | `backend/tests/*_browser.py` + `scripts/tests/*_browser.py` (Playwright and Chromium) against a fresh `vite build` of the frontend | yes |
| `menu-export` | `scripts/tests/test_emag_menu_export.py`, installed with **only** `scripts/browser-requirements.txt`, the way the Windows export tool is used | yes |
| `frontend` | `npm run lint` (zero warnings), `npm run test:lint`, explicit TypeScript checking, then `vite build` | yes |
| `docker` | builds both images with BuildKit and the GitHub Actions layer cache, without pushing | yes |
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
| `backend/requirements.lock` (pinned, audited as-is) | `pip-audit --no-deps` |
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
| starlette | 0.49.3 → **1.3.1** | 5 | **Host/path injection into `request.url` was reachable**: `security.identity()` compares `request.url.path` with the safe paths of restricted sessions (forced password change, pending MFA), and a forged Host header unlocked other endpoints. Also the urlencoded `max_fields` bypass. `HTTPEndpoint` and Windows `StaticFiles` are not used. | Must be upgraded together with FastAPI. |
| fastapi | 0.121.1 → **0.141.1** | — (needed for Starlette ≥ 1.0) | — | 0.141.1 is the newest FastAPI released while 1.3.1 was the current Starlette. Breaking changes since 0.121 were checked: no `on_event`, no `fastapi.security` classes, Pydantic v2 only. JSON bodies now require `Content-Type: application/json` (0.132), which the frontend always sends. Covered by `test_dependency_starlette.py`. |

Still open (dev-only): **pytest 9.0.1** (PYSEC-2026-1845: a `/tmp/pytest-of-<user>` local issue, fixed in 9.0.3). It is a test runner, but it ships in the backend image through the shared lock. Moving test-only packages out of the runtime lock is the cleaner follow-up. **Vite 7.3.8** and the frontend-owned blocking lint integration are covered by FRONTEND-02; the final npm audit reports zero findings.

### Lock maintenance procedure (reproducible)

`backend/requirements.lock` is the complete runtime set: 53 pinned distributions installed with `--no-deps`. To change it:
1. Edit only the pins that must change, never "upgrade everything".
2. Check that the lock is complete and that the resolver would choose exactly these versions under Python 3.12 (the Docker/CI interpreter):
   ```bash
   python3.12 -m venv /tmp/lockcheck && /tmp/lockcheck/bin/pip install -U pip
   /tmp/lockcheck/bin/pip install --dry-run --ignore-installed --report /tmp/report.json -r backend/requirements.lock
   # every package in report["install"] must be in the lock with the same version, and vice versa
   /tmp/lockcheck/bin/pip install --no-deps -r backend/requirements.lock && /tmp/lockcheck/bin/pip check
   ```
3. Run the audit: `pip-audit -r backend/requirements.lock --no-deps --disable-pip`.
4. Run the full CI.

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

## ESLint: blocking frontend integration

FRONTEND-02 moves the toolchain into `frontend/package.json`, with exact locked
versions and `frontend/eslint.config.js`. Run `npm run lint` and `npm run test:lint`
from `frontend/`. Both commands run in the required `frontend` job; lint errors
and warnings fail the job and therefore `ci-ok`.

The original 34 baseline findings (24 hooks dependency warnings, 7 unused
variables and 3 empty blocks) are resolved. UI-FIX-01's two explicit `any` types
were also replaced with `unknown`. No blanket hook suppressions are used. The
file-by-file hook review, advisory links, dependency pins, Node 22 compatibility
and scoped minimatch override test are in [FRONTEND-02](FRONTEND-02.md).

The redundant advisory `eslint` job and `.github/linters/` files are removed.
React Compiler diagnostics are a separate adoption decision; hook ordering and
exhaustive dependency checks are blocking with the current maintained plugin.

## Running the CI jobs locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install --no-deps -r backend/requirements.lock && .venv/bin/pip check
# backend job
PYTHONPATH=backend .venv/bin/pytest -q -ra backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
# browser job (needs Chromium: .venv/bin/python -m playwright install --with-deps chromium)
.venv/bin/pip install -r scripts/browser-requirements.txt
(cd frontend && npm ci && npx vite build)
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py
# frontend job (includes blocking lint)
(cd frontend && npm ci && npm run lint && npm run test:lint && npm run build)
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
> ESLint and its configuration tests run in the required frontend job; errors and warnings block CI. A separate weekly and on-change workflow (`dependency-audit.yml`) reports Python and npm vulnerabilities, classified as actionable, runtime-nofix or dev-only. It is non-blocking for now. Test reports are summarized in each job and uploaded as artifacts only on failure.
>
> Local equivalent of the backend job: `PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py`.
