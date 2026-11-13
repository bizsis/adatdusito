"""Tenants, identities, roles, server sessions and administration audit."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Explicit frozen migration; never imports reference metadata or evolving models.
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("superadmin", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "roles",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
    )
    op.create_table("permissions", sa.Column("code", sa.String(64), primary_key=True))
    op.create_table(
        "role_permissions",
        sa.Column("role", sa.String(32), sa.ForeignKey("roles.code"), primary_key=True),
        sa.Column(
            "permission",
            sa.String(64),
            sa.ForeignKey("permissions.code"),
            primary_key=True,
        ),
    )
    op.create_table(
        "memberships",
        sa.Column(
            "tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), primary_key=True
        ),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(32), sa.ForeignKey("roles.code"), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
    )
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(120), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    roles = {
        "superadmin": "Superadmin",
        "tenant_admin": "Ügyféladminisztrátor",
        "processor": "Adatfeldolgozó",
        "reviewer": "Ellenőrző",
    }
    permissions = {
        "superadmin": [
            "system.manage",
            "tenants.manage",
            "users.manage",
            "reference.read",
            "audit.read",
        ],
        "tenant_admin": [
            "tenant.manage",
            "members.manage",
            "reference.read",
            "audit.read",
        ],
        "processor": ["reference.read"],
        "reviewer": ["reference.read"],
    }
    op.bulk_insert(
        sa.table("roles", sa.column("code"), sa.column("label")),
        [{"code": code, "label": label} for code, label in roles.items()],
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("code")),
        [{"code": p} for p in sorted({p for ps in permissions.values() for p in ps})],
    )
    op.bulk_insert(
        sa.table("role_permissions", sa.column("role"), sa.column("permission")),
        [{"role": r, "permission": p} for r, ps in permissions.items() for p in ps],
    )


def downgrade():
    for table in [
        "system_settings",
        "audit_events",
        "login_sessions",
        "memberships",
        "role_permissions",
        "permissions",
        "roles",
        "tenants",
        "users",
    ]:
        op.drop_table(table)
