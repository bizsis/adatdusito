"""KNOWLEDGE-02: source independence, manual merges, text variants, personal-data holds.

Owner-assigned revision 0016 on top of 0015 (chain 0013 -> 0014 -> 0015 -> 0016). Additive
only: three new tables and nullable/defaulted columns; 0014 and 0015 are unchanged.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
LONG_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade():
    with op.batch_alter_table("reference_product_sources") as b:
        b.add_column(sa.Column("lineage_group", sa.String(64), nullable=True))
    with op.batch_alter_table("knowledge_observations") as b:
        b.add_column(sa.Column("identity_confidence", sa.Numeric(5, 4), nullable=True))
        b.add_column(sa.Column("pii_flags", sa.JSON(), nullable=True))
        b.add_column(sa.Column("pii_reviewed_by", sa.Integer(), nullable=True))
        b.add_column(sa.Column("pii_reviewed_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("knowledge_values") as b:
        b.add_column(sa.Column("independent_sources", sa.Integer(), nullable=False,
                               server_default="0"))
    op.create_table(
        "knowledge_source_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_a_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("source_b_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("shared_values", sa.Integer(), nullable=False),
        sa.Column("identical_values", sa.Integer(), nullable=False),
        sa.Column("identical_texts", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Numeric(5, 4), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_a_id", "source_b_id", name="uq_knowledge_source_pair"),
    )
    op.create_table(
        "knowledge_merges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("survivor_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("merged_id", BIG_ID, sa.ForeignKey("knowledge_products.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("preview_token", sa.String(64), nullable=False),
        sa.Column("variant_risk_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("moved", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("applied_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("reverted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reverted_at", sa.DateTime(), nullable=True),
        sa.Column("revert_reason", sa.String(500), nullable=True),
    )
    op.create_index("ix_knowledge_merges_survivor_id", "knowledge_merges", ["survivor_id"])
    op.create_table(
        "knowledge_texts",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("knowledge_product_id", BIG_ID, sa.ForeignKey("knowledge_products.id"),
                  nullable=False),
        sa.Column("link_id", BIG_ID, sa.ForeignKey("knowledge_links.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("text", LONG_TEXT, nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("language_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("language_method", sa.String(16), nullable=False),
        sa.Column("verification", sa.String(16), nullable=False),
        sa.Column("usage", sa.String(16), nullable=False),
        sa.Column("pii_flags", sa.JSON(), nullable=False),
        sa.Column("pii_reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("pii_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("link_id", "kind", "text_hash", name="uq_knowledge_text_variant"),
    )
    op.create_index("ix_knowledge_texts_knowledge_product_id", "knowledge_texts",
                    ["knowledge_product_id"])


def downgrade():
    c = op.get_bind()
    decisions = sum(c.scalar(sa.text(q)) for q in (
        "SELECT COUNT(*) FROM knowledge_merges",
        "SELECT COUNT(*) FROM knowledge_texts WHERE decided_by IS NOT NULL "
        "OR pii_reviewed_by IS NOT NULL",
        "SELECT COUNT(*) FROM knowledge_source_relations WHERE decided_by IS NOT NULL",
        "SELECT COUNT(*) FROM knowledge_observations WHERE pii_reviewed_by IS NOT NULL",
        "SELECT COUNT(*) FROM reference_product_sources WHERE lineage_group IS NOT NULL",
    ))
    if decisions:
        raise RuntimeError(
            "Knowledge-02 decisions exist; restore the verified pre-0016 backup instead of "
            "downgrading."
        )
    # Texts and suspected relations are rebuilt from the sources; drop_table removes each
    # table's own indexes (MySQL error 1553 otherwise, see RELEASE-02).
    for name in ("knowledge_texts", "knowledge_merges", "knowledge_source_relations"):
        op.drop_table(name)
    with op.batch_alter_table("knowledge_values") as b:
        b.drop_column("independent_sources")
    with op.batch_alter_table("knowledge_observations") as b:
        for column in ("pii_reviewed_at", "pii_reviewed_by", "pii_flags", "identity_confidence"):
            b.drop_column(column)
    with op.batch_alter_table("reference_product_sources") as b:
        b.drop_column("lineage_group")
