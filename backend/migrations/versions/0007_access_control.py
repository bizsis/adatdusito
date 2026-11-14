"""Additive multi-role access control; preserves users, memberships and sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
TABLES = [
    "access_roles",
    "access_bindings",
    "system_user_access",
    "user_permission_exceptions",
    "workspace_resource_access",
    "workspace_companies",
    "workspace_webshops",
    "user_invitations",
]
CATALOG = [
    "audit.read",
    "companies.manage",
    "companies.read",
    "exports.fields.manage",
    "exports.profile",
    "exports.read",
    "imports.approve",
    "imports.cancel",
    "imports.create",
    "imports.manage",
    "imports.read",
    "members.invite",
    "members.manage",
    "members.read",
    "members.roles.manage",
    "products.read",
    "reference.manage",
    "reference.read",
    "system.audit.read",
    "system.roles.manage",
    "system.roles.read",
    "system.settings.manage",
    "system.settings.read",
    "system.users.manage",
    "system.users.read",
    "tenants.access.manage",
    "tenants.create",
    "tenants.edit",
    "tenants.read",
    "tenants.suspend",
    "webshops.manage",
    "webshops.read",
]
DEFAULTS = {
    "system_admin": [
        "audit.read",
        "companies.manage",
        "companies.read",
        "exports.profile",
        "exports.read",
        "imports.approve",
        "imports.cancel",
        "imports.create",
        "imports.manage",
        "imports.read",
        "members.invite",
        "members.manage",
        "members.read",
        "members.roles.manage",
        "products.read",
        "reference.read",
        "system.roles.read",
        "system.settings.read",
        "system.users.read",
        "tenant.manage",
        "tenants.create",
        "tenants.edit",
        "tenants.read",
        "webshops.manage",
        "webshops.read",
    ],
    "system_operator": [
        "exports.read",
        "imports.approve",
        "imports.cancel",
        "imports.create",
        "imports.manage",
        "imports.read",
        "products.read",
        "reference.read",
        "tenants.read",
    ],
    "system_auditor": [
        "audit.read",
        "exports.read",
        "imports.read",
        "products.read",
        "reference.read",
        "system.audit.read",
        "system.roles.read",
        "system.settings.read",
        "system.users.read",
        "tenants.read",
    ],
    "viewer": [
        "companies.read",
        "exports.read",
        "imports.read",
        "products.read",
        "reference.read",
        "webshops.read",
    ],
}


def upgrade():
    bind = op.get_bind()
    if not any(
        i["name"] == "ix_tenant_workspace_names"
        for i in sa.inspect(bind).get_indexes("tenants")
    ):
        op.create_index(
            "ix_tenant_workspace_names", "tenants", ["active", "name", "id"]
        )
    op.create_table(
        "access_roles",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("owner", sa.String(length=48), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("legacy_code", sa.String(length=32), nullable=True),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("protected", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("owner", "code"),
    )
    op.create_index("ix_access_roles_owner", "access_roles", ["owner"])
    op.create_table(
        "access_bindings",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("context", sa.String(length=48), nullable=False, primary_key=True),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("access_roles.id"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_table(
        "system_user_access",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("tenants", sa.JSON(), nullable=False),
    )
    op.create_table(
        "user_permission_exceptions",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("context", sa.String(length=48), nullable=False, primary_key=True),
        sa.Column("permission", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "workspace_resource_access",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("companies", sa.JSON(), nullable=False),
        sa.Column("shops", sa.JSON(), nullable=False),
        sa.Column("roles_managed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "workspace_companies",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_workspace_companies_tenant_id", "workspace_companies", ["tenant_id"]
    )
    op.create_table(
        "workspace_webshops",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("workspace_companies.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_workspace_webshops_company_id", "workspace_webshops", ["company_id"]
    )
    op.create_index(
        "ix_workspace_webshops_tenant_id", "workspace_webshops", ["tenant_id"]
    )
    op.create_table(
        "user_invitations",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True
        ),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
        sa.Column("access", sa.JSON(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("delivery", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "accepted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_user_invitations_tenant_id", "user_invitations", ["tenant_id"])
    op.create_index("ix_user_invitations_email", "user_invitations", ["email"])
    permissions = sa.table("permissions", sa.column("code"))
    for code in CATALOG:
        if not bind.scalar(
            sa.select(permissions.c.code).where(permissions.c.code == code)
        ):
            bind.execute(permissions.insert().values(code=code))
    roles = sa.table(
        "access_roles",
        sa.column("id", sa.Integer),
        sa.column("owner"),
        sa.column("code"),
        sa.column("name"),
        sa.column("permissions", sa.JSON),
        sa.column("legacy_code"),
        sa.column("managed", sa.Boolean),
        sa.column("protected", sa.Boolean),
    )
    created_viewer = not bind.scalar(
        sa.text("SELECT code FROM roles WHERE code='viewer'")
    )
    if created_viewer:
        bind.execute(
            sa.text("INSERT INTO roles (code,label) VALUES ('viewer','Megtekintő')")
        )
        for code in DEFAULTS["viewer"]:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role,permission) VALUES ('viewer',:code)"
                ),
                {"code": code},
            )
    legacy = bind.execute(sa.text("SELECT code,label FROM roles")).mappings().all()
    for r in legacy:
        if created_viewer and r["code"] == "viewer":
            continue
        bind.execute(
            roles.insert().values(
                owner="system" if r["code"] == "superadmin" else "template",
                code=r["code"],
                name=r["label"],
                permissions=[],
                legacy_code=r["code"],
                managed=False,
                protected=r["code"] == "superadmin",
            )
        )
    for code, perms in DEFAULTS.items():
        if bind.scalar(
            sa.select(roles.c.id).where(
                roles.c.code == code,
                roles.c.owner == "template"
                if code == "viewer"
                else roles.c.owner == "system",
            )
        ):
            continue
        bind.execute(
            roles.insert().values(
                owner="template" if code == "viewer" else "system",
                code=code,
                name={
                    "viewer": "Megtekintő",
                    "system_admin": "Rendszeradminisztrátor",
                    "system_operator": "Rendszeroperátor",
                    "system_auditor": "Rendszerellenőr",
                }[code],
                permissions=perms,
                legacy_code=None,
                managed=True,
                protected=False,
            )
        )
    role_ids = {
        r["code"]: r["id"]
        for r in bind.execute(sa.select(roles)).mappings()
        if r["owner"] == "template"
    }
    bindings = sa.table(
        "access_bindings",
        sa.column("user_id"),
        sa.column("context"),
        sa.column("role_id"),
    )
    scopes = sa.table(
        "workspace_resource_access",
        sa.column("user_id"),
        sa.column("tenant_id"),
        sa.column("mode"),
        sa.column("companies", sa.JSON),
        sa.column("shops", sa.JSON),
        sa.column("roles_managed", sa.Boolean),
    )
    for m in bind.execute(
        sa.text("SELECT user_id,tenant_id,role FROM memberships")
    ).mappings():
        if m["role"] not in role_ids:
            raise ValueError("Unknown legacy membership role")
        bind.execute(
            bindings.insert().values(
                user_id=m["user_id"],
                context="tenant:" + str(m["tenant_id"]),
                role_id=role_ids[m["role"]],
            )
        )
        bind.execute(
            scopes.insert().values(
                user_id=m["user_id"],
                tenant_id=m["tenant_id"],
                mode="all",
                companies=[],
                shops=[],
                roles_managed=True,
            )
        )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'access.%'")
    ):
        raise RuntimeError(
            "Access-control configuration has changed; restore the verified application backup instead of dropping authorization data."
        )
    if any(
        i["name"] == "ix_tenant_workspace_names"
        for i in sa.inspect(op.get_bind()).get_indexes("tenants")
    ):
        op.drop_index("ix_tenant_workspace_names", table_name="tenants")
    # Keep global identities, original role column and pre-existing permissions.
    for name in reversed(TABLES):
        op.drop_table(name)
