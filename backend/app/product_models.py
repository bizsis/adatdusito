"""CATEGORY-02A: own categories, internal classification and product history.

The customer's own (supplier/webshop) category and the internal classification
are separate records: classification never rewrites the own category, and the
eMAG donor category only supplies parameter definitions. Every table is
tenant-scoped; reference data (pinfo_db, catalog_*) is never written.
"""

from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, now


class ProductSourceCategory(Base):
    __tablename__ = "product_source_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "origin", "path_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_suppliers.id"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String(16), default="supplier")
    path_key: Mapped[str] = mapped_column(String(64))
    path_text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CategoryMap(Base):
    """Tenant-approved mapping of one own category to an internal category."""

    __tablename__ = "category_maps"
    source_category_id: Mapped[int] = mapped_column(
        ForeignKey("product_source_categories.id"), primary_key=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    state: Mapped[str] = mapped_column(String(16))  # approved / rejected
    navigation_node_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    donor_emag_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(default=1)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProductClassification(Base):
    __tablename__ = "product_classifications"
    __table_args__ = (
        Index("ix_product_classification_status", "tenant_id", "status"),
        Index("ix_product_classification_node", "tenant_id", "navigation_node_id"),
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), primary_key=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    # auto_classified ("Automatikusan besorolt") / needs_review ("Ellenőrzést igényel")
    status: Mapped[str] = mapped_column(String(24))
    # category_map / manual / suggestion / none
    origin: Mapped[str] = mapped_column(String(24))
    method: Mapped[str | None] = mapped_column(String(48), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32))
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    navigation_node_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    donor_emag_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    map_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProductEvent(Base):
    """Non-import product history (classification decisions, maps, backfill)."""

    __tablename__ = "product_events"
    __table_args__ = (Index("ix_product_events_product", "tenant_id", "product_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_products.id"), nullable=True
    )
    source_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_source_categories.id"), nullable=True
    )
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProductJob(Base):
    """Resumable maintenance jobs (e.g. backfill), leased like import runs."""

    __tablename__ = "product_jobs"
    __table_args__ = (
        # CATEGORY-03C: an idempotency key is unique per tenant and job kind.
        UniqueConstraint("tenant_id", "kind", "idempotency_key", name="uq_product_job_idempotency"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    cursor: Mapped[int] = mapped_column(default=0)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    task_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    # CATEGORY-03C (0011)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


# --- CATEGORY-03A: parameter slots and aliases (migration 0010) ---------------


class ParameterAlias(Base):
    """Approved mapping of a source label (+unit) to one donor parameter.

    tenant_id NULL = global alias (separate system permission). Every alias is
    bound to a donor context (scope_emag_category_id). Rows are never deleted:
    revoking sets state="revoked" and bumps version.
    """

    __tablename__ = "parameter_aliases"
    __table_args__ = (
        Index("ix_parameter_alias_lookup", "scope_emag_category_id", "label_key", "state"),
        Index("ix_parameter_alias_tenant", "tenant_id", "state"),
        UniqueConstraint("active_key", name="uq_parameter_alias_active"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    # Unique identity of an approved alias; NULL once revoked (MySQL allows
    # several NULLs in a unique index), so history rows never collide.
    active_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(160))
    label_key: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(24), default="")
    emag_parameter_id: Mapped[int] = mapped_column(Integer)
    scope_emag_category_id: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="approved")
    version: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProductParameterValue(Base):
    """One parameter slot of one product (emag:<id> or src:<source key>).

    Original header/value/unit/origin are kept verbatim in `sources`; the
    normalized value is only derived deterministically. A locked slot is never
    written by automation.
    """

    __tablename__ = "product_parameter_values"
    __table_args__ = (
        Index("ix_product_parameter_state", "tenant_id", "state", "mandatory", "product_id"),
        Index("ix_product_parameter_emag", "tenant_id", "emag_parameter_id"),
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("supplier_products.id"), primary_key=True)
    slot_key: Mapped[str] = mapped_column(String(191), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    emag_parameter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    donor_emag_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    catalog_link_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(String(16))
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    value: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    value_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)  # sources, candidates, conversion, alias
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    catalog_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# --- CATEGORY-03C: selections, bulk operation items, preparation approvals ----


class ProductSelection(Base):
    """Server-side snapshot of a filtered product set; the token is stored hashed."""

    __tablename__ = "product_selections"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    mode: Mapped[str] = mapped_column(String(16))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    excluded: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    catalog_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class ProductSelectionItem(Base):
    __tablename__ = "product_selection_items"
    selection_id: Mapped[int] = mapped_column(ForeignKey("product_selections.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("supplier_products.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)


class ProductOperationItem(Base):
    """Per-product result of a bulk preview / preparation check (job_id), and of
    the apply runs that consumed it (apply_job_id, apply_outcome)."""

    __tablename__ = "product_operation_items"
    __table_args__ = (
        Index("ix_operation_item_outcome", "job_id", "outcome", "product_id"),
        Index("ix_operation_item_apply", "apply_job_id", "apply_outcome", "product_id"),
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("product_jobs.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("supplier_products.id"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    revision_before: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    apply_job_id: Mapped[int | None] = mapped_column(ForeignKey("product_jobs.id"), nullable=True)
    apply_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision_after: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PreparationApproval(Base):
    """Explicit user approval of a checked subset for later research (no AI here)."""

    __tablename__ = "preparation_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_preparation_approval_idempotency"),
        Index("ix_preparation_approval_tenant", "tenant_id", "state", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    state: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    check_id: Mapped[int] = mapped_column(ForeignKey("product_jobs.id"))
    selection_id: Mapped[int] = mapped_column(ForeignKey("product_selections.id"))
    catalog_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32))
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PreparationApprovalItem(Base):
    __tablename__ = "preparation_approval_items"
    __table_args__ = (Index("ix_preparation_item_product", "tenant_id", "product_id", "approval_id"),)
    approval_id: Mapped[int] = mapped_column(ForeignKey("preparation_approvals.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("supplier_products.id"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    product_revision: Mapped[int] = mapped_column(Integer)
    navigation_node_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    donor_emag_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_targets: Mapped[int] = mapped_column(Integer, default=0)
    mandatory_research_targets: Mapped[int] = mapped_column(Integer, default=0)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalid_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
