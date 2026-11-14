"""Application-owned supplier import records. No reference catalog writes."""

from datetime import datetime
from sqlalchemy import ForeignKey, String, JSON, LargeBinary, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, now


class Supplier(Base):
    __tablename__ = "import_suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))


class ImportProfile(Base):
    __tablename__ = "import_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("import_suppliers.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(default=1)
    config: Mapped[dict] = mapped_column(JSON)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("import_suppliers.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("import_profiles.id"))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    cursor: Mapped[int] = mapped_column(default=0)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    task_token: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ImportChunk(Base):
    __tablename__ = "import_file_chunks"
    run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary(60000))


class ImportRow(Base):
    __tablename__ = "import_rows"
    run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), primary_key=True)
    line: Mapped[int] = mapped_column(primary_key=True)
    raw: Mapped[list] = mapped_column(JSON)
    normalized: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(24))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_products.id"))


class SupplierProduct(Base):
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "identity_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("import_suppliers.id"), index=True
    )
    identity_key: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    last_run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", use_alter=True, name="fk_product_last_run")
    )
    last_line: Mapped[int] = mapped_column()


class ImportChange(Base):
    __tablename__ = "import_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), index=True)
    line: Mapped[int] = mapped_column()
    delta: Mapped[dict] = mapped_column(JSON)


class StoreEngine(Base):
    __tablename__ = "store_engines"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(default=1)
    fields: Mapped[list] = mapped_column(JSON, default=list)


class StoreProfile(Base):
    __tablename__ = "store_export_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    engine_key: Mapped[str] = mapped_column(ForeignKey("store_engines.key"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(default=1)
    fields: Mapped[list] = mapped_column(JSON)
    rules: Mapped[dict] = mapped_column(
        JSON, default=lambda: {"negative_stock": "zero"}
    )
