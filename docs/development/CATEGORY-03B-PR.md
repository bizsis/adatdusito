## Result and scope

Refs #24. This is the **first, presentation-only CATEGORY-03B round**, stacked on CATEGORY-02D PR #22 (`a780c65`). It preserves that PR's real-API integration fixes. It does not claim a working CATEGORY-03A API integration.

Adds a responsive Hungarian parameter comparison workspace to the existing ProductData/Classification detail via optional services, plus an optional job slot in ImportWorkspace. Shows raw/normalized values, units/conversion provenance, separate own/donor requirements, all preserved conflicting sources, missing slots, ambiguous aliases, donor review status, correction/lock/history, preview/approval, opaque bulk selection, partial jobs and preparation approval. Pending-review donors cannot offer automatic preparation, local estimates cannot apply as server dry runs, and source-overwriting previews are blocked. Confirmed mappings need no redundant row approval. No frontend matching/unit-conversion/batching algorithm, AI/credit/payment/image feature, backend change or migration.

The production adapter supplies none of the new optional services yet, so no mock data or unimplemented controls appear in the real workflow. Synthetic test transport is excluded from production builds/images. Presentation callback types are not wire DTO proposals.

## Contract dependency and open integration gaps

During this work Claude published the final route/field contract at `claude/category-03a-parameters` / `e330ee7` (`docs/design/CATEGORY-03A-API.md`). That commit is documentation only; its parameter endpoints and 0010 implementation are not present. The UI also supports the documented review/source_only/detached slot states.

The status document lists the exact remaining data needs and mismatches: complete slot-list paging, bounded histories/errors, source/candidate multiplicity, stable allowed-value IDs for constrained PATCH, alias scope, manual-edit preview, real snapshot/token guarantees for bulk, job progress/resume semantics and a separate preparation approval. `prepared` is not user approval; processed/limit is not a reliable completion percentage. No unsupported operation is bound to a guessed endpoint.

## Validation

- 389 backend/tooling tests passed, 14 export tests passed.
- Complete browser regression run: 109 passed. The final parameter UI suite: 32 passed separately (28 overlap the full run; 4 additional regressions). These 32 are presentation mocks, not real 03A backend proof.
- Existing #22 real FastAPI/SQLite cases remain regression coverage; they are not presented as parameter-API integration.
- ESLint, TypeScript/Vite and 3 lint-configuration tests passed; Node 22 lint/configuration and Docker frontend build passed.
- Backend/frontend Docker builds and backend pip check/application import passed. npm audit including dev dependencies: 0 vulnerabilities.
- Desktop/mobile mock screenshots at 1440/390 px; no horizontal viewport overflow.

## Release / rollback

Draft pending implemented 03A endpoints and actual integration/hosted CI. The base is `codex/category-02d-integration`, not main; retarget only after the owner merges the dependency. No main merge or VPS deployment. No .env, Compose, reference database, dependency lock or category hierarchy changes. Rollback removes this optional frontend feature; existing workflows remain available.

See docs/development/CATEGORY-03B-STATUS.md for the exact frontend/backend boundary, published-contract gaps and the implementation/data checklist.

PR creation via GitHub GraphQL failed with HTTP 403 in this cloud environment. The branch is pushed; no hosted GitHub Actions success is claimed. Use this description for a draft PR with base `codex/category-02d-integration` and head `codex/category-03b-frontend`.
