# Operations runbook — development deployment

**Scope:** development VPS only. Approval and active-state verification required before actions.

## Monitoring and health
- `https://dev.pinfo.hu/api/health/live`: HTTP 200 indicates process liveness, not business health.
- `https://dev.pinfo.hu/api/health/ready`: dependency readiness; returns 503 on failed checks.
- Compose service health: backend (healthcheck), Redis (healthcheck), frontend, worker. Check Celery worker logs and stalled import runs.
- Review disk growth, logs, backup success, failed logins, invitation delivery and MySQL health.

## Backups
- Capture the full **application** database `adatdusito_dev` before migrations and on a scheduled retention plan.
- Test a restore into a **separate** empty schema before relying on a backup.
- Preserve `.env` and deployed configuration securely; never publish them or commit to Git.
- Exclude the reference database `pinfo_db` from application migration and rollback scripts.

## Incident handling
1. Preserve timestamps, commit SHA, migration revision and relevant redacted logs.
2. Determine whether the fault is availability, permissions, ingestion or reference database.
3. Avoid turning off permission checks to restore availability.
4. Consider worker pause to protect in-progress imports before DB recovery.
5. For migrations, follow the exact revision rollback guidance; avoid blind downgrade after new writes.
6. Record action, outcome, affected tenants and follow-up in a private incident record.

## SMTP
CODEX 08 invitation delivery relies on `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`. Current secrets are configured outside Git. CODEX 09 aims to add protected UI configuration and test sending.

## Security notes
At documentation inception the SECURITY-01 branch is separate and not necessarily deployed. Its host-Nginx adjustments need manual, approved activation and configuration test on the VPS.

## Operating ownership
Paksi Informatika operates the platform. Operators handling tenant data require explicit system scopes, audit and privacy discipline.
