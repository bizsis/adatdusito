"""KNOWLEDGE-01 tables (migration 0014). They link and consolidate existing records
(reference_products, supplier_products) - they are not a second product store."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, now

BigId = BigInteger().with_variant(Integer, "sqlite")


class KnowledgeProduct(Base):
    """One real-world product: a cluster of records from several sources."""

    __tablename__ = "knowledge_products"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | merged
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_products.id"), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeIdentity(Base):
    """Identity keys of a cluster: valid GTIN, brand+MPN, brand+name (folded)."""

    __tablename__ = "knowledge_identities"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_knowledge_identity"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    knowledge_product_id: Mapped[int] = mapped_column(ForeignKey("knowledge_products.id"),
                                                      index=True)
    kind: Mapped[str] = mapped_column(String(16))  # gtin | mpn | brand_name
    value: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeLink(Base):
    """Membership of one source record in a cluster, with how it was matched."""

    __tablename__ = "knowledge_links"
    __table_args__ = (UniqueConstraint("member_kind", "member_id", name="uq_knowledge_member"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    knowledge_product_id: Mapped[int] = mapped_column(ForeignKey("knowledge_products.id"),
                                                      index=True)
    member_kind: Mapped[str] = mapped_column(String(24))  # reference_product | supplier_product
    member_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(ForeignKey("reference_product_sources.id"))
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    method: Mapped[str] = mapped_column(String(16))  # gtin | mpn | brand_name | new | manual
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeObservation(Base):
    """One value claim of one source record for one attribute (history kept)."""

    __tablename__ = "knowledge_observations"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    knowledge_product_id: Mapped[int] = mapped_column(ForeignKey("knowledge_products.id"),
                                                      index=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("knowledge_links.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("reference_product_sources.id"))
    attribute_key: Mapped[str] = mapped_column(String(191))
    attribute_label: Mapped[str] = mapped_column(String(255))
    value_raw: Mapped[str] = mapped_column(String(1000))
    value_norm: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin: Mapped[str] = mapped_column(String(24))  # reference | tenant | approved_correction
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    current: Mapped[bool] = mapped_column(default=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeValue(Base):
    """Consolidated value of one attribute of one cluster."""

    __tablename__ = "knowledge_values"
    __table_args__ = (
        UniqueConstraint("knowledge_product_id", "attribute_key", name="uq_knowledge_value"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    knowledge_product_id: Mapped[int] = mapped_column(ForeignKey("knowledge_products.id"),
                                                      index=True)
    attribute_key: Mapped[str] = mapped_column(String(191))
    attribute_label: Mapped[str] = mapped_column(String(255))
    value_norm: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    value_display: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # candidate | conflict | verified | rejected (never verified by agreement alone)
    status: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    support_sources: Mapped[int] = mapped_column(Integer, default=0)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    verification_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_values: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeConflict(Base):
    __tablename__ = "knowledge_conflicts"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    value_id: Mapped[int] = mapped_column(ForeignKey("knowledge_values.id"), index=True)
    knowledge_product_id: Mapped[int] = mapped_column(ForeignKey("knowledge_products.id"))
    attribute_key: Mapped[str] = mapped_column(String(191))
    kind: Mapped[str] = mapped_column(String(24))  # values_differ | verified_challenged
    candidates: Mapped[list] = mapped_column(JSON)  # [{value_norm, display, sources, confidence}]
    state: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    resolution: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeEvent(Base):
    """Append-only trail of every knowledge change and decision."""

    __tablename__ = "knowledge_events"
    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    knowledge_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_products.id"), nullable=True, index=True)
    value_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    link_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
