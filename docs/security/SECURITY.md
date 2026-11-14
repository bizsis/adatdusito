# Security model and current hardening backlog

## Current controls (CODEX 08)
- scrypt password hashes (`N=131072,r=8,p=1`), constant-time password check comparison.
- SHA-256 hashes of random session tokens in DB; HttpOnly, Secure and SameSite=Strict cookies in HTTPS deployments.
- CSRF token and Origin verification for mutating requests; login throttling via Redis.
- Server-enforced RBAC: system and tenant roles, union of grants, explicit deny precedence, tenant/company/store scopes; audit and superadmin protection.
- One-time hashed invite tokens, expiry, audit and revocation. SMTP is configured using environment variables.
- Read-only eMAG reference connection and tenant scoping for application data.

## SECURITY-01 issues under review (not yet marked fixed)
1. **scrypt memory exhaustion**: ~128 MiB per concurrent calculation; bound concurrency across hash/verify paths without weakening existing hashes. Local semaphore only protects one process; verify actual worker topology.
2. **Account lockout abuse**: existing `login:account:{email}` low threshold blocks legitimate user; redesign combined credential/client throttling and distributed attack mitigation; avoid easy global lockout. Validate real client IP handling through trusted reverse proxies.
3. **Upload limit mismatch**: application 50 MB; frontend Nginx 51m; repository host Nginx 20m. Verify ACTIVE VPS configuration and standardize proxy body allowance; frontend needs clear Hungarian 413 error.
4. **HSTS**: not present in inspected repository HTTPS Nginx config; consider `max-age=31536000` without `preload`/`includeSubDomains` after HTTPS policy review.
5. `/api/v1/system/status` currently accessible to authenticated users; tighten for operational staff.
6. Password change revokes sessions including current session; UI must explain the resulting re-login.

## Planned auth (NOT live at CODEX 08)
Username-based optional-email system accounts, TOTP with recovery codes, passkeys/WebAuthn, Google OIDC, MFA policy administration, SMTP settings UI. Authenticate and authorize on server; preserve existing user identity and membership data.

## Incident and secret-handling rules
- Never commit `.env`, secret tokens, passwords, private keys, real user data or invite URLs.
- Never return or log raw SMTP credentials, TOTP seeds, recovery codes or sensitive failure traces.
- No production deployment without explicit operator approval and rollback plan.
- Security PRs must include regression tests and explain possible existing-session effects.
- Distinguish code review from penetration test; passing unit tests alone does not prove DoS resistance or deployment security.

## Vulnerability reporting
Report privately to the project maintainer. Avoid public GitHub issues containing exploits, secrets or personal data. Define a dedicated security contact/channel before external customer launch.
