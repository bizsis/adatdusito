#!/usr/bin/env bash
set -euo pipefail
cd /workspace/adatdusito
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock -r scripts/browser-requirements.txt
(cd frontend && npm --cache /tmp/adatdusito-npm ci && npm run build)
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
python3 scripts/cloud-fixture.py
if [ ! -e .env ]; then (umask 077; cp .env.example .env); fi
docker compose -f compose.yaml -f compose.cloud.yaml build
docker pull mysql:8.0
docker pull redis:7.4-alpine
