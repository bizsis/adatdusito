# Continuous integration

Status: **Implemented** in QUALITY-01 (`claude/quality-01`). This page describes the GitHub Actions configuration in `.github/workflows/`. The general testing guide is `docs/development/TESTING.md`, which is maintained by the DOCS-01 branch. The section proposed for it is at the end of this page.

## Workflows

### `ci.yml`: runs on pull requests, pushes to `main` and manual dispatch

| Job | What it checks | Blocking |
|---|---|---|
| `backend` | `backend/tests` + `scripts/tests`, except browser tests and the menu-export test. Dependencies are installed from `backend/requirements.lock` with `--no-deps`, then checked with `pip check`. | yes |
| `browser` | `backend/tests/*_browser.py` + `scripts/tests/*_browser.py` (Playwright and Chromium) against a fresh `vite build` of the frontend | yes |
| `menu-export` | `scripts/tests/test_emag_menu_export.py`, installed with **only** `scripts/browser-requirements.txt`, the way the Windows export tool is used | yes |
| `frontend` | `npx tsc --noEmit -p tsconfig.json` (explicit type check), then `npx vite build` | yes |
| `docker` | builds both images with BuildKit and the GitHub Actions layer cache, without pushing | yes |
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

**Baseline on `main` @ `1d613fe` (2026-11-14)**. Both remediations change files owned by others and need the Vezér's assignment:

| Class | Package | Current | Fixed in | Note |
|---|---|---|---|---|
| actionable | PyJWT | 2.10.1 | 2.15.0 | 16 advisories. Used by the OIDC login (`backend/app/oidc_api.py`). Highest priority. |
| actionable | python-multipart | 0.0.20 | 0.0.31 | 6 advisories. Parses every upload (supplier import). |
| actionable | starlette | 0.49.3 | 1.3.1 | 5 advisories. **Major upgrade**: needs a compatible FastAPI release, so plan it together with `fastapi`. |
| runtime-nofix | PyJWT | 2.10.1 | — | PYSEC-2025-183 (CVE-2025-45768), disputed upstream |
| dev-only | pytest | 9.0.1 | 9.0.3 | test runner; also installed in the backend image through the shared lock |
| dev-only | vite | 7.2.2 | 7.3.8 | 10 dev-server advisories. Production serves the static build through Nginx, so this affects developer machines running `npm run dev`. |

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
.venv/bin/pip install --no-deps -r backend/requirements.lock && .venv/bin/pip check
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
