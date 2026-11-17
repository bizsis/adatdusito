"""UNAS-REF-01 application tables (migration 0013). Application database only; the eMAG
reference tables in pinfo_db and the owned catalog_* copy are never written here."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, now

# Long HTML descriptions can exceed MySQL TEXT (64 KB).
LongText = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class UnasFieldDefinition(Base):
    """One column of one UNAS export schema (a store's export at a point in time)."""

    __tablename__ = "unas_field_definitions"
    __table_args__ = (UniqueConstraint("schema_source", "position", name="uq_unas_field_position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    schema_source: Mapped[str] = mapped_column(String(160), index=True)
    source_version: Mapped[str] = mapped_column(String(64))
    store_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    position: Mapped[int] = mapped_column(Integer)
    header: Mapped[str] = mapped_column(String(500))
    field_key: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(16))  # standard | store_specific | unknown
    field_group: Mapped[str] = mapped_column(String(32))
    data_type: Mapped[str] = mapped_column(String(32))
    requirement: Mapped[str] = mapped_column(String(16))  # required | recommended | optional
    requirement_source: Mapped[str] = mapped_column(String(32))
    importable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None: unknown
    default_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    validation: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile: Mapped[dict] = mapped_column(JSON)  # fill rate / value shape in the export
    # May this column's content enter the shared knowledge base? (never prices, stock,
    # customer-group, system or integration identifiers)
    shareable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class UnasParameterDefinition(Base):
    """A "Paraméter: name|group|type|...|unit|..." header, every position kept raw."""

    __tablename__ = "unas_parameter_definitions"
    __table_args__ = (UniqueConstraint("field_id", name="uq_unas_parameter_field"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("unas_field_definitions.id"))
    schema_source: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(255))
    group_name: Mapped[str] = mapped_column(String(255), default="")
    param_type: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings: Mapped[list] = mapped_column(JSON)
    header: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ParameterMapping(Base):
    """eMAG parameter -> UNAS parameter or field. Never active without approval."""

    __tablename__ = "parameter_mappings"
    __table_args__ = (UniqueConstraint("mapping_key", name="uq_parameter_mapping_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(191))
    emag_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emag_parameter_id: Mapped[int] = mapped_column(Integer, index=True)
    emag_parameter_name: Mapped[str] = mapped_column(String(255))
    unas_parameter_id: Mapped[int | None] = mapped_column(
        ForeignKey("unas_parameter_definitions.id"), nullable=True
    )
    unas_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("unas_field_definitions.id"), nullable=True
    )
    unit_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    origin: Mapped[str] = mapped_column(String(16))  # automatic | manual
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ReferenceProductSource(Base):
    """A reference data source; enrichment use needs an explicit, recorded permission."""

    __tablename__ = "reference_product_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    store_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # KNOWLEDGE-01: a tenant's own uploads become a source with tenant_id set.
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    schema_source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    usage_status: Mapped[str] = mapped_column(String(24), default="restricted")
    # Why use is allowed: "owner_policy:<date>", "written_permission", "none", ...
    usage_basis: Mapped[str] = mapped_column(String(64), default="none")
    enrichment_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    contribution: Mapped[str] = mapped_column(String(16), default="automatic")
    trust_level: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    usage_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    usage_decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    usage_decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    excluded_columns: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReferenceImportRun(Base):
    __tablename__ = "reference_import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("reference_product_sources.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    counters: Mapped[dict] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON)  # first 200 row errors: {line, code}
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Web administration job metadata; original import engine is reused.
    ui_config: Mapped[dict] = mapped_column(JSON, default=dict)
    ui_cursor: Mapped[int] = mapped_column(Integer, default=0)
    ui_task_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ui_lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReferenceImportChunk(Base):
    __tablename__ = "reference_import_chunks"
    run_id: Mapped[int] = mapped_column(ForeignKey("reference_import_runs.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary(60000))


class ReferenceProduct(Base):
    __tablename__ = "reference_products"
    __table_args__ = (UniqueConstraint("source_id", "source_sku", name="uq_reference_product_sku"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("reference_product_sources.id"))
    source_sku: Mapped[str] = mapped_column(String(120))
    source_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(LongText, nullable=True)
    long_description: Mapped[str | None] = mapped_column(LongText, nullable=True)
    images: Mapped[list] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON)  # every non-excluded column, value as exported
    raw_sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(64))
    # Nothing is "verified" automatically; KNOWLEDGE-01 raises it from approvals/agreement.
    verification: Mapped[str] = mapped_column(String(16), default="unverified")
    first_import_id: Mapped[int] = mapped_column(ForeignKey("reference_import_runs.id"))
    last_import_id: Mapped[int] = mapped_column(ForeignKey("reference_import_runs.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReferenceProductIdentifier(Base):
    """Textual identifiers (EAN/GTIN, source SKU, ...); a product may have several EANs."""

    __tablename__ = "reference_product_identifiers"
    __table_args__ = (
        UniqueConstraint("product_id", "kind", "value", name="uq_reference_identifier"),
    )
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("reference_products.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # gtin | source_sku | external_id
    value: Mapped[str] = mapped_column(String(120), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    issues: Mapped[list] = mapped_column(JSON)
    raw_header: Mapped[str] = mapped_column(String(500))


class ReferenceProductAttribute(Base):
    __tablename__ = "reference_product_attributes"
    __table_args__ = (
        UniqueConstraint("product_id", "parameter_id", name="uq_reference_attribute"),
    )
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("reference_products.id"), index=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("unas_parameter_definitions.id"))
    name: Mapped[str] = mapped_column(String(255))
    group_name: Mapped[str] = mapped_column(String(255), default="")
    value_text: Mapped[str] = mapped_column(LongText)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
