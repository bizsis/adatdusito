# Database map and migration rules

## Databases
- `adatdusito_dev`: application-owned MySQL 8 schema, managed by Alembic.
- `pinfo_db`: source/reference MySQL database, read-only at application level. Core tables include `emag_categories`, `emag_category_parameters`, `emag_parameter_values`. **Never migrate or mutate it.**

## Main application entities (code-verified)
Identity and tenancy in `backend/app/models.py`:
- `users`: global identity, email, name, scrypt hash, active/superadmin flags.
- `tenants`: subscribing customer workspace.
- `memberships`: legacy tenant role membership; retained for compatibility.
- `roles`, `permissions`, `role_permissions`: original permission system and aliases.
- `login_sessions`: hashed session token, selected tenant, expiry.
- `audit_events`: actor/context/action/details/timestamp.
- `system_settings`: present string settings.

CODEX 08 / migration `0007`, `backend/app/access_models.py`:
- `access_roles`, `access_bindings`: scoped configurable roles and multiple grants.
- `system_user_access`: all/selected/none tenant access for system users.
- `user_permission_exceptions`: allow/deny overrides.
- `workspace_resource_access`: full/selected company/webshop access.
- `workspace_companies`, `workspace_webshops`: minimal organizational resources.
- `user_invitations`: invitation state, hashed one-time tokens and delivery metadata.

Supplier/import entities in `backend/app/import_models.py`:
- `Supplier`, `ImportProfile`, `ImportRun`, `ImportChunk`, `ImportRow`,
  `SupplierProduct`, `ImportChange`, `StoreEngine`, `StoreProfile`.
Use class definitions/migration DDL for exact column names and foreign keys rather than assuming this summary is exhaustive.

Versioned reference/catalog classes in `backend/app/models.py`:
- `CatalogVersion`, `CatalogCategory`, `CatalogNode`,
  `CatalogParameter`, `CatalogLink`, `CatalogLinkEntry`,
  `CatalogValue`, `CatalogSourceMapping`.
Additional reference-source and observation entities exist.

## Migration discipline
- Existing baseline: Alembic `0007` after CODEX 08. Reserve the next revision centrally; parallel agents must not both create `0008`.
- New schema only in `adatdusito_dev`; do not modify original `0001`–`0007` history.
- Include forward/backward compatibility for app deployments, preserving tenants, users, sessions, memberships, supplier profiles and product data.
- Run migration on disposable MySQL 8 first. Take and validate a full app DB backup before VPS migration.
- Avoid irreversible destructive downgrade or silent data dropping; test data migration for legacy memberships.
- Keep PII and credentials out of repository fixtures and generated reports.

## Known modeling gap
CODEX 08 introduced company/webshop resources, but older product/import rows lack those explicit relationships. Do **not** invent or auto-infer these associations. The data migration to resource-linked business records is separate future work.
