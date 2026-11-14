"""0007 -> 0008 preserves identities, sessions, CODEX 08 grants and configuration."""

from pathlib import Path
import pytest
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_access_migration import load


def test_0008_preserves_legacy_identity_data_and_reversible_initial_state():
    e = create_engine("sqlite://")
    directory = Path(__file__).resolve().parents[1] / "migrations/versions"
    with e.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for p in sorted(directory.glob("000[1-7]*.py")):
                load(p).upgrade()
            c.execute(
                text(
                    "INSERT INTO users(id,email,name,password_hash,active,superadmin,created_at) VALUES (1,'root@example.hu','Root','unchanged-hash',1,1,CURRENT_TIMESTAMP),(2,'user@example.hu','User','other-hash',1,0,CURRENT_TIMESTAMP)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO tenants(id,name,active,created_at) VALUES (1,'Molnarvegyi',1,CURRENT_TIMESTAMP)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO memberships(tenant_id,user_id,role,active) VALUES (1,2,'processor',1)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO login_sessions(token_hash,user_id,tenant_id,created_at,expires_at) VALUES ('preserved-cookie-hash',2,1,CURRENT_TIMESTAMP,'2099-01-01')"
                )
            )
            c.execute(
                text(
                    "INSERT INTO system_settings(key,value) VALUES ('display_name','Régi név'),('admin_notice','Megőrzendő belső megjegyzés')"
                )
            )
            c.execute(
                text(
                    "INSERT INTO access_bindings(user_id,context,role_id) SELECT 2,'tenant:1',id FROM access_roles WHERE code='processor'"
                )
            )
            tables = set(inspect(c).get_table_names())
            migration = load(next(directory.glob("0008*.py")))
            migration.upgrade()
            assert len(set(inspect(c).get_table_names()) - tables) == 7
            assert c.execute(
                text("SELECT id,username,email,password_hash FROM users ORDER BY id")
            ).all() == [
                (1, "user-1", "root@example.hu", "unchanged-hash"),
                (2, "user-2", "user@example.hu", "other-hash"),
            ]
            assert c.scalar(text("SELECT COUNT(*) FROM memberships")) == 1
            assert c.scalar(text("SELECT COUNT(*) FROM access_bindings")) == 1
            assert (
                c.scalar(text("SELECT token_hash FROM login_sessions"))
                == "preserved-cookie-hash"
            )
            assert c.scalar(text("SELECT onboarding_state FROM tenants")) == "existing"
            assert (
                c.scalar(
                    text("SELECT value FROM system_settings WHERE key='admin_notice'")
                )
                == "Megőrzendő belső megjegyzés"
            )
            migration.downgrade()
            assert c.scalar(text("SELECT COUNT(*) FROM users")) == 2
            assert c.scalar(text("SELECT COUNT(*) FROM access_bindings")) == 1
            migration.upgrade()
            c.execute(
                text(
                    "INSERT INTO audit_events(actor_id,tenant_id,action,target,details,created_at) VALUES (1,NULL,'auth09.totp_enabled','1','{}',CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(
                RuntimeError, match="Authentication configuration changed"
            ):
                migration.downgrade()
            assert "user_totp_devices" in inspect(c).get_table_names()
