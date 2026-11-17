"""Independent enrichment worktables (owner-assigned revision 0012)."""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "import_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("import_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_import_template_run", "import_templates", ["run_id", "id"])
    op.create_table(
        "import_template_chunks",
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("import_templates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("format", sa.String(4), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("data", sa.LargeBinary(60000), nullable=False),
    )


def downgrade():
    # Explicit schema rollback removes only the newly introduced generated artifacts.
    op.drop_table("import_template_chunks")
    op.drop_index("ix_import_template_run", table_name="import_templates")
    op.drop_table("import_templates")
