import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from app.db import check_database
from app.worker import celery
from app.api import router as identity_router
from app.reference import router as reference_router
from app.security import Identity, identity
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

app = FastAPI(
    title="Adatdúsító API",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(identity_router)
app.include_router(reference_router)
from app.reference_sources import router as sources_router

app.include_router(sources_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Same-origin JSON API. CORS is deliberately not enabled.
    origin = request.headers.get("origin")
    expected = os.getenv("APP_ORIGIN", "https://dev.pinfo.hu").rstrip("/")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and origin != expected
    ):
        return JSONResponse(
            {"error": {"code": "forbidden", "message": "Nem engedélyezett eredet."}},
            status_code=403,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request, error):
    return JSONResponse(
        {"error": {"code": str(error.status_code), "message": error.detail}},
        status_code=error.status_code,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Never echo request bodies or passwords in validation responses.
    return JSONResponse(
        {
            "error": {
                "code": "validation",
                "message": "Hibás bemeneti adatok.",
                "fields": [
                    {"location": list(e["loc"]), "type": e["type"]}
                    for e in error.errors()
                ],
            }
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict_error(request, error):
    return JSONResponse(
        {
            "error": {
                "code": "conflict",
                "message": "Az adat már létezik vagy a kapcsolat érvénytelen.",
            }
        },
        status_code=409,
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return JSONResponse(
        {
            "error": {
                "code": "database_unavailable",
                "message": "Az adatbázis átmenetileg nem elérhető.",
            }
        },
        status_code=503,
    )


@app.get("/api/v1/openapi.json", include_in_schema=False)
def openapi_document(who: Identity = Depends(identity)):
    return app.openapi()


@app.get("/api/v1/docs", include_in_schema=False)
def documentation(who: Identity = Depends(identity)):
    from fastapi.openapi.docs import get_swagger_ui_html

    return get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json", title="Adatdúsító API"
    )


@app.get("/api/v1/system/status", tags=["Rendszerállapot"])
def system_status(who: Identity = Depends(identity)):
    import json

    # The status document remains readable when a dependency is degraded.
    return json.loads(ready().body)


@app.get("/api/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready():
    checks = {}
    for name, operation in {
        "database": lambda: check_database(),
        "reference": lambda: check_database(True),
        "redis": lambda: Redis.from_url(
            os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
        ).ping(),
        "worker": lambda: bool(celery.control.ping(timeout=2)),
    }.items():
        try:
            result = operation()
            checks[name] = result is not False
        except Exception:
            checks[name] = False
    ok = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status_code=200 if ok else 503,
    )


# Document cookie authentication and the synchronizer token accepted by mutations.
def documented_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description="Többügyfeles adminisztráció. Belépés után a böngésző HttpOnly cookie-t használ. A /auth/me csrf_token értékét X-CSRF-Token fejlécként küldd minden módosító kéréshez. A referencia-végpontok kizárólag SELECT lekérdezéseket hajtanak végre.",
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "SessionCookie"
    ] = {"type": "apiKey", "in": "cookie", "name": "adatdusito_session"}
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if path.startswith("/api/v1/") and path != "/api/v1/auth/login":
                operation["security"] = [{"SessionCookie": []}]
                for status, message in [
                    ("401", "Bejelentkezés szükséges"),
                    ("403", "Nincs jogosultság / érvénytelen CSRF-token"),
                ]:
                    operation.setdefault("responses", {}).setdefault(
                        status, {"description": message}
                    )
                if method != "get":
                    operation.setdefault("parameters", []).append(
                        {
                            "name": "X-CSRF-Token",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "A /api/v1/auth/me csrf_token értéke.",
                        }
                    )
    app.openapi_schema = schema
    return schema


app.openapi = documented_openapi
