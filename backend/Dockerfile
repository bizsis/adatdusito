# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
# Runtime dependencies only (test tools are in requirements-test.lock and
# never installed here). The lock is complete, so install it exactly.
COPY requirements.lock .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --no-deps -r requirements.lock && pip check
RUN useradd --uid 10001 --create-home app
COPY --chown=app:app . .
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
