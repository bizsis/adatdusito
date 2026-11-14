"""Additive RBAC and invitation schema; legacy identities/memberships are retained."""

from datetime import datetime
from sqlalchemy import ForeignKey, String, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, now


class AccessRole(Base):
    __tablename__ = "access_roles"
    __table_args__ = (UniqueConstraint("owner", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(
        String(48), index=True
    )  # system, template, tenant:ID
    code: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(120))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    legacy_code: Mapped[str | None] = mapped_column(String(32))
    managed: Mapped[bool] = mapped_column(default=True)
    protected: Mapped[bool] = mapped_column(default=False)


class AccessBinding(Base):
    __tablename__ = "access_bindings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    context: Mapped[str] = mapped_column(String(48), primary_key=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("access_roles.id"), primary_key=True
    )


class SystemAccess(Base):
    __tablename__ = "system_user_access"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="none")
    tenants: Mapped[list] = mapped_column(JSON, default=list)


class PermissionException(Base):
    __tablename__ = "user_permission_exceptions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    context: Mapped[str] = mapped_column(String(48), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    allowed: Mapped[bool] = mapped_column()


class ResourceAccess(Base):
    __tablename__ = "workspace_resource_access"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="all")
    companies: Mapped[list] = mapped_column(JSON, default=list)
    shops: Mapped[list] = mapped_column(JSON, default=list)
    roles_managed: Mapped[bool] = mapped_column(default=False)


class Company(Base):
    __tablename__ = "workspace_companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(default=True)


class Webshop(Base):
    __tablename__ = "workspace_webshops"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_companies.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(default=True)


class Invitation(Base):
    __tablename__ = "user_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    role_ids: Mapped[list] = mapped_column(JSON)
    access: Mapped[dict] = mapped_column(JSON, default=dict)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    delivery: Mapped[str] = mapped_column(String(16), default="pending")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
