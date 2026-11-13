"""Application-only schema. Reference tables must never join this metadata."""

from datetime import datetime, timezone
from sqlalchemy import Integer, Boolean, DateTime, ForeignKey, JSON, String, Text
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
