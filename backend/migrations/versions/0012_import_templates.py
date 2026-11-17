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
    # MySQL DDL commits immediately. Preflight the lower revisions' decision
    # guards before dropping anything, otherwise a later refusal rolls back the
    # Alembic version update but cannot restore already dropped template tables.
    destination = op.get_context().opts.get("destination_rev", "0011")
    target = int(destination) if str(destination).isdigit() else 0
    c = op.get_bind()
    guards = [
        (
            11,
            "SELECT COUNT(*) FROM preparation_approvals",
            "Preparation approvals exist",
        ),
        (10, "SELECT COUNT(*) FROM parameter_aliases", "Parameter decisions exist"),
        (
            10,
            "SELECT COUNT(*) FROM product_parameter_values WHERE locked = 1 OR origin = 'user'",
            "Parameter decisions exist",
        ),
        (9, "SELECT COUNT(*) FROM category_maps", "Category decisions exist"),
        (9, "SELECT COUNT(*) FROM product_events", "Category decisions exist"),
        (
            9,
            "SELECT COUNT(*) FROM product_classifications WHERE locked = 1",
            "Category decisions exist",
        ),
    ]
    for level, query, reason in guards:
        if target < level and c.scalar(sa.text(query)):
            raise RuntimeError(
                f"{reason}; restore the verified backup instead of downgrading."
            )
    # drop_table also removes its own indexes, including those needed by a FK.
    op.drop_table("import_template_chunks")
    op.drop_table("import_templates")
