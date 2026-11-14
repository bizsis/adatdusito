# Database map and migration rules

## Databases
- `adatdusito_dev`: application-owned MySQL 8 schema, managed by Alembic.
- `pinfo_db`: source/reference MySQL database, read-only at application level. Core tables include `emag_categories`, `emag_category_parameters`, `emag_parameter_values`. **Never migrate or mutate it.**

## Main application entities (code-verified)
Identity and tenancy in `backend/app/models.py`:
- `users`: global identity, unique username, optional email, name, scrypt hash, active/superadmin flags, email verification, forced password change and MFA-reset flags.
- `tenants`: subscribing customer workspace.
- `memberships`: legacy tenant role membership; retained for compatibility.
- `roles`, `permissions`, `role_permissions`: original permission system and aliases.
- `login_sessions`: hashed session token, selected tenant, expiry, authentication method, MFA-verified and reauthentication timestamps.
- `audit_events`: actor/context/action/details/timestamp.
- `system_settings`: legacy compatibility settings; CODEX 09 adds structured and encrypted settings tables.

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

CODEX 09 / migration `0008_settings_auth`:
- `system_configuration`: validated categorized non-secret configuration.
- `system_secret_settings`: encrypted SMTP/OIDC secrets.
- `auth_challenges`: short-lived one-use hashed challenges.
- `external_identities`: explicit provider identity bindings.
- `user_passkeys`: public credential metadata and counters (not private keys).
- `user_totp_devices`: encrypted TOTP secrets and anti-replay counters.
- `user_recovery_codes`: hashes of one-use recovery codes.
- `tenants.onboarding_state`: legacy tenants remain `existing`.

## Migration discipline
- Current code baseline: Alembic `0008_settings_auth` after CODEX 09; next revision `0009` must be centrally assigned. **VPS migration status is not confirmed; do not equate merged code with deployed schema.**
- New schema only in `adatdusito_dev`; do not modify original `0001`–`0008` migration history.
- Include forward/backward compatibility for app deployments, preserving tenants, users, sessions, memberships, supplier profiles and product data.
- Run migration on disposable MySQL 8 first. Take and validate a full app DB backup before VPS migration.
- Avoid irreversible destructive downgrade or silent data dropping; test data migration for legacy memberships.
- Keep PII and credentials out of repository fixtures and generated reports.

## Known modeling gap
CODEX 08 introduced company/webshop resources, but older product/import rows lack those explicit relationships. Do **not** invent or auto-infer these associations. The data migration to resource-linked business records is separate future work.
