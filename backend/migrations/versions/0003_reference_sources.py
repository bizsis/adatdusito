"""Global reference provenance, not a second category tree or a reference copy."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reference_sources",
        sa.Column("key", sa.String(48), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
    )
    op.create_table(
        "reference_observations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "source_key",
            sa.String(48),
            sa.ForeignKey("reference_sources.key"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime, nullable=False),
        sa.Column("evidence_url", sa.String(1000), nullable=False),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("source_category_id", sa.String(160)),
        sa.Column("canonical_emag_id", sa.Integer),
        sa.Column("mapping_status", sa.String(32), nullable=False),
        sa.Column("evidence_kind", sa.String(48)),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_index(
        "ix_reference_observations_source_key", "reference_observations", ["source_key"]
    )
    op.create_index(
        "ix_reference_observations_canonical_emag_id",
        "reference_observations",
        ["canonical_emag_id"],
    )
    op.bulk_insert(
        sa.table(
            "reference_sources",
            sa.column("key"),
            sa.column("name"),
            sa.column("description"),
        ),
        [
            {
                "key": "emag_marketplace",
                "name": "Helyi eMAG Marketplace referencia",
                "description": "pinfo_db; megőrzött belső és külső azonosítók; csak olvasás.",
            },
            {
                "key": "emag_webshop",
                "name": "eMAG magyar webshop",
                "description": "Nyilvános navigáció, breadcrumb és strukturált adatok; teljessége csak bizonyítékkal állítható.",
            },
            {
                "key": "emag_sitemap",
                "name": "eMAG publikus sitemap",
                "description": "Sitemap-bejegyzés önmagában nem bizonyít Marketplace-azonosságot vagy szülőkapcsolatot.",
            },
            {
                "key": "emag_documentation",
                "name": "eMAG dokumentáció",
                "description": "Paraméterkezelési szabály és forrásleírás; öröklés csak igazolt szabályból.",
            },
        ],
    )


def downgrade():
    op.drop_table("reference_observations")
    op.drop_table("reference_sources")
