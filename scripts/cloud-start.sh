#!/usr/bin/env bash
set -euo pipefail
cd /workspace/adatdusito
python3 scripts/cloud-fixture.py
# This file is only needed for base Compose parsing. Preserve any existing settings.
if [ ! -e .env ]; then (umask 077; cp .env.example .env); fi
export COMPOSE_FILE=compose.yaml:compose.cloud.yaml
docker compose up -d --no-build
for attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:18080/api/health/ready; then
        bash scripts/smoke.sh http://127.0.0.1:18080
        exit 0
    fi
    sleep 2
done
exit 1
