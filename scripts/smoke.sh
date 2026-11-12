#!/usr/bin/env bash
set -euo pipefail
base="${1:-http://127.0.0.1:8080}"
curl --fail --silent --show-error "$base/" | grep -q 'Adatdúsító'
curl --fail --silent --show-error "$base/api/health/live"
curl --fail --silent --show-error "$base/api/health/ready"
docker compose exec -T backend python -c 'from app.worker import ping; assert ping.delay().get(timeout=15) == "pong"'
