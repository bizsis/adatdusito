"""CATEGORY-03C: selections, bulk operation items and preparation approvals.

Additive only: five new tenant-scoped tables, three nullable columns and one
unique index on product_jobs, two permissions. Existing data is untouched;
pinfo_db is never touched.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

PERMISSIONS = ["products.bulk", "products.prepare.approve"]


def upgrade():
    with op.batch_alter_table("product_jobs") as b:
        b.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        b.add_column(sa.Column("idempotency_key", sa.String(80), nullable=True))
        b.add_column(sa.Column("request_hash", sa.String(64), nullable=True))
        b.create_foreign_key("fk_product_job_created_by", "users", ["created_by"], ["id"])
        b.create_unique_constraint("uq_product_job_idempotency", ["tenant_id", "kind", "idempotency_key"])
    op.create_table(
        "product_selections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("excluded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("catalog_version_id", sa.Integer(), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_product_selection_token"),
    )
    op.create_index("ix_product_selections_tenant_id", "product_selections", ["tenant_id"])
    op.create_table(
        "product_selection_items",
        sa.Column("selection_id", sa.Integer(), sa.ForeignKey("product_selections.id"), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "product_operation_items",
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("product_jobs.id"), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("apply_job_id", sa.Integer(), sa.ForeignKey("product_jobs.id"), nullable=True),
        sa.Column("apply_outcome", sa.String(32), nullable=True),
        sa.Column("revision_after", sa.Integer(), nullable=True),
    )
    op.create_index("ix_operation_item_outcome", "product_operation_items", ["job_id", "outcome", "product_id"])
    op.create_index("ix_operation_item_apply", "product_operation_items",
                    ["apply_job_id", "apply_outcome", "product_id"])
    op.create_table(
        "preparation_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("check_id", sa.Integer(), sa.ForeignKey("product_jobs.id"), nullable=False),
        sa.Column("selection_id", sa.Integer(), sa.ForeignKey("product_selections.id"), nullable=False),
        sa.Column("catalog_version_id", sa.Integer(), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("schema_fingerprint", sa.String(64), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(500), nullable=True),
        sa.Column("revalidated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_preparation_approval_idempotency"),
    )
    op.create_index("ix_preparation_approval_tenant", "preparation_approvals", ["tenant_id", "state", "id"])
    op.create_table(
        "preparation_approval_items",
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("preparation_approvals.id"), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("supplier_products.id"), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_revision", sa.Integer(), nullable=False),
        sa.Column("navigation_node_id", sa.String(160), nullable=True),
        sa.Column("donor_emag_category_id", sa.Integer(), nullable=True),
        sa.Column("research_targets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mandatory_research_targets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("invalid_reason", sa.String(32), nullable=True),
    )
    op.create_index("ix_preparation_item_product", "preparation_approval_items",
                    ["tenant_id", "product_id", "approval_id"])
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("code"))
    for code in PERMISSIONS:
        if not bind.scalar(sa.select(permissions.c.code).where(permissions.c.code == code)):
            bind.execute(permissions.insert().values(code=code))


def downgrade():
    c = op.get_bind()
    if c.scalar(sa.text("SELECT COUNT(*) FROM preparation_approvals")):
        raise RuntimeError(
            "Preparation approvals exist; restore the verified pre-0011 backup instead of downgrading."
        )
    # drop_table removes the tables' own indexes; dropping them one by one first
    # fails on MySQL (error 1553) because they back foreign keys.
    op.drop_table("preparation_approval_items")
    op.drop_table("preparation_approvals")
    op.drop_table("product_operation_items")
    op.drop_table("product_selection_items")
    op.drop_table("product_selections")
    # Bulk job rows are operational history of the removed tables.
    c.execute(sa.text("DELETE FROM product_jobs WHERE kind IN ('bulk_preview','bulk_apply','preparation_check')"))
    if c.dialect.name == "mysql":
        # On MySQL the unique index (tenant_id, kind, idempotency_key) silently replaced
        # the implicit index of the unnamed tenant_id foreign key created in 0009, so it
        # cannot be dropped while that key exists (error 1553). Drop the key, then add it
        # back unnamed after the unique index is gone: MySQL recreates the same implicit
        # index and key name, so the 0010 schema is exactly as before and a later 0011
        # upgrade replaces the implicit index again.
        tenant_fk = next(
            fk["name"]
            for fk in sa.inspect(c).get_foreign_keys("product_jobs")
            if fk["referred_table"] == "tenants" and fk["constrained_columns"] == ["tenant_id"]
        )
        op.drop_constraint("fk_product_job_created_by", "product_jobs", type_="foreignkey")
        op.drop_constraint(tenant_fk, "product_jobs", type_="foreignkey")
        op.drop_constraint("uq_product_job_idempotency", "product_jobs", type_="unique")
        for col in ["request_hash", "idempotency_key", "created_by"]:
            op.drop_column("product_jobs", col)
        c.execute(sa.text("ALTER TABLE product_jobs ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id)"))
    else:
        with op.batch_alter_table("product_jobs") as b:
            b.drop_constraint("uq_product_job_idempotency", type_="unique")
            b.drop_constraint("fk_product_job_created_by", type_="foreignkey")
            b.drop_column("request_hash")
            b.drop_column("idempotency_key")
            b.drop_column("created_by")
    for code in PERMISSIONS:
        c.execute(sa.text("DELETE FROM role_permissions WHERE permission = :p"), {"p": code})
        c.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": code})
