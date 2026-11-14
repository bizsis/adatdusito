# Adatdúsító — Documentation index

This is the **living documentation** entrypoint. CODEX release notes remain in their existing locations until link-safe reorganization is agreed and reviewed.

## Start here
- [Product charter](project/PROJECT.md) — business goal, implemented vs planned.
- [Delivery roadmap](project/ROADMAP.md) — release status, assigned workstreams, pending decisions.
- [System architecture](architecture/ARCHITECTURE.md) — runtime topology and trust boundaries.
- [Database](architecture/DATABASE.md) — application and read-only reference schemas.
- [API overview](architecture/API.md) — endpoint families; use runtime OpenAPI for exact contracts.
- [Security](security/SECURITY.md) — existing controls and SECURITY-01 backlog.
- [Testing](development/TESTING.md) — test commands, CI coverage and gaps.
- [Deployment](operations/DEPLOYMENT.md) and [operations](operations/OPERATIONS.md).

## Functional modules
- [Supplier import](modules/IMPORT-ENGINE.md) — existing, CODEX 07.
- [AI engine](modules/AI-ENGINE.md) — design only.
- [UNAS integration](modules/UNAS-INTEGRATION.md) — export config exists; full API sync planned.
- [Subscription, billing and AI credits](modules/BILLING.md) — approved business design, not implemented.
- [UI design](development/UI-DESIGN.md) — CODEX 09 design target, not yet shipped.
- [User guide](user/USER-GUIDE.md) — currently available operational paths, subject to UI changes.

## Decisions
- [ADR-001 — Tenant isolation and RBAC](decisions/ADR-001-tenant-and-access-boundaries.md)
- [ADR-002 — Curated taxonomy and eMAG parameter source](decisions/ADR-002-reference-taxonomy.md)
- [ADR-003 — Plans, AI credits and no processed-row quota](decisions/ADR-003-billing-and-processing.md)

## Historical implementation reports
- [CODEX 07 import engine](codex-07-import-engine.md)
- [CODEX 08 access control](codex-08-access-control.md)

**Documentation rules:** mark capability status explicitly as Implemented / Deployed / In progress / Planned; no placeholders that imply working features. Validate changes against source code. Document releases and architecture changes in PRs. Never publish secrets or real customer records.
