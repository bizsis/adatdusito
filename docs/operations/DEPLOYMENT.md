# Development VPS deployment — operational reference

**Target:** `dev.pinfo.hu`; checkout `/opt/adatdusito`; MySQL schema `adatdusito_dev`. This document is guidance, not evidence of a fresh deployment.

## Infrastructure
- Host Nginx terminates HTTPS, fronts frontend Nginx on `127.0.0.1:8080`.
- Compose project `adatdusito-dev`; services `redis`, `migrate`, `backend`, `worker`, `frontend`.
- External network `adatdusito-dev-net`; host MySQL outside Compose.
- `.env` excluded from Git; `APP_DATABASE_URL` must target app database; `REFERENCE_DATABASE_URL` must access `pinfo_db` read-only.
- Check `APP_ORIGIN=https://dev.pinfo.hu`, `COOKIE_SECURE=true`, CODEX 09's encryption-key requirements, and SMTP/OIDC provider configuration before enabling those methods. See `docs/codex-09-ui-system-settings-auth.md` for complete setup and recovery.

## Deployment protocol
1. Verify clean tracked working tree, current revision, import jobs completed and disk capacity.
2. Preserve current commit, `.env` and Compose configuration with restricted filesystem permissions; preserve currently running Docker images.
3. Fetch reviewed `main` commit via fast-forward only; build new images.
4. Stop application frontend/backend/worker; create and **validate** consistent compressed backup of **only** `adatdusito_dev`.
5. Run the assigned Alembic revision with application migration container.
6. Recreate/restart relevant services and verify health, app revision and logs.
7. Test browser login, permissions and sample import; record resulting commit and schema version.

## Rollback
Read the specific version migration notes FIRST. For CODEX 08, `docs/codex-08-access-control.md` documents a guarded `0007 → 0006` rollback; once new access records are used, do not blindly downgrade. A full recovery must first preserve current state and validate restore into an isolated schema. Rolling back application binaries alone may be unsafe when permission semantics changed.

## Operations and monitoring
- Liveness: `/api/health/live`.
- Readiness: `/api/health/ready` checks DB/reference/Redis/worker.
- Ensure host-side Nginx config actually deployed matches repository templates.
- Review authentication failures, worker issues, backup integrity, database growth and disk pressure.
- Do not publish `docker compose config` output or backup locations with secrets.

## Required CODEX 09 + SECURITY-01 rollout checks
- **New Alembic `0008_settings_auth`** must be applied only after verified app database backup and a confirmed rollback plan. Preserve the matching encryption key independently; loss of key can make stored SMTP/OIDC/TOTP secrets unrecoverable.
- Git template sets host body limit 51m, HSTS max-age 31536000 and secure real-IP forwarding; inspect real host `nginx -T`, certificate renewal, ingress and Docker proxy network CIDRs before applying.
- Run `nginx -t` before reloading host Nginx. Confirm frontend Nginx forwards the trusted client address without overwriting it.
- Verify email/username password login, MFA and recovery, Google/passkey only when explicitly configured, and import workflow after backend/worker rebuild.
- Do **not** deploy based on this summary alone. Follow `docs/codex-09-ui-system-settings-auth.md` and SECURITY-01 PR instructions for exact commands and rollback.
- Frontend user-facing handling of non-JSON Nginx 413 remains an open task.
