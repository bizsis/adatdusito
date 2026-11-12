#!/usr/bin/env bash
set -euo pipefail
cd /workspace/adatdusito
python3 scripts/cloud-fixture.py
# This file is only needed for base Compose parsing. Preserve any existing settings.
if [ ! -e .env ]; then (umask 077; cp .env.example .env); fi
docker compose -f compose.yaml -f compose.cloud.yaml up -d --no-build
for attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8080/api/health/ready; then
        bash scripts/smoke.sh
        exit 0
    fi
    sleep 2
done
exit 1
