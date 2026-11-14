"""Legacy identities, memberships, sessions and reference metadata survive 0007."""

import importlib.util
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_0007_preserves_legacy_assignments_and_superadmin_sessions():
    e = create_engine("sqlite://")
    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(directory.glob("000[1-6]*.py")):
                load(p).upgrade()
            c.execute(
                text(
                    "INSERT INTO users(id,email,name,password_hash,active,superadmin,created_at) VALUES (1,'root@test.hu','Root','preserved-root-hash',1,1,CURRENT_TIMESTAMP),(2,'staff@test.hu','Staff','preserved-staff-hash',1,0,CURRENT_TIMESTAMP)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Molnarvegyi',1,CURRENT_TIMESTAMP),(2,'Nomadsport',1,CURRENT_TIMESTAMP)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO memberships(tenant_id,user_id,role,active) VALUES (1,2,'processor',1),(2,2,'reviewer',1),(1,1,'tenant_admin',1)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO login_sessions(token_hash,user_id,tenant_id,created_at,expires_at) VALUES ('unchanged-session',1,NULL,CURRENT_TIMESTAMP,'2099-01-01')"
                )
            )
            old_tables = set(inspect(c).get_table_names())
            m = load(next(directory.glob("0007*.py")))
            m.upgrade()
            assert len(set(inspect(c).get_table_names()) - old_tables) == 8
            assert c.scalar(text("SELECT COUNT(*) FROM users")) == 2
            assert c.scalar(text("SELECT superadmin FROM users WHERE id=1")) == 1
            assert (
                c.scalar(text("SELECT password_hash FROM users WHERE id=2"))
                == "preserved-staff-hash"
            )
            assert (
                c.scalar(text("SELECT token_hash FROM login_sessions"))
                == "unchanged-session"
            )
            rows = c.execute(
                text(
                    "SELECT b.user_id,b.context,r.code FROM access_bindings b JOIN access_roles r ON r.id=b.role_id ORDER BY b.user_id,b.context"
                )
            ).all()
            assert rows == [
                (1, "tenant:1", "tenant_admin"),
                (2, "tenant:1", "processor"),
                (2, "tenant:2", "reviewer"),
            ]
            assert c.scalar(text("SELECT COUNT(*) FROM memberships")) == 3
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM workspace_resource_access WHERE mode='all' AND roles_managed=1"
                    )
                )
                == 3
            )
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM access_roles WHERE code='superadmin' AND protected=1"
                    )
                )
                == 1
            )
            m.downgrade()
            assert c.scalar(text("SELECT COUNT(*) FROM memberships")) == 3
            assert c.scalar(text("SELECT superadmin FROM users WHERE id=1")) == 1
