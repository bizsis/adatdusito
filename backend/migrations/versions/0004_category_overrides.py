"""Simple shared category choices, never reference data or parameter copies."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "category_overrides",
        sa.Column("node_id", sa.String(160), primary_key=True),
        sa.Column("source_key", sa.String(48), nullable=False),
        sa.Column("source_category_id", sa.String(160), nullable=True),
        sa.Column("parent_id", sa.String(160), nullable=True),
        sa.Column("override_parent", sa.Boolean(), nullable=False),
        sa.Column("disable_automatic", sa.Boolean(), nullable=False),
        sa.Column("source_snapshot", sa.String(64), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("category_overrides")
