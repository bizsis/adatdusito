"""Owned, versioned catalog; application database only."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("source_state", sa.JSON(), nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "catalog_categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
    )
    op.create_table(
        "catalog_parameters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "catalog_category_parameters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("key", sa.String(length=160), nullable=False, unique=True),
    )
    op.create_table(
        "catalog_parameter_values",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "parameter_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_parameters.id"),
            nullable=False,
        ),
        sa.Column("value_text", sa.Text(), nullable=False),
    )
    op.create_table(
        "catalog_category_nodes",
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("catalog_versions.id"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(length=160), primary_key=True),
        sa.Column(
            "category_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_categories.id"),
            nullable=True,
        ),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_catalog_category_nodes_category_id",
        "catalog_category_nodes",
        ["category_id"],
    )
    op.create_table(
        "catalog_category_parameter_entries",
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("catalog_versions.id"),
            primary_key=True,
        ),
        sa.Column(
            "link_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_category_parameters.id"),
            primary_key=True,
        ),
        sa.Column(
            "category_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_categories.id"),
            nullable=False,
        ),
        sa.Column(
            "parameter_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_parameters.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("emag_parameter_id", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=True),
        sa.Column("is_filter", sa.Boolean(), nullable=True),
        sa.Column("allow_new_value", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "ix_catalog_category_parameter_entries_category_id",
        "catalog_category_parameter_entries",
        ["category_id"],
    )
    op.create_index(
        "ix_catalog_entry_category",
        "catalog_category_parameter_entries",
        ["version_id", "category_id", "display_order", "link_id"],
    )
    op.create_table(
        "catalog_source_mappings",
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("catalog_versions.id"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(length=24), primary_key=True),
        sa.Column("source_key", sa.String(length=48), primary_key=True),
        sa.Column("source_id", sa.BigInteger(), primary_key=True),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("context_id", sa.BigInteger(), nullable=True),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_catalog_mapping_external",
        "catalog_source_mappings",
        ["version_id", "kind", "source_key", "external_id"],
    )
    op.create_index(
        "ix_catalog_mapping_values",
        "catalog_source_mappings",
        ["version_id", "kind", "context_id", "target_id"],
    )

    op.create_index(
        "ix_catalog_mapping_targets",
        "catalog_source_mappings",
        ["version_id", "kind", "target_id"],
    )


def downgrade():
    connection = op.get_bind()
    locked = connection.dialect.name == "mysql"
    if (
        locked
        and connection.execute(
            sa.text("SELECT GET_LOCK('adatdusito.catalog_import', 0)")
        ).scalar()
        != 1
    ):
        raise RuntimeError(
            "Catalog import/activation is running; schema downgrade refused"
        )
    try:
        active = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT value FROM system_settings WHERE `key` = 'reference_catalog_active'"
                )
            )
            .scalar()
        )
        if active and active != "legacy":
            raise RuntimeError(
                "Deactivate the owned catalog before schema downgrade; prefer version-pointer rollback"
            )
        op.drop_table("catalog_source_mappings")
        op.drop_table("catalog_category_parameter_entries")
        op.drop_table("catalog_category_nodes")
        op.drop_table("catalog_parameter_values")
        op.drop_table("catalog_category_parameters")
        op.drop_table("catalog_parameters")
        op.drop_table("catalog_categories")
        op.drop_table("catalog_versions")
    finally:
        if locked:
            connection.execute(
                sa.text("SELECT RELEASE_LOCK('adatdusito.catalog_import')")
            )
