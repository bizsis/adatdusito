# Development VPS deployment — operational reference

**Target:** `dev.pinfo.hu`; checkout `/opt/adatdusito`; MySQL schema `adatdusito_dev`. This document is guidance, not evidence of a fresh deployment.

## Infrastructure
- Host Nginx terminates HTTPS, fronts frontend Nginx on `127.0.0.1:8080`.
- Compose project `adatdusito-dev`; services `redis`, `migrate`, `backend`, `worker`, `frontend`.
- External network `adatdusito-dev-net`; host MySQL outside Compose.
- `.env` excluded from Git; `APP_DATABASE_URL` must target app database; `REFERENCE_DATABASE_URL` must access `pinfo_db` read-only.
- Check `APP_ORIGIN=https://dev.pinfo.hu`, `COOKIE_SECURE=true` and SMTP transport if sending invitations.

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

## Known issue
Repository host Nginx body limit is 20m while internal proxy is 51m and app is 50 MB at CODEX 08 baseline. SECURITY-01 work is planned to align these; do not assume the checked-in host config reflects the live VPS.
