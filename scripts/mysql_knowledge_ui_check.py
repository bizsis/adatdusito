"""Integrated 0013->0014->0015 + reference/knowledge APIs on EMPTY loopback MySQL.

Requires an explicit fixture acknowledgement. Never use on a VPS, shared DB or
pinfo_db. Synthetic records only. Does not drop a database or print credentials.
"""

import os
import sys
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from sqlalchemy import create_engine, make_url, inspect, text, select, func, delete
    from sqlalchemy.orm import Session

    if os.getenv("KNOWLEDGE_UI_FIXTURE_ACK") != "isolated-knowledge-ui-01":
        raise SystemExit(
            "Refusing: explicit isolated knowledge-ui fixture acknowledgement required."
        )
    url = make_url(os.environ["APP_DATABASE_URL"])
    if (
        url.get_backend_name() != "mysql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "adatdusito_dev"
    ):
        raise SystemExit(
            "Refusing: expected an empty loopback MySQL adatdusito_dev fixture."
        )
    db_engine = create_engine(url, pool_pre_ping=True)
    with db_engine.connect() as conn:
        if inspect(conn).get_table_names():
            raise SystemExit("Refusing: fixture schema must be empty.")
        assert conn.scalar(text("SELECT VERSION()")).startswith("8.0.")
    os.environ["REFERENCE_DATABASE_URL"] = (
        "mysql+pymysql://blocked:blocked@127.0.0.1:1/pinfo_db"
    )
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/migrations"))
    command.upgrade(cfg, "0013")
    from app.models import User, now
    from app.unas_models import (
        ReferenceProductSource,
        ReferenceProduct,
        ReferenceImportRun,
        ReferenceImportChunk,
    )
    from app.security import hash_password, database

    password = "Knowledge-synthetic-fixture-only!"
    with Session(db_engine) as db:
        db.add(
            User(
                id=1,
                email="root@example.invalid",
                name="Synthetic Root",
                password_hash=hash_password(password),
                superadmin=True,
            )
        )
        db.add(
            ReferenceProductSource(
                id=1,
                key="legacy-fixture",
                name="Legacy",
                kind="unas_export",
                usage_status="restricted",
                usage_basis="none",
                enrichment_enabled=False,
                contribution="automatic",
                excluded_columns=[],
            )
        )
        db.commit()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reference_import_runs(id,source_id,file_name,file_sha256,state,counters,errors,started_at) VALUES(1,1,'legacy.csv',:h,'completed',:counters,'[]',CURRENT_TIMESTAMP)"
            ),
            {"h": "a" * 64, "counters": '{"created":7}'},
        )
    command.upgrade(cfg, "0014")
    command.upgrade(cfg, "0015")
    with db_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
        assert (
            conn.scalar(text("SELECT ui_cursor FROM reference_import_runs WHERE id=1"))
            == 0
        )
        assert (
            conn.scalar(
                text(
                    "SELECT JSON_EXTRACT(counters,'$.created') FROM reference_import_runs WHERE id=1"
                )
            )
            == "7"
        )
    print("OK 0013 -> 0014 -> 0015; legacy run preserved", flush=True)
    from app.main import app
    from app import api, security, knowledge as kb, knowledge_uploads as jobs
    from app.knowledge_models import KnowledgeLink, KnowledgeValue, KnowledgeObservation
    from fastapi.testclient import TestClient

    def database_fixture():
        with Session(db_engine) as db:
            yield db

    class Guard:
        def check(self):
            pass

        def failure(self):
            pass

        def success(self):
            pass

    original = dict(app.dependency_overrides)
    app.dependency_overrides[database] = database_fixture
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(api, "limit_login", lambda *a, **k: None))
            stack.enter_context(
                patch.object(api, "login_guard", lambda *a, **k: Guard())
            )
            stack.enter_context(
                patch.object(security, "limit_failures", lambda *a, **k: None)
            )
            stack.enter_context(
                patch.object(kb.process_rebuild, "apply_async", lambda *a, **k: None)
            )
            stack.enter_context(patch.object(jobs, "enqueue", lambda id: None))
            client = stack.enter_context(TestClient(app, base_url="https://testserver"))
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "root@example.invalid", "password": password},
            )
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            prefix = "/api/v1/knowledge-admin"
            data = "SKU;NAME;EAN;Gyártó;Email;Nettó Ár\n0001;Mosógép;5201137061819;Acme;private@example.invalid;100\n0002;Porszívó;5904517345546;Acme;secret@example.invalid;200\n".encode()
            response = client.post(
                prefix + "/uploads",
                data={
                    "source_name": "Synthetic knowledge source",
                    "scope": "system",
                    "reuse_authorized": "true",
                },
                files={"file": ("source.csv", data)},
            )
            assert response.status_code == 200, response.status_code
            run_id, source_id = response.json()["id"], response.json()["source_id"]
            with Session(db_engine) as db:
                jobs.process(db, run_id)
            run = client.get(prefix + f"/imports/{run_id}").json()
            assert run["state"] == "preview"
            assert "private@example.invalid" not in str(run)
            assert (
                client.post(
                    prefix + f"/imports/{run_id}/start",
                    json={"mapping": run["mapping"]},
                ).status_code
                == 200
            )
            with Session(db_engine) as db:
                jobs.process(db, run_id)
                assert db.get(ReferenceImportRun, run_id).state == "completed"
                assert (
                    db.scalar(select(func.count()).select_from(ReferenceProduct)) == 2
                )
                assert (
                    db.scalar(
                        select(ReferenceProduct.source_sku).order_by(
                            ReferenceProduct.id
                        )
                    )
                    == "0001"
                )
                kb.rebuild(db, source_id=source_id)
                assert db.scalar(select(func.count()).select_from(KnowledgeLink)) == 2
            print(
                "OK web upload -> reference import -> knowledge rebuild; privacy and identifiers preserved",
                flush=True,
            )
            repeat = client.post(prefix + f"/imports/{run_id}/repeat")
            assert repeat.status_code == 200
            with Session(db_engine) as db:
                jobs.process(db, repeat.json()["id"])
                assert (
                    db.get(ReferenceImportRun, repeat.json()["id"]).counters[
                        "unchanged"
                    ]
                    == 2
                )
            print("OK repeat import is duplicate-free", flush=True)
            try:
                command.downgrade(cfg, "0014")
            except RuntimeError as exc:
                assert "Stored reference uploads" in str(exc)
            else:
                raise AssertionError("Stored uploads must prevent a downgrade")
            with Session(db_engine) as db:
                db.execute(delete(ReferenceImportChunk))
                db.commit()
                value = db.scalar(select(KnowledgeValue))
                value.verified_by = 1
                db.commit()
            command.downgrade(cfg, "0014")
            command.upgrade(cfg, "0015")
            try:
                command.downgrade(cfg, "0013")
            except RuntimeError as exc:
                assert "Protected decisions" in str(exc)
            else:
                raise AssertionError(
                    "Knowledge decisions must prevent a cross-revision downgrade"
                )
            with db_engine.connect() as conn:
                assert (
                    conn.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0015"
                )
                assert "reference_import_chunks" in inspect(conn).get_table_names()
                assert conn.scalar(text("SELECT COUNT(*) FROM reference_products")) == 2
            print(
                "OK 0015 -> 0014 -> 0015 and decision guard before any DDL", flush=True
            )
            with Session(db_engine) as db:
                db.scalar(
                    select(KnowledgeValue).where(KnowledgeValue.verified_by == 1)
                ).verified_by = None
                db.commit()
            command.downgrade(cfg, "0013")
            command.upgrade(cfg, "head")
            with db_engine.connect() as conn:
                assert (
                    conn.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0015"
                )
                assert conn.scalar(text("SELECT COUNT(*) FROM reference_products")) == 2
            print(
                "OK 0015 -> 0013 -> 0015; reference rows preserved; reference DB never contacted",
                flush=True,
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
        db_engine.dispose()


if __name__ == "__main__":
    main()
