"""Supplier imports and export field administration, application database only."""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
TABLES = [
    "import_suppliers",
    "import_profiles",
    "import_runs",
    "import_file_chunks",
    "supplier_products",
    "import_rows",
    "import_changes",
    "store_engines",
    "store_export_profiles",
]


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "import_suppliers",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
    )
    op.create_index("ix_import_suppliers_tenant_id", "import_suppliers", ["tenant_id"])
    op.create_table(
        "import_profiles",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("import_suppliers.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "supplier_id", "name", "version"),
    )
    op.create_index("ix_import_profiles_tenant_id", "import_profiles", ["tenant_id"])
    op.create_index(
        "ix_import_profiles_supplier_id", "import_profiles", ["supplier_id"]
    )
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("import_suppliers.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("import_profiles.id"),
            nullable=True,
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column(
            "approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("task_token", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_import_runs_tenant_id", "import_runs", ["tenant_id"])
    op.create_index("ix_import_runs_supplier_id", "import_runs", ["supplier_id"])
    op.create_index("ix_import_runs_state", "import_runs", ["state"])
    op.create_table(
        "import_file_chunks",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("import_runs.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("data", sa.LargeBinary(length=60000), nullable=False),
    )
    op.create_table(
        "supplier_products",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("import_suppliers.id"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "last_run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=False
        ),
        sa.Column("last_line", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "supplier_id", "identity_key"),
    )
    op.create_index(
        "ix_supplier_products_supplier_id", "supplier_products", ["supplier_id"]
    )
    op.create_index(
        "ix_supplier_products_tenant_id", "supplier_products", ["tenant_id"]
    )
    op.create_table(
        "import_rows",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("import_runs.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("line", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("supplier_products.id"),
            nullable=True,
        ),
    )
    op.create_table(
        "import_changes",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("supplier_products.id"),
            nullable=False,
        ),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=False
        ),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("delta", sa.JSON(), nullable=False),
    )
    op.create_index("ix_import_changes_product_id", "import_changes", ["product_id"])
    op.create_index("ix_import_changes_run_id", "import_changes", ["run_id"])
    op.create_table(
        "store_engines",
        sa.Column("key", sa.String(length=48), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
    )
    op.create_table(
        "store_export_profiles",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "engine_key",
            sa.String(length=48),
            sa.ForeignKey("store_engines.key"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_store_export_profiles_tenant_id", "store_export_profiles", ["tenant_id"]
    )
    for code, roles in {
        "imports.read": ["superadmin", "tenant_admin", "processor", "reviewer"],
        "imports.manage": ["superadmin", "tenant_admin", "processor"],
        "exports.manage": ["superadmin"],
        "exports.profile": ["superadmin", "tenant_admin"],
    }.items():
        bind.execute(
            sa.text("INSERT INTO permissions (code) VALUES (:code)"), {"code": code}
        )
        for role in roles:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role,permission) VALUES (:role,:code)"
                ),
                {"role": role, "code": code},
            )
    op.bulk_insert(
        sa.table(
            "store_engines",
            sa.column("key"),
            sa.column("name"),
            sa.column("version"),
            sa.column("fields", sa.JSON()),
        ),
        [{"key": "unas", "name": "UNAS", "version": 1, "fields": []}],
    )


def downgrade():
    bind = op.get_bind()
    for code in ["imports.read", "imports.manage", "exports.manage", "exports.profile"]:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission=:code"),
            {"code": code},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE code=:code"), {"code": code}
        )
    for name in reversed(TABLES):
        op.drop_table(name)
