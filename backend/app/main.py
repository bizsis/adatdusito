import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from app.db import check_database
from app.worker import celery

app = FastAPI(title="Adatdúsító", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/api/health/live")
def live():
    return {"status": "ok"}

@app.get("/api/health/ready")
def ready():
    checks = {}
    for name, operation in {
        "database": lambda: check_database(),
        "reference": lambda: check_database(True),
        "redis": lambda: Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2).ping(),
        "worker": lambda: bool(celery.control.ping(timeout=2)),
    }.items():
        try:
            result = operation()
            checks[name] = result is not False
        except Exception:
            checks[name] = False
    ok = all(checks.values())
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)
