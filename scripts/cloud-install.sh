#!/usr/bin/env bash
set -euo pipefail
cd /workspace/adatdusito
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
(cd frontend && npm --cache /tmp/adatdusito-npm ci && npm run build)
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t adatdusito-dev-backend backend
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t adatdusito-dev-frontend frontend
docker pull mysql:8.0
docker pull redis:7.4-alpine
