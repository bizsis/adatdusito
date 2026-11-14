# Current architecture (CODEX 08 baseline)

## Runtime topology
```text
Browser (React + TypeScript / Vite build)
  │ HTTPS, same-origin cookies + CSRF
  ▼
Host Nginx (dev.pinfo.hu) → frontend Nginx (127.0.0.1:8080)
                                  │ /api/v1/*
                                  ▼
                           FastAPI backend
                          ┌────┴─────────┐
                          ▼              ▼
                   Application MySQL   Read-only eMAG MySQL
                   adatdusito_dev      pinfo_db
                          │
                          ▼
                       Celery worker ↔ Redis (broker / runtime)
```
The Docker Compose services are `redis`, `migrate`, `backend`, `worker`, `frontend`, on external `adatdusito-dev-net`. Host MySQL and host Nginx are **not** managed by this Compose project.

## Backend modules
- `app/main.py`: FastAPI entrypoint, routers, security headers, error handling, health checks.
- `app/api.py`: login/session, tenants, users and legacy-compatible identity/admin API.
- `app/security.py`: session cookie / CSRF, scrypt, dependency checks.
- `app/access_control.py`, `access_api.py`, `access_models.py`, `invitations.py`: CODEX 08 RBAC, scoped workspace access, invitation lifecycle.
- `app/reference.py`, `reference_sources.py`, `category_tree.py`: reference taxonomy and values.
- `app/catalog_import.py`, `models.py`: versioned application-owned taxonomy.
- `app/import_api.py`, `import_models.py`: supplier imports, mappings, approval, product/change history and export profiles.
- `app/worker.py`: Celery application; supplier task modules are registered for worker execution.
- `app/db.py`: application DB and read-only reference DB connections.

## Trust boundaries
1. The browser does not enforce authorization: every mutating/read API must check server-side effective permissions and tenant/scope.
2. Tenant context is session-specific; system staff have explicit tenant access scopes. Superadmin doesn't require tenant membership.
3. Organization/webshop permissions are implemented as access resources; **legacy products/imports without resource mapping require whole-tenant access** (CODEX 08 known limitation).
4. `pinfo_db` must remain read-only and excluded from application schema migrations.
5. E-mail invitation and sensitive configuration are privileged operations; never log secrets or raw invite tokens.
6. File uploads, worker results and exports must be tenant-scoped; source originals must be traceable.

## Key limitations
Current auth is email/password only. SMTP invitations depend on configured environment variables. AI research, auto-feed schedules, full UNAS API integration and subscription billing are future work.

## Architecture change process
Record breaking or cross-cutting decisions in `docs/decisions/` (ADRs); update this document when code lands. Historical CODEX reports are supporting evidence, not an architecture source of truth.
