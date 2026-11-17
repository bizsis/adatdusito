"""KNOWLEDGE-UI-01: durable web jobs over the existing reference import engine.

Owner-assigned revision, following Claude's unchanged KNOWLEDGE-01 migration 0014.
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("reference_import_runs") as batch:
        batch.add_column(
            sa.Column(
                "ui_config", sa.JSON(), nullable=False, server_default=sa.text("('{}')")
            )
        )
        batch.add_column(
            sa.Column("ui_cursor", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("ui_task_token", sa.String(64), nullable=True))
        batch.add_column(sa.Column("ui_lease_until", sa.DateTime(), nullable=True))
    op.create_table(
        "reference_import_chunks",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("reference_import_runs.id"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("data", sa.LargeBinary(60000), nullable=False),
    )


def downgrade():
    # Stored uploads/progress must be exported/retained before dropping this feature.
    c = op.get_bind()
    if c.scalar(sa.text("SELECT COUNT(*) FROM reference_import_chunks")):
        raise RuntimeError(
            "Stored reference uploads exist; preserve them before downgrading."
        )
    if c.scalar(
        sa.text(
            "SELECT COUNT(*) FROM reference_import_runs WHERE ui_task_token IS NOT NULL"
        )
    ):
        raise RuntimeError(
            "Reference administration jobs are running; stop them before downgrading."
        )
    # MySQL commits DDL immediately: a lower revision's refusal must be checked
    # before any 0015 DDL, or Alembic's version rollback leaves a partial schema.
    destination = op.get_context().opts.get("destination_rev", "0014")
    target = int(destination) if str(destination).isdigit() else 0
    guards = [
        (14, "SELECT COUNT(*) FROM knowledge_values WHERE verified_by IS NOT NULL"),
        (14, "SELECT COUNT(*) FROM knowledge_conflicts WHERE resolved_by IS NOT NULL"),
        (14, "SELECT COUNT(*) FROM knowledge_links WHERE decided_by IS NOT NULL"),
        (13, "SELECT COUNT(*) FROM parameter_mappings WHERE decided_by IS NOT NULL"),
        (
            13,
            "SELECT COUNT(*) FROM reference_product_sources WHERE usage_decided_by IS NOT NULL",
        ),
        (11, "SELECT COUNT(*) FROM preparation_approvals"),
        (10, "SELECT COUNT(*) FROM parameter_aliases"),
        (
            10,
            "SELECT COUNT(*) FROM product_parameter_values WHERE locked = 1 OR origin = 'user'",
        ),
        (9, "SELECT COUNT(*) FROM category_maps"),
        (9, "SELECT COUNT(*) FROM product_events"),
        (9, "SELECT COUNT(*) FROM product_classifications WHERE locked = 1"),
    ]
    for revision_number, query in guards:
        if target < revision_number and c.scalar(sa.text(query)):
            raise RuntimeError(
                "Protected decisions exist; restore the verified backup instead of downgrading."
            )
    op.drop_table("reference_import_chunks")
    with op.batch_alter_table("reference_import_runs") as batch:
        for name in ("ui_lease_until", "ui_task_token", "ui_cursor", "ui_config"):
            batch.drop_column(name)
