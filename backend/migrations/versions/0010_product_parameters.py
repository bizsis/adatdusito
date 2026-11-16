"""CATEGORY-03A: parameter slots and approved parameter aliases.

Additive only: two new tenant-scoped tables in the application database and
two permissions. Existing products, imports, classifications and catalog data
are untouched; pinfo_db is never touched. Slots are produced later by the
resumable parameter run (POST /api/v1/workspace/parameter-runs), not here.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

PERMISSIONS = ["products.parameters", "parameters.global_aliases.manage"]


def upgrade():
    op.create_table(
        "parameter_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("active_key", sa.String(64), nullable=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("label_key", sa.String(160), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False, server_default=""),
        sa.Column("emag_parameter_id", sa.Integer(), nullable=False),
        sa.Column("scope_emag_category_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("active_key", name="uq_parameter_alias_active"),
    )
    op.create_index("ix_parameter_alias_lookup", "parameter_aliases",
                    ["scope_emag_category_id", "label_key", "state"])
    op.create_index("ix_parameter_alias_tenant", "parameter_aliases", ["tenant_id", "state"])
    op.create_table(
        "product_parameter_values",
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), primary_key=True),
        sa.Column("slot_key", sa.String(191), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("emag_parameter_id", sa.Integer(), nullable=True),
        sa.Column("donor_emag_category_id", sa.Integer(), nullable=True),
        sa.Column("catalog_link_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("value", sa.String(1000), nullable=True),
        sa.Column("unit", sa.String(24), nullable=True),
        sa.Column("value_id", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("catalog_version_id", sa.Integer(), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_parameter_state", "product_parameter_values",
                    ["tenant_id", "state", "mandatory", "product_id"])
    op.create_index("ix_product_parameter_emag", "product_parameter_values",
                    ["tenant_id", "emag_parameter_id"])
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("code"))
    for code in PERMISSIONS:
        if not bind.scalar(sa.select(permissions.c.code).where(permissions.c.code == code)):
            bind.execute(permissions.insert().values(code=code))


def downgrade():
    c = op.get_bind()
    decisions = c.scalar(sa.text("SELECT COUNT(*) FROM parameter_aliases")) + c.scalar(
        sa.text("SELECT COUNT(*) FROM product_parameter_values WHERE locked = 1 OR origin = 'user'")
    )
    if decisions:
        raise RuntimeError(
            "Parameter decisions exist; restore the verified pre-0010 backup instead of downgrading."
        )
    # drop_table removes the tables' own indexes; dropping them one by one first
    # fails on MySQL (error 1553) because they back the tenant_id foreign keys.
    op.drop_table("product_parameter_values")
    op.drop_table("parameter_aliases")
    for code in PERMISSIONS:
        c.execute(sa.text("DELETE FROM role_permissions WHERE permission = :p"), {"p": code})
        c.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": code})
