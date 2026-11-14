"""Versioned identity and administration API; tenant authorization is server-side."""

import re
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Audit, Membership, Role, Setting, Tenant, User
from app import access_control as ac
from app.access_models import SystemAccess, AccessRole, AccessBinding, ResourceAccess
from app.security import (
    COOKIE,
    Identity,
    audit,
    csrf_for,
    database,
    digest,
    hash_password,
    identity,
    limit_login as limit_login,
    login_guard,
    require,
    revoke,
    scope,
    verify_password,
)

router = APIRouter(prefix="/api/v1")
TenantRole = Literal["tenant_admin", "processor", "reviewer", "viewer"]
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", check_fields=False)
    @classmethod
    def trimmed_name(cls, value):
        if value is None:
            return value
        if not value.strip():
            raise ValueError("A név nem lehet üres.")
        return value.strip()


class Login(Input):
    email: str | None = Field(default=None, max_length=254)
    identifier: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CreateUser(Login):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Érvénytelen email-cím.")
        return value

    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    superadmin: bool = False


class UserPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    superadmin: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)


class ProfilePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=12, max_length=128)


class TenantInput(Input):
    name: str = Field(min_length=1, max_length=120)


class TenantPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class MemberInput(Input):
    user_id: int = Field(gt=0)
    role: TenantRole


class MemberPatch(Input):
    role: TenantRole | None = None
    active: bool | None = None


class CreateMember(CreateUser):
    role: TenantRole = "processor"


class Switch(Input):
    tenant_id: int | None = Field(default=None, gt=0)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class SettingInput(Input):
    value: str = Field(max_length=1000)


def public_user(user):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "must_change_password": user.must_change_password,
        "name": user.name,
        "active": user.active,
        "superadmin": user.superadmin,
    }


def public_tenant(tenant):
    return {"id": tenant.id, "name": tenant.name, "active": tenant.active}


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Az adat már létezik vagy a kapcsolat érvénytelen.")


def page(db, statement, offset, limit, serialize):
    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    return {
        "items": [
            serialize(item)
            for item in db.scalars(statement.offset(offset).limit(limit))
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def tenant_or_404(db, tenant_id):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Az ügyfél nem található.")
    return tenant


def memberships(db, user_id):
    rows = db.execute(
        select(Membership, Tenant)
        .join(Tenant)
        .where(
            Membership.user_id == user_id,
            Membership.active.is_(True),
            Tenant.active.is_(True),
        )
        .order_by(Tenant.name)
    ).all()
    return [{"tenant_id": t.id, "name": t.name, "role": m.role} for m, t in rows]


def me_data(db, who):
    return {
        "user": public_user(who.user),
        "mfa_required": getattr(who, "mfa_required", False),
        "tenant_id": who.session.tenant_id,
        "role": who.role,
        "permissions": sorted(who.permissions),
        "memberships": memberships(db, who.user.id),
        "workspaces": ac.workspaces(db, who.user),
        "system": who.system,
        "roles": who.roles,
        "permission_sources": who.permission_sources,
        "workspace": {
            "tenant_id": who.session.tenant_id,
            "name": db.get(Tenant, who.session.tenant_id).name,
            "onboarding_state": db.get(Tenant, who.session.tenant_id).onboarding_state,
        }
        if who.session.tenant_id
        else None,
        "resource_access": resource_snapshot(db, who),
        "csrf_token": csrf_for(who.token),
        "expires_at": who.session.expires_at.isoformat() + "Z",
    }


@router.post("/auth/login", tags=["Hitelesítés"])
def login(
    body: Login, request: Request, response: Response, db: Session = Depends(database)
):
    from app.system_config import config
    from app.auth_service import complete_login
    from app.security import rate_configuration

    if not config(db, "auth")["password"]:
        raise HTTPException(403, "A jelszavas bejelentkezés le van tiltva.")
    identifier = (body.identifier or body.email or "").strip().casefold()
    if not identifier:
        raise HTTPException(422, "Felhasználónév vagy e-mail-cím szükséges.")
    user = db.scalar(
        select(User)
        .where(
            User.email == identifier
            if "@" in identifier
            else User.username == identifier
        )
        .with_for_update()
    )
    # SECURITY-01: progressive account+client-IP protection with the
    # configurable policy. Email and username share one account subject, and
    # there is no account-wide hard lockout (see security.LoginGuard).
    policy = rate_configuration.set(config(db, "security"))
    try:
        guard = login_guard(
            request, f"user:{user.id}" if user else f"identifier:{identifier}"
        )
    finally:
        rate_configuration.reset(policy)
    guard.check()
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.active:
        guard.failure()
        db.add(Audit(action="auth.login_failed", target=digest(identifier), details={}))
        db.commit()
        raise HTTPException(401, "Hibás felhasználónév, e-mail-cím vagy jelszó.")
    guard.success()
    return complete_login(db, user, request, response, "password")


@router.get("/auth/me", tags=["Hitelesítés"])
def me(who: Identity = Depends(identity), db: Session = Depends(database)):
    return me_data(db, who)


@router.post("/auth/logout", status_code=204, tags=["Hitelesítés"])
def logout(
    response: Response,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    audit(db, who, "auth.logout", who.user.id, who.session.tenant_id)
    db.delete(who.session)
    db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/tenant", tags=["Hitelesítés"])
def switch(
    body: Switch, who: Identity = Depends(identity), db: Session = Depends(database)
):
    if body.tenant_id is None:
        if not who.system:
            raise HTTPException(403, "Válassz ügyfelet.")
    elif not ac.can_access(db, who.user, body.tenant_id):
        raise HTTPException(403, "Nincs ügyfél-hozzáférés.")
    who.session.tenant_id = body.tenant_id
    audit(db, who, "auth.tenant_switch", str(body.tenant_id), body.tenant_id)
    db.commit()
    return {"tenant_id": body.tenant_id}


@router.post("/auth/password", status_code=204, tags=["Hitelesítés"])
def change_password(
    body: PasswordChange,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    db.refresh(who.user, with_for_update=True)
    if not verify_password(body.current_password, who.user.password_hash):
        raise HTTPException(400, "A jelenlegi jelszó hibás.")
    from app.system_config import password_policy

    password_policy(db, body.password)
    from app.auth_service import needs_mfa, recent

    if needs_mfa(db, who.user):
        recent(who, db)
    who.user.password_hash = hash_password(body.password)
    who.user.must_change_password = False
    audit(db, who, "user.password_change", who.user.id, who.session.tenant_id)
    revoke(db, who.user.id)
    db.commit()


@router.get("/tenants", tags=["Ügyfelek"])
def tenants(
    who: Identity = Depends(identity),
    db: Session = Depends(database),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    ac.need(who, "tenants.read")
    stmt = select(Tenant).order_by(Tenant.id)
    if not who.user.superadmin:
        account = db.get(SystemAccess, who.user.id)
        if account and "tenants.suspend" in who.permissions:
            if account.mode != "all":
                stmt = stmt.where(
                    Tenant.id.in_(account.tenants if account.mode == "selected" else [])
                )
        else:
            stmt = stmt.where(
                Tenant.id.in_(
                    [x["tenant_id"] for x in ac.workspaces(db, who.user, limit=100000)]
                )
            )
    return page(db, stmt, offset, limit, public_tenant)


@router.post("/tenants", status_code=201, tags=["Ügyfelek"])
def create_tenant(
    body: TenantInput,
    who: Identity = Depends(require("tenants.create")),
    db: Session = Depends(database),
):
    tenant = Tenant(name=body.name)
    db.add(tenant)
    db.flush()
    audit(db, who, "tenant.create", tenant.id, tenant.id)
    commit(db)
    return public_tenant(tenant)


@router.patch("/tenants/{tenant_id}", tags=["Ügyfelek"])
def edit_tenant(
    tenant_id: int,
    body: TenantPatch,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    if not who.system or not ac.system_tenant_scope(db, who.user, tenant_id):
        scope(who, tenant_id)
    if body.name is not None:
        ac.need(who, "tenants.edit")
    if body.active is not None:
        ac.need(who, "tenants.suspend")
    tenant = tenant_or_404(db, tenant_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(tenant, key, value)
    audit(
        db,
        who,
        "tenant.update",
        tenant.id,
        tenant.id,
        fields=list(body.model_fields_set),
    )
    commit(db)
    return public_tenant(tenant)


@router.get("/users", tags=["Felhasználók"])
def users(
    who: Identity = Depends(require("system.users.read")),
    db: Session = Depends(database),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    q: str = Query("", max_length=120),
):
    stmt = (
        select(User)
        .where(
            User.email.contains(q, autoescape=True)
            | User.name.contains(q, autoescape=True)
            | User.username.contains(q, autoescape=True)
        )
        .order_by(User.id)
    )
    return page(db, stmt, offset, limit, public_user)


@router.post("/users", status_code=201, tags=["Felhasználók"])
def create_user(
    body: CreateUser,
    who: Identity = Depends(require("system.users.manage")),
    db: Session = Depends(database),
):
    from app.auth_service import recent
    from app.system_config import password_policy

    recent(who, db)
    password_policy(db, body.password)
    if body.superadmin:
        ac.protected_admin(who)
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(409, "Ez az email-cím már használatban van.")
    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        superadmin=body.superadmin,
    )
    db.add(user)
    db.flush()
    if body.superadmin:
        from app.settings_api import ensure_admin_methods
        from app.system_config import config

        ensure_admin_methods(db, config(db, "auth"))
    audit(db, who, "user.create", user.id)
    commit(db)
    return public_user(user)


@router.patch("/users/{user_id}", tags=["Felhasználók"])
def edit_user(
    user_id: int,
    body: UserPatch,
    who: Identity = Depends(require("system.users.manage")),
    db: Session = Depends(database),
):
    if body.superadmin is not None:
        ac.protected_admin(who)
        from app.auth_service import recent

        recent(who, db)
    target = db.get(User, user_id)
    if target and target.superadmin:
        ac.protected_admin(who)
        from app.auth_service import recent

        recent(who, db)
    # Serialize global admin transitions to preserve a usable last Superadmin.
    db.scalar(select(Role).where(Role.code == "superadmin").with_for_update())
    user = db.get(User, user_id, populate_existing=True, with_for_update=True)
    if not user:
        raise HTTPException(404, "A felhasználó nem található.")
    if (
        user.active
        and user.superadmin
        and (body.active is False or body.superadmin is False)
    ):
        count = len(
            list(
                db.scalars(
                    select(User.id)
                    .where(User.active.is_(True), User.superadmin.is_(True))
                    .with_for_update()
                )
            )
        )
        if count <= 1:
            raise HTTPException(409, "Az utolsó aktív Superadmin nem tiltható le.")
    if body.active is False or body.superadmin is not None:
        ac.revoke_pending(db, user.email, None, who.user.id, all_contexts=True)
    before_flags = {
        "name": user.name,
        "active": user.active,
        "superadmin": user.superadmin,
    }
    for key, value in body.model_dump(exclude_none=True, exclude={"password"}).items():
        setattr(user, key, value)
    if body.password:
        from app.auth_service import recent
        from app.system_config import password_policy

        recent(who, db)
        password_policy(db, body.password)
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
    if body.active is not None or body.superadmin is not None:
        db.flush()
        from app.settings_api import ensure_admin_methods
        from app.system_config import config

        ensure_admin_methods(db, config(db, "auth"))
    if body.password or body.active is False or body.superadmin is not None:
        revoke(db, user.id)
    audit(
        db,
        who,
        "user.update",
        user.id,
        fields=list(body.model_fields_set),
        before=before_flags,
        after={"name": user.name, "active": user.active, "superadmin": user.superadmin},
    )
    commit(db)
    return public_user(user)


def member_admin(who, tenant_id):
    scope(who, tenant_id)
    if "members.manage" not in who.permissions or not who.full_resources:
        raise HTTPException(403, "Nincs felhasználókezelési jogosultság.")


@router.get("/tenants/{tenant_id}/members", tags=["Tagságok"])
def members(
    tenant_id: int,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    scope(who, tenant_id)
    ac.need(who, "members.read")
    if not who.full_resources:
        raise HTTPException(403, "Teljes ügyfél-hozzáférés szükséges.")
    tenant_or_404(db, tenant_id)
    stmt = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.tenant_id == tenant_id,
            User.name.contains(q, autoescape=True)
            | User.email.contains(q, autoescape=True),
            User.superadmin.is_(False),
            ~select(SystemAccess.user_id)
            .where(SystemAccess.user_id == User.id)
            .exists(),
        )
        .order_by(User.id)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {
        "items": [
            {**public_user(u), "role": m.role, "membership_active": m.active}
            for u, m in db.execute(stmt.offset(offset).limit(limit))
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/tenants/{tenant_id}/users", status_code=201, tags=["Tagságok"])
def create_member(
    tenant_id: int,
    body: CreateMember,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    member_admin(who, tenant_id)
    tenant_or_404(db, tenant_id)
    ac.need(who, "members.roles.manage")
    if not who.user.superadmin and not body.superadmin:
        raise HTTPException(
            409,
            "Új és meglévő fiókhoz is az e-mailes meghívást használd; a meghívott saját maga állítja be a jelszavát.",
        )
    if body.superadmin:
        raise HTTPException(403, "Ezen a végponton nem hozható létre Superadmin.")
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(
            409,
            "Az email-cím nem használható. Meglévő felhasználót Superadmin rendelhet ügyfélhez.",
        )
    from app.auth_service import recent
    from app.system_config import password_policy

    recent(who, db)
    password_policy(db, body.password)
    user = User(
        email=body.email, name=body.name, password_hash=hash_password(body.password)
    )
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, tenant_id=tenant_id, role=body.role))
    audit(db, who, "member.create_user", user.id, tenant_id, role=body.role)
    commit(db)
    return public_user(user)


@router.post("/tenants/{tenant_id}/members", status_code=201, tags=["Tagságok"])
def assign_member(
    tenant_id: int,
    body: MemberInput,
    who: Identity = Depends(require("system.users.manage")),
    db: Session = Depends(database),
):
    scope(who, tenant_id)
    tenant_or_404(db, tenant_id)
    if not db.get(User, body.user_id):
        raise HTTPException(404, "A felhasználó nem található.")
    if db.get(Membership, (tenant_id, body.user_id)):
        raise HTTPException(409, "A tagság már létezik.")
    validate_legacy_assignment(db, who, tenant_id, body.role)
    db.add(Membership(tenant_id=tenant_id, user_id=body.user_id, role=body.role))
    audit(db, who, "member.assign", body.user_id, tenant_id, role=body.role)
    commit(db)
    return {"user_id": body.user_id, "tenant_id": tenant_id, "role": body.role}


@router.patch("/tenants/{tenant_id}/members/{user_id}", tags=["Tagságok"])
def edit_member(
    tenant_id: int,
    user_id: int,
    body: MemberPatch,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    member_admin(who, tenant_id)
    if body.role is not None:
        if (
            db.scalar(
                select(func.count())
                .select_from(AccessBinding)
                .where(
                    AccessBinding.user_id == user_id,
                    AccessBinding.context == f"tenant:{tenant_id}",
                )
            )
            > 1
        ):
            raise HTTPException(
                409, "Több szerepkör esetén az új hozzáférésszerkesztőt használd."
            )
        validate_legacy_assignment(db, who, tenant_id, body.role)
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    member = db.get(
        Membership, (tenant_id, user_id), populate_existing=True, with_for_update=True
    )
    user = db.get(User, user_id)
    if not member:
        raise HTTPException(404, "A tagság nem található.")
    if ac.is_system(db, user) and not who.user.superadmin:
        raise HTTPException(403, "Superadmin tagságát csak Superadmin módosíthatja.")
    if (
        member.active
        and member.role == "tenant_admin"
        and (
            body.active is False
            or (body.role is not None and body.role != "tenant_admin")
        )
    ):
        count = len(
            list(
                db.scalars(
                    select(Membership.user_id)
                    .join(User)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.active.is_(True),
                        Membership.role == "tenant_admin",
                        User.active.is_(True),
                    )
                    .with_for_update()
                )
            )
        )
        if count <= 1:
            raise HTTPException(
                409, "Az utolsó aktív ügyféladminisztrátor nem távolítható el."
            )
    ac.revoke_pending(db, user.email, tenant_id, who.user.id)
    previous_member = {"role": member.role, "active": member.active}
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(member, key, value)
    if body.role is not None:
        sync_legacy_role(db, user_id, tenant_id, body.role)
    audit(
        db,
        who,
        "member.update",
        user_id,
        tenant_id,
        fields=list(body.model_fields_set),
        before=previous_member,
        after={"role": member.role, "active": member.active},
    )
    commit(db)
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": member.role,
        "active": member.active,
    }


def audit_target_name(db, event):
    code = event.action
    id = (
        int(event.target)
        if event.target.isascii() and event.target.isdigit() and len(event.target) < 19
        else None
    )
    if code in {"tenant.create", "tenant.update", "auth.tenant_switch"}:
        item = db.get(Tenant, id) if id is not None else None
        return (
            item.name
            if item
            else "Rendszerszint"
            if code == "auth.tenant_switch"
            else None
        )
    if code.startswith(("user.", "member.", "auth09.")) or code in {
        "auth.login",
        "auth.logout",
        "access.user_update",
        "access.system_resources",
        "access.invite_accept",
    }:
        item = db.get(User, id) if id is not None else None
        return item.name if item else None
    if code.startswith("access.role_"):
        item = db.get(AccessRole, id) if id is not None else None
        return item.name if item else None
    if code.startswith("access.invite_"):
        from app.access_models import Invitation

        item = db.get(Invitation, id) if id is not None else None
        return item.email if item else None
    return None


@router.get("/audit", tags=["Adminisztráció"])
def audits(
    who: Identity = Depends(identity),
    db: Session = Depends(database),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    stmt = select(Audit).order_by(Audit.id.desc())
    if who.session.tenant_id is None:
        ac.need(who, "system.audit.read")
        if not who.user.superadmin:
            from sqlalchemy import or_

            stmt = stmt.where(
                or_(
                    Audit.tenant_id.is_(None),
                    Audit.tenant_id.in_(
                        [
                            x["tenant_id"]
                            for x in ac.workspaces(db, who.user, limit=100000)
                        ]
                    ),
                )
            )
    else:
        ac.need(who, "audit.read")
        if not who.full_resources:
            raise HTTPException(403, "Teljes ügyfél-hozzáférés szükséges.")
        stmt = stmt.where(Audit.tenant_id == who.session.tenant_id)
    return page(
        db,
        stmt,
        offset,
        limit,
        lambda event: {
            "id": event.id,
            "actor_id": event.actor_id,
            "actor_name": db.get(User, event.actor_id).name
            if event.actor_id and db.get(User, event.actor_id)
            else "Rendszer / meghívott",
            "tenant_name": db.get(Tenant, event.tenant_id).name
            if event.tenant_id and db.get(Tenant, event.tenant_id)
            else "Rendszerszint",
            "tenant_id": event.tenant_id,
            "action": event.action,
            "target": event.target,
            "target_name": audit_target_name(db, event),
            "details": event.details,
            "created_at": event.created_at.isoformat() + "Z",
        },
    )


@router.get("/settings", tags=["Adminisztráció"])
def settings(
    who: Identity = Depends(require("system.settings.read")),
    db: Session = Depends(database),
):
    return {
        setting.key: setting.value
        for setting in db.scalars(
            select(Setting).where(Setting.key.in_(["display_name", "admin_notice"]))
        )
    }


@router.put("/settings/{key}", tags=["Adminisztráció"])
def setting(
    key: Literal["display_name", "admin_notice"],
    body: SettingInput,
    who: Identity = Depends(require("system.settings.manage")),
    db: Session = Depends(database),
):
    current = db.get(Setting, key)
    if current:
        current.value = body.value
    else:
        db.add(Setting(key=key, value=body.value))
    audit(db, who, "setting.update", key)
    commit(db)
    return {"key": key, "value": body.value}


@router.patch("/tenants/{tenant_id}/users/{user_id}", tags=["Tagságok"])
def edit_member_profile(
    tenant_id: int,
    user_id: int,
    body: ProfilePatch,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
):
    member_admin(who, tenant_id)
    user = db.get(User, user_id, populate_existing=True, with_for_update=True)
    if not user or not db.get(Membership, (tenant_id, user_id)):
        raise HTTPException(404, "A felhasználó nem található az ügyfélnél.")
    if not who.user.superadmin:
        memberships_count = len(
            list(
                db.scalars(
                    select(Membership.tenant_id)
                    .where(Membership.user_id == user_id)
                    .with_for_update()
                )
            )
        )
        if ac.is_system(db, user) or memberships_count != 1:
            raise HTTPException(
                403, "Megosztott vagy Superadmin-fiókot csak Superadmin módosíthat."
            )
        if body.password and user_id == who.user.id:
            raise HTTPException(
                403, "Saját jelszóhoz használd a Jelszó módosítása funkciót."
            )
    if body.name is not None:
        user.name = body.name
    if body.password:
        from app.auth_service import recent
        from app.system_config import password_policy

        recent(who, db)
        password_policy(db, body.password)
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
        revoke(db, user_id)
    audit(
        db,
        who,
        "member.profile_update",
        user_id,
        tenant_id,
        fields=list(body.model_fields_set),
    )
    commit(db)
    return public_user(user)


def sync_legacy_role(db, user_id, tenant_id, code):
    r = db.scalar(
        select(AccessRole)
        .where(
            AccessRole.owner.in_(["template", f"tenant:{tenant_id}"]),
            AccessRole.code == code,
        )
        .order_by(AccessRole.owner.desc())
    )
    if r:
        db.execute(
            delete(AccessBinding).where(
                AccessBinding.user_id == user_id,
                AccessBinding.context == f"tenant:{tenant_id}",
            )
        )
        db.add(
            AccessBinding(user_id=user_id, context=f"tenant:{tenant_id}", role_id=r.id)
        )
        s = db.get(ResourceAccess, (user_id, tenant_id))
        if not s:
            s = ResourceAccess(
                user_id=user_id, tenant_id=tenant_id, mode="all", companies=[], shops=[]
            )
            db.add(s)
        s.roles_managed = True


def resource_snapshot(db, who):
    r = (
        db.get(ResourceAccess, (who.user.id, who.session.tenant_id))
        if who.session.tenant_id
        else None
    )
    return {
        "full": who.full_resources,
        "companies": r.companies if r else [],
        "shops": r.shops if r else [],
    }


def validate_legacy_assignment(db, who, tenant_id, code):
    ac.need(who, "members.roles.manage")
    r = db.scalar(
        select(AccessRole)
        .where(
            AccessRole.owner.in_(["template", f"tenant:{tenant_id}"]),
            AccessRole.code == code,
        )
        .order_by(AccessRole.owner.desc())
    )
    if not r:
        raise HTTPException(422, "Ismeretlen ügyfélszerepkör.")
    ac.validate_grants(who, ac.role_permissions(db, r), False)
