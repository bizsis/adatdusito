# Adatdúsító — Product and project charter

**Status:** living requirements baseline. **Checked against:** CODEX 08 code on `main` at documentation inception; future branches require revalidation. **Owner:** Paksi Informatika.

## Purpose
A multi-tenant Hungarian SaaS to convert inconsistent supplier CSV/XLSX product feeds into structured, reviewable, reusable product information and eventually UNAS-compatible exports. Typical journey: supplier feed → reliable identification and matching → controlled taxonomy/parameter mapping → optional AI-assisted research → human approval → export/synchronization.

## Implemented baseline (CODEX 07–09 + SECURITY-01, merged to Git)
- FastAPI, SQLAlchemy/Alembic, MySQL 8, React/TypeScript/Vite, Celery/Redis, Docker Compose.
- Cookie sessions, scrypt password hashes with cross-process concurrency cap, CSRF/Origin checks, progressive account/IP throttling, admin audit.
- Tenants, system/tenant roles, multi-role grants, explicit allow/deny, scoped system users, workspace switching, companies/webshops as minimal permission resources; invitation and SMTP sending when configured.
- Fixed approved Hungarian category tree with 13 first-level groups; eMAG database is read-only reference. Application-owned versioned catalog is separate.
- Supplier CSV/XLSX import, saved profiles, field mapping, preview, approval, runs, product/change records and export-field/profile administration.
- CODEX 09 Cloud & Teal UI, structured and encrypted SMTP settings, email/username sign-in, Google OIDC, WebAuthn/passkeys, TOTP and recovery codes, session management and restricted onboarding registration (default off). Migration `0008` required for deployment.

These capabilities are derived from `backend/app/{main,api,security,access_control,import_api,models}.py`, CODEX 07/08 notes. Deploy confirmation and individual external integrations still require runtime verification.

## Planned — not production functionality
- AI research/enrichment (multiple models and providers), validation, Hungarian product content, images, hybrid approval.
- Product identity/deduplication, robust automated supplier sync, complete UNAS export/API synchronizer.
- Complete self-service trial/entitlement lifecycle, subscription packages, credit billing, payment and invoice provider integrations. Basic restricted-workspace registration is merged but disabled by default.
- External identity-provider setup and production activation of CODEX 09 sign-in methods (code merged, not yet deployed to VPS).

## Business invariants
1. Strong tenant isolation, also for import files, worker jobs, exports and caches.
2. Customer-specific prices, availability and internal data never leak into shared product knowledge.
3. Preserve original supplier columns and traceability; avoid guessing financial-field semantics.
4. Human/manual UNAS changes must not be overwritten without explicit merge policy.
5. eMAG parameters remain the single reference parameter system; customer-facing fixed category structure is not extended automatically by synchronization.
6. Normal imports and inventory/price updates do **not** consume separate processing units; subscription limits cover technical load and product storage.
7. AI usage is accounted separately as credits, including real provider charges on failed calls when applicable.

## Audience
Paksi Informatika operators, subscriber administrators, product processors, reviewers and read-only users. Default UI language: Hungarian.

## Source-of-truth order
For *what works*: executable code, migrations, test results and deployment confirmation. For *intended behavior*: this charter, ADRs and approved feature specification. Historical CODEX notes show how changes were made, not current design by themselves.

## Boundaries
This document is not a promise of released features. Track delivery in [ROADMAP](ROADMAP.md); see the module specifications for future behavior.
