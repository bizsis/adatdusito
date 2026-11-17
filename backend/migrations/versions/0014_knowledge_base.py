"""KNOWLEDGE-01: central product knowledge base (clusters, identities, source links,
observations, consolidated values, conflicts, events).

Additive only: seven new tables in the application database, built on the RC-03 reference
store (reference_product_sources / reference_products) and the tenants' supplier_products.
No existing table or row changes; pinfo_db is not touched. Assigned number 0014 (owner).
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TABLES = ["knowledge_events", "knowledge_conflicts", "knowledge_values",
          "knowledge_observations", "knowledge_links", "knowledge_identities",
          "knowledge_products"]


def upgrade():
    op.create_table(
        "knowledge_products",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("merged_into_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=True),
        sa.Column("display_name", sa.String(500), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "knowledge_identities",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kind", "value", name="uq_knowledge_identity"),
    )
    op.create_index("ix_knowledge_identities_knowledge_product_id", "knowledge_identities",
                    ["knowledge_product_id"])
    op.create_table(
        "knowledge_links",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("member_kind", sa.String(24), nullable=False),
        sa.Column("member_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("member_kind", "member_id", name="uq_knowledge_member"),
    )
    op.create_index("ix_knowledge_links_knowledge_product_id", "knowledge_links",
                    ["knowledge_product_id"])
    op.create_table(
        "knowledge_observations",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("link_id", BIG_ID, sa.ForeignKey("knowledge_links.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("attribute_key", sa.String(191), nullable=False),
        sa.Column("attribute_label", sa.String(255), nullable=False),
        sa.Column("value_raw", sa.String(1000), nullable=False),
        sa.Column("value_norm", sa.String(1000), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_knowledge_observations_knowledge_product_id", "knowledge_observations",
                    ["knowledge_product_id"])
    op.create_index("ix_knowledge_observations_link_id", "knowledge_observations", ["link_id"])
    op.create_table(
        "knowledge_values",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("attribute_key", sa.String(191), nullable=False),
        sa.Column("attribute_label", sa.String(255), nullable=False),
        sa.Column("value_norm", sa.String(1000), nullable=True),
        sa.Column("value_display", sa.String(1000), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("support_sources", sa.Integer(), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("verification_basis", sa.String(32), nullable=True),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_values", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("knowledge_product_id", "attribute_key", name="uq_knowledge_value"),
    )
    op.create_table(
        "knowledge_conflicts",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("value_id", BIG_ID, sa.ForeignKey("knowledge_values.id"), nullable=False),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("attribute_key", sa.String(191), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("resolution", sa.String(1000), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_conflicts_value_id", "knowledge_conflicts", ["value_id"])
    op.create_table(
        "knowledge_events",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=True),
        sa.Column("value_id", sa.BigInteger(), nullable=True),
        sa.Column("link_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_events_knowledge_product_id", "knowledge_events",
                    ["knowledge_product_id"])


def downgrade():
    c = op.get_bind()
    decisions = c.scalar(sa.text(
        "SELECT COUNT(*) FROM knowledge_values WHERE verified_by IS NOT NULL")) + c.scalar(
        sa.text("SELECT COUNT(*) FROM knowledge_conflicts WHERE resolved_by IS NOT NULL")) + \
        c.scalar(sa.text("SELECT COUNT(*) FROM knowledge_links WHERE decided_by IS NOT NULL"))
    if decisions:
        raise RuntimeError(
            "Knowledge decisions exist; restore the verified pre-0014 backup instead of "
            "downgrading."
        )
    # Everything else is rebuilt from the sources (python -m app.knowledge rebuild).
    for name in TABLES:
        op.drop_table(name)
