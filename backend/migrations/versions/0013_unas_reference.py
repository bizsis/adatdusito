"""UNAS-REF-01: UNAS schema registry, parameter definitions, eMAG-UNAS parameter mappings
and an isolated product reference store.

Additive only: eight new tables in the application database. No existing table, row or
permission changes; pinfo_db (emag_*) and the owned catalog_* tables are not touched.

Revision chain: assigned number 0013, integrated in RELEASE-CANDIDATE-03 after TEMPLATE-01's
0012 (0011 -> 0012 -> 0013, a single head). 0013 has no dependency on the 0012 tables; only
the order is fixed. It was never applied to a persistent database on top of 0011.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLES = [
    "reference_product_attributes",
    "reference_product_identifiers",
    "reference_products",
    "reference_import_runs",
    "reference_product_sources",
    "parameter_mappings",
    "unas_parameter_definitions",
    "unas_field_definitions",
]
LONG_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade():
    op.create_table(
        "unas_field_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_source", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("store_key", sa.String(120), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("header", sa.String(500), nullable=False),
        sa.Column("field_key", sa.String(120), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("field_group", sa.String(32), nullable=False),
        sa.Column("data_type", sa.String(32), nullable=False),
        sa.Column("requirement", sa.String(16), nullable=False),
        sa.Column("requirement_source", sa.String(32), nullable=False),
        sa.Column("importable", sa.Boolean(), nullable=True),
        sa.Column("default_value", sa.String(255), nullable=True),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("schema_source", "position", name="uq_unas_field_position"),
    )
    op.create_index("ix_unas_field_definitions_schema_source", "unas_field_definitions",
                    ["schema_source"])
    op.create_table(
        "unas_parameter_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("unas_field_definitions.id"),
                  nullable=False),
        sa.Column("schema_source", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("param_type", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("unit_source", sa.String(32), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("header", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("field_id", name="uq_unas_parameter_field"),
    )
    op.create_index("ix_unas_parameter_definitions_schema_source",
                    "unas_parameter_definitions", ["schema_source"])
    op.create_table(
        "parameter_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_key", sa.String(191), nullable=False),
        sa.Column("emag_category_id", sa.Integer(), nullable=True),
        sa.Column("emag_parameter_id", sa.Integer(), nullable=False),
        sa.Column("emag_parameter_name", sa.String(255), nullable=False),
        sa.Column("unas_parameter_id", sa.Integer(),
                  sa.ForeignKey("unas_parameter_definitions.id"), nullable=True),
        sa.Column("unas_field_id", sa.Integer(), sa.ForeignKey("unas_field_definitions.id"),
                  nullable=True),
        sa.Column("unit_from", sa.String(32), nullable=True),
        sa.Column("unit_to", sa.String(32), nullable=True),
        sa.Column("unit_factor", sa.Numeric(20, 10), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("mapping_key", name="uq_parameter_mapping_key"),
    )
    op.create_index("ix_parameter_mappings_emag_parameter_id", "parameter_mappings",
                    ["emag_parameter_id"])
    op.create_table(
        "reference_product_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("store_key", sa.String(120), nullable=True),
        sa.Column("schema_source", sa.String(160), nullable=True),
        sa.Column("usage_status", sa.String(24), nullable=False, server_default="restricted"),
        sa.Column("enrichment_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("usage_note", sa.String(1000), nullable=True),
        sa.Column("usage_decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("usage_decided_at", sa.DateTime(), nullable=True),
        sa.Column("excluded_columns", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "reference_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_reference_import_runs_source_id", "reference_import_runs", ["source_id"])
    op.create_table(
        "reference_products",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("reference_product_sources.id"),
                  nullable=False),
        sa.Column("source_sku", sa.String(120), nullable=False),
        sa.Column("source_record_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(500), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("category_path", sa.Text(), nullable=True),
        sa.Column("short_description", LONG_TEXT, nullable=True),
        sa.Column("long_description", LONG_TEXT, nullable=True),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(64), nullable=False),
        sa.Column("first_import_id", sa.Integer(), sa.ForeignKey("reference_import_runs.id"),
                  nullable=False),
        sa.Column("last_import_id", sa.Integer(), sa.ForeignKey("reference_import_runs.id"),
                  nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_id", "source_sku", name="uq_reference_product_sku"),
    )
    op.create_table(
        "reference_product_identifiers",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("product_id", BIG_ID, sa.ForeignKey("reference_products.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("value", sa.String(120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("raw_header", sa.String(500), nullable=False),
        sa.UniqueConstraint("product_id", "kind", "value", name="uq_reference_identifier"),
    )
    op.create_index("ix_reference_product_identifiers_product_id",
                    "reference_product_identifiers", ["product_id"])
    op.create_index("ix_reference_product_identifiers_value", "reference_product_identifiers",
                    ["value"])
    op.create_table(
        "reference_product_attributes",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("product_id", BIG_ID, sa.ForeignKey("reference_products.id"), nullable=False),
        sa.Column("parameter_id", sa.Integer(), sa.ForeignKey("unas_parameter_definitions.id"),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("value_text", LONG_TEXT, nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.UniqueConstraint("product_id", "parameter_id", name="uq_reference_attribute"),
    )
    op.create_index("ix_reference_product_attributes_product_id",
                    "reference_product_attributes", ["product_id"])


def downgrade():
    c = op.get_bind()
    decisions = c.scalar(sa.text(
        "SELECT COUNT(*) FROM parameter_mappings WHERE decided_by IS NOT NULL")) + c.scalar(
        sa.text("SELECT COUNT(*) FROM reference_product_sources "
                "WHERE usage_decided_by IS NOT NULL"))
    if decisions:
        raise RuntimeError(
            "Mapping or usage decisions exist; restore the verified pre-0013 backup instead "
            "of downgrading."
        )
    # Reference rows are reproducible from their source export files. drop_table removes
    # each table's own indexes (MySQL error 1553 otherwise, see RELEASE-02).
    for name in TABLES:
        op.drop_table(name)
