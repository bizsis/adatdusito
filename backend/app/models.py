"""Application-only schema. Reference tables must never join this metadata."""

from datetime import datetime, timezone
from sqlalchemy import (
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    BigInteger,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Role(Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"), primary_key=True)
    permission: Mapped[str] = mapped_column(
        ForeignKey("permissions.code"), primary_key=True
    )


class Membership(Base):
    __tablename__ = "memberships"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Setting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


ROLE_LABELS = {
    "superadmin": "Superadmin",
    "tenant_admin": "Ügyféladminisztrátor",
    "processor": "Adatfeldolgozó",
    "reviewer": "Ellenőrző",
}
ROLE_PERMISSIONS = {
    "superadmin": [
        "system.manage",
        "tenants.manage",
        "users.manage",
        "reference.read",
        "audit.read",
    ],
    "tenant_admin": ["tenant.manage", "members.manage", "reference.read", "audit.read"],
    "processor": ["reference.read"],
    "reviewer": ["reference.read"],
}


def seed_roles(connection):
    connection.execute(
        Role.__table__.insert(),
        [{"code": code, "label": label} for code, label in ROLE_LABELS.items()],
    )
    connection.execute(
        Permission.__table__.insert(),
        [
            {"code": code}
            for code in sorted(
                {p for perms in ROLE_PERMISSIONS.values() for p in perms}
            )
        ],
    )
    connection.execute(
        RolePermission.__table__.insert(),
        [
            {"role": role, "permission": permission}
            for role, perms in ROLE_PERMISSIONS.items()
            for permission in perms
        ],
    )


class ReferenceSource(Base):
    __tablename__ = "reference_sources"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)


class ReferenceObservation(Base):
    __tablename__ = "reference_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(
        ForeignKey("reference_sources.key"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    evidence_url: Mapped[str] = mapped_column(String(1000))
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    source_category_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    canonical_emag_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    mapping_status: Mapped[str] = mapped_column(String(32), default="pending")
    evidence_kind: Mapped[str | None] = mapped_column(String(48), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class CategoryOverride(Base):
    """Shared operator choices; category/parameter records stay in their source."""

    __tablename__ = "category_overrides"
    node_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(48), default="emag_marketplace")
    source_category_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    override_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    disable_automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    source_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# Stable common IDs are allocated by the single catalog importer, above the
# legacy eMAG range and below JavaScript's exact-integer limit. Versions contain
# memberships/placements; shared definitions and values are stored only once.


class CatalogVersion(Base):
    __tablename__ = "catalog_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), default="building")
    phase: Mapped[str] = mapped_column(String(24), default="categories")
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    source_state: Mapped[dict] = mapped_column(JSON)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class CatalogCategory(Base):
    __tablename__ = "catalog_categories"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class CatalogNode(Base):
    __tablename__ = "catalog_category_nodes"
    version_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_versions.id"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_categories.id"), nullable=True, index=True
    )
    data: Mapped[dict] = mapped_column(JSON)


class CatalogParameter(Base):
    __tablename__ = "catalog_parameters"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CatalogLink(Base):
    __tablename__ = "catalog_category_parameters"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(160), unique=True)


class CatalogLinkEntry(Base):
    __tablename__ = "catalog_category_parameter_entries"
    version_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_versions.id"), primary_key=True
    )
    link_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_category_parameters.id"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_categories.id"), index=True
    )
    parameter_id: Mapped[int] = mapped_column(ForeignKey("catalog_parameters.id"))
    name: Mapped[str] = mapped_column(String(255))
    emag_parameter_id: Mapped[int] = mapped_column(Integer)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_mandatory: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_filter: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_new_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    __table_args__ = (
        Index(
            "ix_catalog_entry_category",
            "version_id",
            "category_id",
            "display_order",
            "link_id",
        ),
    )


class CatalogValue(Base):
    __tablename__ = "catalog_parameter_values"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("catalog_parameters.id"))
    value_text: Mapped[str] = mapped_column(Text)


class CatalogSourceMapping(Base):
    __tablename__ = "catalog_source_mappings"
    version_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_versions.id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_id: Mapped[int] = mapped_column(BigInteger)
    context_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    source_json: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True, deferred=True
    )
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        Index(
            "ix_catalog_mapping_values", "version_id", "kind", "context_id", "target_id"
        ),
        Index("ix_catalog_mapping_targets", "version_id", "kind", "target_id"),
        Index(
            "ix_catalog_mapping_external",
            "version_id",
            "kind",
            "source_key",
            "external_id",
        ),
    )
