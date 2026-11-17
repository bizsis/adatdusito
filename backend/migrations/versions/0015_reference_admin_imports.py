"""KNOWLEDGE-UI-01: durable web jobs over the existing reference import engine.

Owner-assigned revision. 0014 belongs to claude/knowledge-01 and is deliberately
not supplied here. Full chain validation requires integration of that branch.
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
    op.drop_table("reference_import_chunks")
    with op.batch_alter_table("reference_import_runs") as batch:
        for name in ("ui_lease_until", "ui_task_token", "ui_cursor", "ui_config"):
            batch.drop_column(name)
