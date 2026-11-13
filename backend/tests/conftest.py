import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from contextlib import contextmanager
from app.main import app
from app.models import Base, User, Tenant, Membership, seed_roles
from app.security import database, hash_password
from app import api, reference
from app.db import enforce_reference_readonly


@pytest.fixture(scope="session")
def password_hash():
    return hash_password("Test-password-2026!")


@pytest.fixture
def environment(monkeypatch, password_hash):
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(
        db_engine,
        "connect",
        lambda conn, record: conn.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(db_engine)
    with db_engine.begin() as conn:
        seed_roles(conn)
    with Session(db_engine) as db:
        db.add_all(
            [
                User(
                    id=1,
                    email="root@example.hu",
                    name="Super Admin",
                    password_hash=password_hash,
                    superadmin=True,
                ),
                User(
                    id=2,
                    email="admin@example.hu",
                    name="Ügyfél Admin",
                    password_hash=password_hash,
                ),
                User(
                    id=3,
                    email="processor@example.hu",
                    name="Feldolgozó",
                    password_hash=password_hash,
                ),
                User(
                    id=4,
                    email="reviewer@example.hu",
                    name="Ellenőrző",
                    password_hash=password_hash,
                ),
                User(
                    id=5,
                    email="other@example.hu",
                    name="Másik ügyfél",
                    password_hash=password_hash,
                ),
            ]
        )
        db.add_all(
            [Tenant(id=1, name="Első ügyfél"), Tenant(id=2, name="Második ügyfél")]
        )
        db.flush()
        db.add_all(
            [
                Membership(tenant_id=1, user_id=2, role="tenant_admin"),
                Membership(tenant_id=1, user_id=3, role="processor"),
                Membership(tenant_id=1, user_id=4, role="reviewer"),
                Membership(tenant_id=2, user_id=5, role="tenant_admin"),
            ]
        )
        db.commit()

    def get_database():
        with Session(db_engine) as db:
            yield db

    app.dependency_overrides[database] = get_database
    monkeypatch.setattr(api, "limit_login", lambda *args: None)
    monkeypatch.setenv("APP_ORIGIN", "https://testserver")
    ref_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    reference.metadata.create_all(ref_engine)
    with ref_engine.begin() as conn:
        # External IDs deliberately differ, and a missing external parent collides
        # with a real internal ID. Never resolve this orphan by internal ID.
        conn.execute(
            reference.categories.insert(),
            [
                {
                    "id": 10,
                    "emag_category_id": 1000,
                    "name": "Műszaki cikkek",
                    "parent_id": None,
                },
                {
                    "id": 20,
                    "emag_category_id": 2000,
                    "name": "Laptopok",
                    "parent_id": 1000,
                },
                {
                    "id": 30,
                    "emag_category_id": 3000,
                    "name": "Árva kategória",
                    "parent_id": 10,
                },
                {
                    "id": 40,
                    "emag_category_id": 4000,
                    "name": "Unoka kategória",
                    "parent_id": 2000,
                },
                {
                    "id": 50,
                    "emag_category_id": 5000,
                    "name": "Körkörös A",
                    "parent_id": 6000,
                },
                {
                    "id": 60,
                    "emag_category_id": 6000,
                    "name": "Körkörös B",
                    "parent_id": 5000,
                },
            ],
        )
        conn.execute(
            reference.parameters.insert(),
            [
                {
                    "id": 70,
                    "category_id": 20,
                    "emag_parameter_id": 9000,
                    "name": "Szín",
                    "type_id": 2,
                    "display_order": 1,
                    "is_mandatory": True,
                    "is_filter": True,
                    "allow_new_value": False,
                },
                {
                    "id": 80,
                    "category_id": 10,
                    "emag_parameter_id": 9000,
                    "name": "Más kategória színe",
                    "type_id": 2,
                    "display_order": 1,
                    "is_mandatory": False,
                    "is_filter": False,
                    "allow_new_value": True,
                },
            ],
        )
        conn.execute(
            reference.values.insert(),
            [
                {
                    "id": i + 100,
                    "parameter_id": 70,
                    "value_text": f"Érték {i:03}",
                    "value_order": i,
                }
                for i in range(125)
            ],
        )
        conn.execute(
            reference.values.insert(),
            [
                {
                    "id": 900,
                    "parameter_id": 80,
                    "value_text": "Nem ide tartozik",
                    "value_order": 0,
                }
            ],
        )
    event.listen(ref_engine, "before_cursor_execute", enforce_reference_readonly)
    statements = []
    event.listen(
        ref_engine,
        "before_cursor_execute",
        lambda conn,
        cursor,
        statement,
        parameters,
        context,
        executemany: statements.append(statement),
    )

    @contextmanager
    def readonly():
        with ref_engine.connect() as conn:
            yield conn

    monkeypatch.setattr(reference, "reference_database", readonly)
    with TestClient(app, base_url="https://testserver") as client:
        yield client, db_engine, ref_engine, statements
    app.dependency_overrides.clear()
    db_engine.dispose()
    ref_engine.dispose()


def login(client, email="root@example.hu", password="Test-password-2026!"):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response
