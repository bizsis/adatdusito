# Security model and current hardening backlog

## Current controls (CODEX 09 + SECURITY-01 merged in Git; VPS rollout pending)
- scrypt password hashes (`N=131072,r=8,p=1`), constant-time password check comparison.
- SHA-256 hashes of random session tokens in DB; HttpOnly, Secure and SameSite=Strict cookies in HTTPS deployments.
- CSRF token and Origin verification for mutating requests; login throttling via Redis.
- Server-enforced RBAC: system and tenant roles, union of grants, explicit deny precedence, tenant/company/store scopes; audit and superadmin protection.
- One-time hashed invite tokens, expiry, audit and revocation. CODEX 09 supports encrypted SMTP and Google OIDC secrets through system settings with legacy environment-variable fallback; operational encryption key deployment is required.
- Read-only eMAG reference connection and tenant scoping for application data.

## SECURITY-01 status
Merged in PR #1 (`c5502c38`): scrypt lock-file slots shared across Uvicorn processes in one container (default 2), bounded queue with 503/Retry-After; progressive account/IP login throttling that avoids global hard account lockout; trusted reverse-proxy IP handling and MFA failure counters; repository host Nginx 51m limit and HSTS `max-age=31536000` without subdomain/preload scope. The Nginx template is **not proof that the live host has been updated**.

## Residual security and UX follow-ups
1. Frontend still needs a clear Hungarian response to HTML HTTP 413 from Nginx.
2. Audit whether `/api/v1/system/status` should be accessible only to operational staff.
3. Review dependency advisories (PyJWT, python-multipart, FastAPI/Starlette compatibility) with reproducible lockfile updates.
4. Verify lock directory, trusted proxy CIDRs, TLS/HSTS prerequisites and real-IP behavior on actual VPS before deployment.
5. A strong distributed botnet can attempt one guess per fresh IP during severe account targeting; require/configure MFA where risk warrants it.

## CODEX 09 authentication implementation
Merged code supports username-based system accounts with optional email, TOTP/recovery codes, multiple WebAuthn passkeys, Google OIDC, MFA policies, SMTP settings UI and session management. These require configuration, secure encryption key handling, migration `0008` and rollout validation; do not describe as already deployed.

## Incident and secret-handling rules
- Never commit `.env`, secret tokens, passwords, private keys, real user data or invite URLs.
- Never return or log raw SMTP credentials, TOTP seeds, recovery codes or sensitive failure traces.
- No production deployment without explicit operator approval and rollback plan.
- Security PRs must include regression tests and explain possible existing-session effects.
- Distinguish code review from penetration test; passing unit tests alone does not prove DoS resistance or deployment security.

## Vulnerability reporting
Report privately to the project maintainer. Avoid public GitHub issues containing exploits, secrets or personal data. Define a dedicated security contact/channel before external customer launch.
