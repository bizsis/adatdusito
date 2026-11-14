# Adatdúsító — administrator quick guide (CODEX 09 merged code)

**Status:** CODEX 09 UI/auth implementation is merged in Git; VPS rollout and real-provider settings remain pending. Confirm actual labels and behavior on deployment.

## Sign-in and workspace
Sign in using an existing account's email or username and password; optional Google OIDC/passkey flows require administrator enablement and provider setup. A system superadmin can search and select any active tenant workspace without becoming its member. A normal customer user sees only tenants with active memberships. Switching workspace must refresh data and permissions.

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

## Personal security and system settings
Users can manage personal account security, TOTP/recovery codes, passkeys and sessions subject to configuration. Administrators have General, SMTP, Authentication, 2FA and Security settings tabs. Google and SMTP require external configuration; registration is disabled by default. Audit remains an independent navigation item.

## Limitations
- New UI and authentication are merged but not yet deployed to the VPS.
- No AI enrichment or direct UNAS sync in this baseline.
- Older tenant-only product/import records are not automatically mapped to specific company/shop resources; full tenant resource access may be needed.

## Help and operations
For feature behavior consult CODEX 09's Hungarian contextual help; for incidents contact the Paksi Informatika operator and include redacted error text, time and active workspace.
