# Delivery roadmap

**Status date:** 2026-11-14. Distinguish merged code from actual VPS deployment.

| Area | Status | Source / dependency |
|---|---|---|
| CODEX 07 supplier import and export-field admin | Implemented in repository; deployed to dev per operator | `docs/codex-07-import-engine.md` |
| CODEX 08 scoped RBAC, workspace picker, invitations | Implemented; dev migration `0007` and health check confirmed by operator | `docs/codex-08-access-control.md` |
| SECURITY-01: scrypt slots, progressive throttling, trusted proxy IP, host Nginx HSTS/body limit | **Merged to main** (`c5502c38`); VPS deployment pending | PR #1 |
| CODEX 09 Cloud & Teal UI | **Merged to main** (`1d613fe`); VPS deployment pending | `docs/codex-09-ui-system-settings-auth.md` |
| CODEX 09 auth/settings: SMTP UI, username, TOTP, passkeys, Google OIDC | **Merged to main**; migration `0008`; VPS deployment pending | `docs/codex-09-ui-system-settings-auth.md` |
| Product identity and dedup | Planned | Import normalization |
| Category assignment / parameter mapping | Planned enhancement | eMAG read-only catalog |
| AI research, multi-provider credits and human QC | Planned | Product pipeline, billing design |
| UNAS export/API sync and protection of manual changes | Planned | Verified UNAS formats/API |
| Automated supplier feeds and change detection | Planned | Supplier profiles and job scheduling |
| Public signup with restricted onboarding workspace | **Merged to main**, disabled by default; VPS deployment pending | CODEX 09 |
| Subscription plans, payments, invoicing and full trial/credit lifecycle | Planned | Provider decisions and legal/tax review |
| QUALITY-01 expanded test/CI and dependency audit | **Merged to main** (`eb275c62`) | `docs/development/CI.md` |
| Dependency upgrades and frontend 413 handling | Open follow-up | Separate reviewed PRs |

## Delivery gates
- No direct push to `main`: feature branches, PR, code review, green CI.
- App/database schema changes must have an assigned Alembic revision; concurrent agents may not independently claim the same number.
- Backup/rollback and migration validation before VPS deploy; app DB only. `pinfo_db` is read-only.
- A feature becomes **Implemented** only on merged commit with successful tests, and **Deployed** only after VPS validation.
- Avoid refactoring import core during unrelated UI/security work.

## Open product decisions
Initial payment provider and invoicing provider; supported payment methods and currencies/taxes; counting product variants across feeds; duration of one-off capacity add-ons; cancellation/credit edge cases; refund/chargeback policy; price-change notice; data retention and erasure policy.

## Collaboration
ChatGPT coordinates requirements and integration; Claude and Codex own disjoint branches/tasks; each PR documents affected behavior and limitations. See root `AGENTS.md` for required branch, file-ownership and deployment approval rules.
