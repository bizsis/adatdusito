# Delivery roadmap

**Status date:** 2026-11-14. This file lists planned work; it is **not** evidence that a feature shipped.

| Area | Status | Source / dependency |
|---|---|---|
| CODEX 07 supplier import and export-field admin | Implemented in repository; deployed to dev per operator | `docs/codex-07-import-engine.md` |
| CODEX 08 scoped RBAC, workspace picker, invitations | Implemented; dev migration `0007` and health check confirmed by operator | `docs/codex-08-access-control.md` |
| SECURITY-01 hardening: scrypt slots, login throttling, body limits, HSTS | Assigned to Claude, **not yet merged at this baseline** | Separate PR, security review |
| CODEX 09/A Cloud & Teal UI modernization | Assigned to Codex, **in progress** | Component refactor and consistent help text |
| CODEX 09 authentication/settings: SMTP UI, username, TOTP, passkeys, Google | Planned; must integrate with security hardening | Separate implementation/review gates |
| Product identity and dedup | Planned | Import normalization |
| Category assignment / parameter mapping | Planned enhancement | eMAG read-only catalog |
| AI research, multi-provider credits and human QC | Planned | Product pipeline, billing design |
| UNAS export/API sync and protection of manual changes | Planned | Verified UNAS formats/API |
| Automated supplier feeds and change detection | Planned | Supplier profiles and job scheduling |
| Subscription, payments, invoicing and self-service trial | Planned | Provider decisions and legal/tax review |

## Delivery gates
- No direct push to `main`: feature branches, PR, code review, green CI.
- App/database schema changes must have an assigned Alembic revision; concurrent agents may not independently claim the same number.
- Backup/rollback and migration validation before VPS deploy; app DB only. `pinfo_db` is read-only.
- A feature becomes **Implemented** only on merged commit with successful tests, and **Deployed** only after VPS validation.
- Avoid refactoring import core during unrelated UI/security work.

## Open product decisions
Initial payment provider and invoicing provider; supported payment methods and currencies/taxes; counting product variants across feeds; duration of one-off capacity add-ons; cancellation/credit edge cases; refund/chargeback policy; price-change notice; data retention and erasure policy.

## Collaboration
ChatGPT coordinates requirements and integration; Claude and Codex own disjoint branches/tasks; each PR documents affected behavior and limitations. See root `AGENTS.md` when committed by the security/documentation workstream.
