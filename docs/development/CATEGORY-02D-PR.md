## Purpose

Refs #21. This is a temporary integration/test branch combining backend PR #18 (`8c5db11`) and frontend PR #19 (`0625e4b`) at merge `74f4c64`. **Do not merge this integration PR into main or deploy it.** The original PR branches remain unchanged. Frontend fixes and new tests are isolated in `048b39a` after the combined base.

## Changes and findings

- Add runtime validation for consumed product/detail/internal-category/map/write DTOs. Malformed responses show a recoverable Hungarian error, never an empty-success view, React crash or unverified save confirmation.
- Follow the actual nullable `method`, `rule_version` and map `reason` fields. Show “Még nincs” for a missing classification rule version.
- Allow explicit reload/retry after read/write failure, including a malformed response to an already committed write. Never blindly repeat the write.
- Report map deletion/rejection accurately and distinguish category assignment from donor/enrichment approval.
- Add 25 real-API browser scenarios: q/name/SKU/EAN, status/counts/cursor, all 457 categories/13 roots, multiple donors, map paging/save/delete/reject/409, preview/cancel, real 401/403/404/409/422, readonly/tenant switching, an actual 50,003-row stored stock with 25-row pages, malformed response/503 transport injection, quick search changes and delayed responses.

Normal requests use the production frontend and real FastAPI/TestClient API with isolated SQLite/session/CSRF/RBAC. Fault injection is explicitly labelled; it is not presented as proof of backend business behavior. No existing reference data, hierarchy, application backend, migration, dependencies, .env, Compose or CI rules were changed beyond importing the two pinned PRs.

## Validation

- Complete backend/tooling suite: 389 passed.
- Full browser job: **81 passed, 0 skipped**, including the 25 new real-API/fault/recovery scenarios and both previous real integration cases.
- Export job: 14 passed. ESLint, 3 lint-configuration tests and TypeScript/Vite build passed, including Node 22 lint/configuration validation and the Docker build.
- Runtime/test dependency resolver agrees (49 runtime + 4 test-only pins); npm audit: 0 vulnerabilities.
- Backend/frontend Docker builds and backend runtime pip check/application import passed.

## Backend coordination / limits

Claude should clarify nullable method/rule_version/map reason and the settings GET heading in the contract documentation; GET reads the existing `/system/settings` group, not a separate classification GET. Donor DTOs contain IDs/names, not future enrichment approval or donor-quality status; the UI makes no such assertion. Backend/migration implementation is unchanged from #18. MySQL load and deployed VPS/Nginx/HTTPS were not tested.

See docs/development/CATEGORY-02D-INTEGRATION.md for endpoint/DTO comparison, reproduction, fault boundaries and the detailed discrepancy list. No main merge or VPS deployment. Rollback: drop this integration branch; original PRs remain untouched.

GitHub API PR creation failed with HTTP 403 (`POST api.github.com/graphql: Forbidden`). The branch is pushed; the supplied description can be pasted into a draft PR. The reported validation is local CI-equivalent, not a hosted GitHub Actions success.
