# FRONTEND-02: frontend dependencies and blocking lint

This documents the **frontend lint and Vite status** summarized in `CI.md`; Python dependency
maintenance and the other QUALITY-01 jobs remain outside this change. Base:
`26c2a77e21bccbaba4f23d3e219bc3fcc2a33710`. Assignment: GitHub issue #9.

## Dependency decisions

All direct pins are exact and committed in `frontend/package-lock.json`.

| Package | Before | After | Reason |
| --- | --- | --- | --- |
| Vite | 7.2.2 | 7.3.8 | Latest published 7.x at review; compatible with Node 22.12+ and existing static build. |
| ESLint / `@eslint/js` | external 9.39.5 | frontend 9.39.5 | Requested ESLint 9 integration; latest published 9.x. |
| typescript-eslint | external 8.72.2 | frontend 8.72.2 | Supports TypeScript 5.9.3 and ESLint 9. |
| eslint-plugin-react-hooks | external 5.2.0 | frontend 7.1.1 | Current plugin, with blocking hook ordering and dependency rules. |
| minimatch (only typescript-estree's dependency) | 10.2.6 | 11.0.1 override | Fix GHSA-g3hv-75wg-m249 introduced through the lint dependency tree. |

React 19.2.0, TypeScript 5.9.3, WebAuthn 13.1.2 and Lucide 0.468.0 are unchanged.
Vite requires Node `^20.19.0 || >=22.12.0`; both CI and the build image use Node 22.
ESLint marks its 9.x series deprecated in npm. This task explicitly requires
ESLint 9, so upgrading to ESLint 10 is a separate maintenance decision, not an
unreported major upgrade in this PR.

### Advisory validation

The npm registry audit identified **10 Vite advisories** on 7.2.2. The ranges and
fixes were checked against the linked publisher advisories and the
[Vite 7.3.8 changelog](https://github.com/vitejs/vite/blob/v7.3.8/packages/vite/CHANGELOG.md).
7.3.7 is the first release outside every reported affected range; 7.3.8 also fixes
virtual-module ID escaping and is the latest compatible 7.x patch.

| Advisory | Area | Reported affected 7.x versions end at |
| --- | --- | --- |
| [GHSA-4w7w-66w2-5vf9](https://github.com/advisories/GHSA-4w7w-66w2-5vf9) | optimized dependency sourcemap traversal | 7.3.1 |
| [GHSA-v2wj-q39q-566r](https://github.com/advisories/GHSA-v2wj-q39q-566r) | `server.fs.deny` query bypass | 7.3.1 |
| [GHSA-p9ff-h696-f583](https://github.com/advisories/GHSA-p9ff-h696-f583) | dev-server WebSocket file read | 7.3.1 |
| [GHSA-v6wh-96g9-6wx3](https://github.com/advisories/GHSA-v6wh-96g9-6wx3) | Windows editor UNC paths | 7.3.4 |
| [GHSA-698v-4r3x-3vcv](https://github.com/advisories/GHSA-698v-4r3x-3vcv) | Windows editor command escaping | 7.3.6 |
| [GHSA-r825-w8mm-5pxw](https://github.com/advisories/GHSA-r825-w8mm-5pxw) | editor CLI flag interpretation | 7.3.6 |
| [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm) | editor existence-check bypass | 7.3.6 |
| [GHSA-9jrq-w75r-8gcw](https://github.com/advisories/GHSA-9jrq-w75r-8gcw) | cross-origin custom middleware scripts | 7.3.6 |
| [GHSA-rq7h-c2jc-7f22](https://github.com/advisories/GHSA-rq7h-c2jc-7f22) | dev-server allowed-path checks | 7.3.6 |
| [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff) | Windows alternate paths | 7.3.4 |

Adding typescript-eslint initially introduced seven transitive audit findings
caused by [minimatch GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249).
The scoped override replaces only typescript-estree's minimatch. Its actual call
uses the named CommonJS `minimatch(filePath, pattern, {dot: true})` API, retained
by 11.0.1. A parser project-service test exercises `allowDefaultProject`, which
executes this call; Node 22 lint and parser tests also pass. Remove the override
when typescript-eslint declares a patched dependency itself. Do not use
`npm audit fix --force` or downgrade the parser to npm's misleading proposed fix.

After `npm ci`, both `npm audit` and `npm audit --omit=dev` report **zero findings**.
These are point-in-time advisory results, not a guarantee about future reports.
The Vite/editor findings concern development/build tooling. The final production
image contains Nginx and `dist`, with no Node, Vite server, ESLint or npm packages.
Docker/Nginx configuration is unchanged. Do not run or expose the dev server on
the VPS.

## Hook review and baseline fixes

There are no inline lint suppressions or disabled hook rules. The configuration
keeps JS/TypeScript recommended checks and enables `rules-of-hooks` and
`exhaustive-deps` as errors. Warnings also fail the command. The new plugin's React
Compiler diagnostics are not enabled: this project does not use React Compiler,
and adopting its state/immutability conventions would require a separate UI
refactor. Coverage of the previous advisory configuration is preserved and made
blocking, including two new `unknown`-instead-of-`any` corrections in `apiResponse`.

| File | Dependency findings | Review and correction |
| --- | ---: | --- |
| `AccessWorkspace.tsx` | 5 | Memoized loading depends on API, scope and actual read permissions. Initial loading no longer calls the tab-dependent action wrapper, preventing a reload when editing or switching tabs. Search effects include the API and scope; existing debounce cleanup remains. Invitation and resource searches include their API dependency. |
| `AuthViews.tsx` | 3 | Login methods and recovery search follow the API identity. Security-center loading is a callback depending only on the API, so typing usernames/passwords or handling TOTP/passkey results does not reload/reset the form. |
| `ImportWorkspace.tsx` | 7 | Stable action, refresh and selection callbacks. Export permissions are a boolean dependency, not a freshly returned permissions array. Polling captures run ID/state rather than an entire run object. Rows, joins and preview depend on the relevant scalar state and mapping, preventing fetch loops and preserving edited mappings during polling. Cleanup ignores late poll responses after the selected run changes. Export loading follows the API identity. |
| `ProductData.tsx` | 1 | API identity added; existing cancellation guard retained. The surrounding tenant-keyed workspace still remounts at tenant changes. |
| `SystemSettings.tsx` | 1 | Memoized API-dependent loading; editing and save notifications do not trigger a load loop or clear secrets mid-edit. |
| `main.tsx` | 7 | Stable branding/session callbacks. Serialized workspace-list snapshots preserve search during identical periodic session refreshes while including fallback memberships. Search capability and tenant ID are explicit dependencies. Signed-in state controls one session-refresh timer, with cleanup on expiry. The generation guard and CSRF transitions are retained. |

The seven original unused-variable findings were removed (including an unused
legacy role selector and its newly redundant type). Three empty catch blocks now
explain why the original error/local logout must be preserved when a follow-up
request fails. They do not discard a newly introduced error condition.

## CI and regression coverage

The existing required `frontend` job now runs:

```bash
npm ci --no-audit --no-fund
npm run lint
npm run test:lint
npx tsc --noEmit -p tsconfig.json --pretty false
npx vite build
```

The redundant advisory `eslint` job and `.github/linters/` lock/config are removed.
`ci-ok` already requires `frontend`, so lint failures now block the aggregate
status without changing its job dependencies or any backend CI step. Existing
dependency-audit jobs continue to audit the frontend lock normally.

New tests:

- `frontend/tests/lint.test.mjs`: hook ordering, missing dependencies, unused
  variables and empty blocks must be errors; a complete callback example passes;
  the real parser project service works with the minimatch override.
- `scripts/tests/test_frontend_hooks_browser.py`: periodic refresh preserves
  workspace search; tenant switching resets search and rotates CSRF; expiry
  clears CSRF and stops the timer; late session responses cannot undo logout;
  import polling retains edited mappings with bounded fetch counts and ignores old run responses; HTML 413 on
  a real multipart upload preserves supplier/form state and sends the CSRF token.
- Existing desktop/mobile API-backed tests cover passkey/TOTP/recovery, system
  settings, access forms, tenant flows, import/approval/export and navigation.
  UI-FIX-01's HTML/JSON/204/error regressions remain part of the browser job.

### Initial FRONTEND-02 local validation

| Command/check | Result |
| --- | --- |
| `PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py` | 305 passed |
| `PYTHONPATH=backend .venv/bin/pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py scripts/tests/test_emag_menu_export.py` | 44 passed, including desktop/mobile auth, import, navigation and standalone export-tool tests |
| `npm ci`, `npm run lint`, `npm run test:lint`, `npm run build` | Successful; 3 lint configuration tests passed; zero lint warnings/errors |
| Node 22.23.5 container: `npm run lint && npm run test:lint` | Successful |
| `npm audit`, `npm audit --omit=dev` | Zero findings in each |
| Both Docker builds | Successful, using the existing `proxy_ca` BuildKit secret for this cloud's certificate trust |
| Final frontend image smoke check | Static `index.html` exists; neither Node nor npm is installed |
| CI workflow integrity check | YAML parses; backend/browser/menu-export/docker/ci-ok job definitions are unchanged; frontend lint is required |
| Late import poll regression against pre-guard bundle | Fails because the old response restores the prior selection; passes with the guard |

The Python suites report two existing Starlette/httpx/AnyIO deprecation warnings.
The cloud proxy rejects GitHub API connections with HTTP 403, so hosted job links
and an Actions success cannot be claimed from these local results. The PR must
trigger and pass the hosted workflow before merge.

No backend source, Python lock, database, migration, `.env` or VPS is changed.

## SECURITY-02 integration into FRONTEND-02

Integrated `main` at `df31f6c8e127b76c11fdb551e52f333d38113922` (SECURITY-02,
PR #10) into `codex/frontend-02` for PR #11. The original frontend implementation
at `2c9bd2fc21d729aaa101802cf4db1f765e8d3478` is preserved.

- `ci.yml` merged automatically. Parsed YAML comparisons confirm that the
  backend, browser, menu-export, Docker and aggregate jobs match SECURITY-02;
  the frontend job matches FRONTEND-02, including blocking lint and its tests.
- The two conflicting passages in `CI.md` now describe the test-only Python
  lock and runtime-only image checks alongside the patched Vite and required lint.
- Backend security, all Python locks and tooling, the dependency audit workflow,
  `AGENTS.md` and the SECURITY-02 test/reporting changes match the integrated
  `main` byte for byte. No additional security or backend edits were made.
- The 49 runtime and 4 test-only pins pass `pip check` and resolver agreement.
  The backend image has no pytest/pluggy/iniconfig, tests or test lock;
  `pip check` succeeds and `app.main` imports. Both Docker builds succeed.
- Audits of the runtime lock, test lock, browser dependencies and npm runtime/all
  dependencies find **zero vulnerabilities**. The combined report has zero
  actionable, runtime-nofix and dev-only findings.

Integration validation: **364 backend/tooling + 30 browser + 14 isolated export
+ 3 lint-configuration tests passed**. `npm ci`, blocking lint, TypeScript and
Vite production build pass. Both Docker builds and SECURITY-02 runtime-image
checks pass. The existing two Python deprecation warnings remain. The audit
commands use the merged dependency-audit workflow's three Python inputs and two
npm reports; the aggregate report is clean.

## Deployment and rollback

No migration or data import is needed. After owner-approved merge, use the
existing frontend image rebuild/recreation procedure. The production Nginx image
and forwarded-header behavior are unchanged. Rollback is the prior frontend
image or reverting this PR; there are no database rollback steps.
