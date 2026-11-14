# UNAS integration — target contract and current boundary

**Status:** supplier import engine and configurable export fields/profiles exist. Complete UNAS API writeback / live synchronizer is **planned** and must not be presented as shipping.

## Target behavior
- Map normalized and approved product data to UNAS import format and, when authorized, API write operations.
- Per-tenant store configuration, product/variant identifiers, import/export profile, supplier source attribution.
- Dry-run/preview with validation (required fields, price semantics, variants, categories, image URLs) and error report.
- Prefer idempotent, differential updates; detect changes to manually maintained UNAS fields and avoid overwriting protected values.
- Store-level permission checks before export/API calls; securely store credentials outside code.
- Explicit audit of outbound changes, success/failure, retry, reconciliation and rollback limitations.
- Tenant and company/store separation across all queues and files.

## Needed verification before implementation
Current UNAS API documentation, supported export columns, variant/discount semantics, pagination, rates and API auth. Never infer current UNAS capabilities from the existence of an `exports.profile` route.

## Related
- [Supplier import](IMPORT-ENGINE.md).
- [Current RBAC architecture](../architecture/ARCHITECTURE.md).
