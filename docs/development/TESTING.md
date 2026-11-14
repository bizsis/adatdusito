# Development and CI testing

## Local baseline
Python 3.12, Node.js 22.12+, Docker Compose 2.24.4+ (see root README for environment setup).

From the repository root with dependencies installed:
```bash
PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests
(cd frontend && npm ci && npm run build)
```
Use isolated MySQL fixtures and `scripts/cloud-install.sh` / `scripts/cloud-start.sh` only in disposable cloud/local test environments. **Never run cloud fixtures on VPS.**

## Current GitHub Actions (QUALITY-01 merged)
- `.github/workflows/ci.yml` runs independent backend, Chromium browser, eMAG export, frontend TypeScript check/build, Docker image build, advisory ESLint and aggregate `CI result` jobs.
- All applicable test files are allocated once; new test files are picked up automatically. GitHub Actions preserves job summaries and failure artifacts (7 days).
- `.github/workflows/dependency-audit.yml` runs advisory Python/npm vulnerability audits; findings require separate triage.
- Last reviewed SECURITY-01 integration CI on `205a074`: 265 backend, 16 browser, 14 menu-export tests according to the developer, seven GitHub Actions jobs successful.
- For CI ownership/commands see [CI.md](CI.md) from QUALITY-01.

## Minimum pull request checks
- Existing backend tests and any affected browser tests.
- Build React frontend and both backend/frontend Docker images if modified.
- For permissions: test direct API access across tenants and scopes, revoked permissions in active sessions, deny precedence and system staff boundary.
- For schema changes: forward migration, idempotent upgrade, and safe rollback on disposable MySQL 8.
- For ingestion: CSV/XLSX headers/mappings, exact join keys, financial ambiguity, chunked processing, size and decompression limits.
- For auth: throttling, CSRF/Origin, secrets, password/session regression, TOTP, recovery, Google OIDC and passkey flows.
- For UI: keyboard navigation, mobile viewport, user-facing Hungarian strings and 413 error parsing.

## Test-count caution
Reported totals (e.g. 175 backend vs 201 broader tests) are not comparable without listing commands and git SHA. Always report exact invocation, SHA, pass/fail/skip counts.

## Release acceptance
PR reviewed and CI green; deployment backup and migration plan approved; smoke test actual dev URL; test cross-tenant access and one sample import; document known limitations.
