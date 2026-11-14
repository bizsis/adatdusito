# ADR-001: Tenant separation and action-based RBAC

- **Status:** Accepted; implemented with CODEX 08, subject to limitations below.
- **Context:** Service operator must work across customers while each customer's users remain isolated.
- **Decision:** Distinguish system roles from tenant roles. Superadmin may access active customers without tenant membership. Other system accounts use all/selected/none customer scope. Multiple roles union permissions; explicit deny wins; scope further restricts access. Tenant-specific company/store grants may be full (including future) or selected resources.
- **Why:** Avoid fake customer memberships for operator staff and privilege bleed across tenants; support multi-company users.
- **Consequences:** Check every request in backend, clear tenant caches when switching, audit changes and cross-tenant operations.
- **Known limitation:** Legacy products/imports without company/store links require full tenant resource access; later migration must add explicit links, never infer.
- **Evidence:** `backend/app/access_control.py`, `backend/app/access_models.py`, `docs/codex-08-access-control.md`.
