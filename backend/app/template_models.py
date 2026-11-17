"""Immutable, tenant-owned worktable snapshots; no AI or reference writes."""

from sqlalchemy import ForeignKey, Integer, String, JSON, LargeBinary, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, now


class ImportTemplate(Base):
    __tablename__ = "import_templates"
    __table_args__ = (Index("ix_import_template_run", "run_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String(32), default="queued")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TemplateChunk(Base):
    __tablename__ = "import_template_chunks"
    template_id: Mapped[int] = mapped_column(
        ForeignKey("import_templates.id", ondelete="CASCADE"), primary_key=True
    )
    format: Mapped[str] = mapped_column(String(4), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary(60000))
