# Adatdúsító — administrator quick guide (CODEX 08)

**Status:** quick reference for currently implemented areas. UI layout may change under CODEX 09; screenshots and exact button labels require reconfirmation after merge.

## Sign-in and workspace
Sign in using an existing account's email/password. A system superadmin can search and select any active tenant workspace without becoming its member. A normal customer user sees only tenants with active memberships. Switching workspace must refresh data and permissions.

## System access
System administrators with appropriate permissions can manage system roles, tenant scopes and users. Customer admins can manage their own members, roles and invitations only within delegated permissions. Several roles can apply; individual denies override allows. Company/shop-specific access must be explicit where supported.

## Invitations
User invitations use a single-use link with configurable expiry, sent via SMTP. SMTP must be configured on the server for delivery. Existing account owners approve additional tenancy using their own identity. Avoid sharing invite links.

## Supplier import
1. Select tenant workspace and supplier.
2. Upload CSV or XLSX.
3. Review detected columns, preserving raw columns.
4. Confirm financial meaning and exact join key; do not guess missing VAT, currency or price type.
5. Approve the import; monitor progress and errors.
6. Review processed product records and tracked changes.

## Limitations
- No web-based SMTP settings or 2FA management yet at CODEX 08.
- No AI enrichment or direct UNAS sync in this shipped baseline.
- Older tenant-only product/import records are not automatically mapped to specific company/shop resources; full tenant resource access may be needed.

## Help and operations
For feature behavior check context-sensitive help when introduced by CODEX 09; for incidents contact the Paksi Informatika operator and include redacted error text, time and active workspace.
