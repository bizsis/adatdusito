"""CATEGORY-02A: lossless source attributes, own categories, internal classification.

Additive only: existing products, import rows, changes, profiles and access data
are untouched (new columns are nullable or defaulted). pinfo_db is never
touched. Existing products are filled later by the resumable backfill job
(python -m app.product_backfill), not inside this migration.
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLES = [
    "product_source_categories",
    "category_maps",
    "product_classifications",
    "product_events",
    "product_jobs",
]
PERMISSION = "products.classify"


def upgrade():
    op.create_table(
        "product_source_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("import_suppliers.id"), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False, server_default="supplier"),
        sa.Column("path_key", sa.String(64), nullable=False),
        sa.Column("path_text", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "supplier_id", "origin", "path_key", name="uq_source_category_path"),
    )
    op.create_index("ix_product_source_categories_tenant_id", "product_source_categories", ["tenant_id"])
    op.create_table(
        "category_maps",
        sa.Column(
            "source_category_id",
            sa.Integer(),
            sa.ForeignKey("product_source_categories.id"),
            primary_key=True,
        ),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("navigation_node_id", sa.String(160), nullable=True),
        sa.Column("donor_emag_category_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_category_maps_tenant_id", "category_maps", ["tenant_id"])
    with op.batch_alter_table("supplier_products") as b:
        b.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        b.add_column(sa.Column("source_category_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("source_attributes", sa.JSON(), nullable=True))
        b.add_column(sa.Column("search_text", sa.String(1024), nullable=True))
        b.create_foreign_key(
            "fk_product_source_category",
            "product_source_categories",
            ["source_category_id"],
            ["id"],
        )
        b.create_index("ix_supplier_products_source_category_id", ["source_category_id"])
    op.create_table(
        "product_classifications",
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("method", sa.String(48), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("navigation_node_id", sa.String(160), nullable=True),
        sa.Column("donor_emag_category_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("map_revision", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_classification_status", "product_classifications", ["tenant_id", "status"])
    op.create_index("ix_product_classification_node", "product_classifications", ["tenant_id", "navigation_node_id"])
    op.create_table(
        "product_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), nullable=True),
        sa.Column(
            "source_category_id",
            sa.Integer(),
            sa.ForeignKey("product_source_categories.id"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_events_product", "product_events", ["tenant_id", "product_id", "id"])
    op.create_table(
        "product_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("task_token", sa.String(64), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("code"))
    if not bind.scalar(sa.select(permissions.c.code).where(permissions.c.code == PERMISSION)):
        bind.execute(permissions.insert().values(code=PERMISSION))


def downgrade():
    c = op.get_bind()
    decisions = c.scalar(sa.text("SELECT COUNT(*) FROM category_maps")) + c.scalar(
        sa.text("SELECT COUNT(*) FROM product_events")
    ) + c.scalar(sa.text("SELECT COUNT(*) FROM product_classifications WHERE locked = 1"))
    if decisions:
        raise RuntimeError(
            "Category decisions exist; restore the verified pre-0009 backup instead of downgrading."
        )
    for name in ["product_jobs", "product_events", "product_classifications"]:
        op.drop_table(name)
    with op.batch_alter_table("supplier_products") as b:
        b.drop_index("ix_supplier_products_source_category_id")
        b.drop_constraint("fk_product_source_category", type_="foreignkey")
        for col in ["search_text", "source_attributes", "source_category_id", "revision"]:
            b.drop_column(col)
    op.drop_index("ix_category_maps_tenant_id", "category_maps")
    op.drop_table("category_maps")
    op.drop_index("ix_product_source_categories_tenant_id", "product_source_categories")
    op.drop_table("product_source_categories")
    c.execute(sa.text("DELETE FROM role_permissions WHERE permission = :p"), {"p": PERMISSION})
    c.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": PERMISSION})
