"""Versioned identity and administration API; tenant authorization is server-side."""

import os
import re
import secrets
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Audit, LoginSession, Membership, Role, Setting, Tenant, User, now
from app.security import (
    COOKIE,
    Identity,
    audit,
    csrf_for,
    database,
    digest,
    hash_password,
    identity,
    limit_login,
    require,
    revoke,
    scope,
    verify_password,
)

router = APIRouter(prefix="/api/v1")
TenantRole = Literal["tenant_admin", "processor", "reviewer"]
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
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Érvénytelen email-cím.")
        return value

    @field_validator("password", mode="before")
    @classmethod
    def preserve_password(cls, value):
        # Password whitespace is significant.
        return value


class CreateUser(Login):
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
        "tenant_id": who.session.tenant_id,
        "role": who.role,
        "permissions": sorted(who.permissions),
        "memberships": memberships(db, who.user.id),
        "csrf_token": csrf_for(who.token),
        "expires_at": who.session.expires_at.isoformat() + "Z",
    }


@router.post("/auth/login", tags=["Hitelesítés"])
def login(
    body: Login, request: Request, response: Response, db: Session = Depends(database)
):
    limit_login(request, body.email)
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.active:
        db.add(Audit(action="auth.login_failed", target=digest(body.email), details={}))
        db.commit()
        raise HTTPException(401, "Hibás email-cím vagy jelszó.")
    choices = memberships(db, user.id)
    tenant_id = (
        choices[0]["tenant_id"] if len(choices) == 1 and not user.superadmin else None
    )
    token = secrets.token_hex(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
    db.add(
        LoginSession(
            token_hash=digest(token),
            user_id=user.id,
            tenant_id=tenant_id,
            expires_at=now() + timedelta(hours=8),
        )
    )
    db.add(
        Audit(
            actor_id=user.id,
            tenant_id=tenant_id,
            action="auth.login",
            target=str(user.id),
            details={},
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=28800,
        secure=os.getenv("COOKIE_SECURE", "true").lower() != "false",
        httponly=True,
        samesite="strict",
        path="/",
    )
    return {"csrf_token": csrf_for(token)}


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
        if not who.user.superadmin:
            raise HTTPException(403, "Válassz ügyfelet.")
    else:
        tenant = tenant_or_404(db, body.tenant_id)
        membership = db.get(Membership, (tenant.id, who.user.id))
        if not tenant.active or (
            not who.user.superadmin and (not membership or not membership.active)
        ):
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
    who.user.password_hash = hash_password(body.password)
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
    stmt = select(Tenant).order_by(Tenant.id)
    if not who.user.superadmin:
        stmt = stmt.join(Membership).where(
            Membership.user_id == who.user.id,
            Membership.active.is_(True),
            Tenant.active.is_(True),
        )
    return page(db, stmt, offset, limit, public_tenant)


@router.post("/tenants", status_code=201, tags=["Ügyfelek"])
def create_tenant(
    body: TenantInput,
    who: Identity = Depends(require("tenants.manage")),
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
    scope(who, tenant_id)
    if not who.user.superadmin and "tenant.manage" not in who.permissions:
        raise HTTPException(403, "Nincs ügyféladminisztrátori jogosultság.")
    if body.active is not None and not who.user.superadmin:
        raise HTTPException(403, "Az ügyfél állapotát csak Superadmin módosíthatja.")
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
    who: Identity = Depends(require("users.manage")),
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
        )
        .order_by(User.id)
    )
    return page(db, stmt, offset, limit, public_user)


@router.post("/users", status_code=201, tags=["Felhasználók"])
def create_user(
    body: CreateUser,
    who: Identity = Depends(require("users.manage")),
    db: Session = Depends(database),
):
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
    audit(db, who, "user.create", user.id)
    commit(db)
    return public_user(user)


@router.patch("/users/{user_id}", tags=["Felhasználók"])
def edit_user(
    user_id: int,
    body: UserPatch,
    who: Identity = Depends(require("users.manage")),
    db: Session = Depends(database),
):
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
    for key, value in body.model_dump(exclude_none=True, exclude={"password"}).items():
        setattr(user, key, value)
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.password or body.active is False or body.superadmin is not None:
        revoke(db, user.id)
    audit(db, who, "user.update", user.id, fields=list(body.model_fields_set))
    commit(db)
    return public_user(user)


def member_admin(who, tenant_id):
    scope(who, tenant_id)
    if not who.user.superadmin and "members.manage" not in who.permissions:
        raise HTTPException(403, "Nincs felhasználókezelési jogosultság.")


@router.get("/tenants/{tenant_id}/members", tags=["Tagságok"])
def members(
    tenant_id: int,
    who: Identity = Depends(identity),
    db: Session = Depends(database),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    member_admin(who, tenant_id)
    tenant_or_404(db, tenant_id)
    stmt = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == tenant_id)
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
    if body.superadmin:
        raise HTTPException(403, "Ezen a végponton nem hozható létre Superadmin.")
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(
            409,
            "Az email-cím nem használható. Meglévő felhasználót Superadmin rendelhet ügyfélhez.",
        )
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
    who: Identity = Depends(require("users.manage")),
    db: Session = Depends(database),
):
    tenant_or_404(db, tenant_id)
    if not db.get(User, body.user_id):
        raise HTTPException(404, "A felhasználó nem található.")
    if db.get(Membership, (tenant_id, body.user_id)):
        raise HTTPException(409, "A tagság már létezik.")
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
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    member = db.get(
        Membership, (tenant_id, user_id), populate_existing=True, with_for_update=True
    )
    user = db.get(User, user_id)
    if not member:
        raise HTTPException(404, "A tagság nem található.")
    if user.superadmin and not who.user.superadmin:
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
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(member, key, value)
    audit(
        db, who, "member.update", user_id, tenant_id, fields=list(body.model_fields_set)
    )
    commit(db)
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": member.role,
        "active": member.active,
    }


@router.get("/audit", tags=["Adminisztráció"])
def audits(
    who: Identity = Depends(require("audit.read")),
    db: Session = Depends(database),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    stmt = select(Audit).order_by(Audit.id.desc())
    if not who.user.superadmin:
        stmt = stmt.where(Audit.tenant_id == who.session.tenant_id)
    return page(
        db,
        stmt,
        offset,
        limit,
        lambda event: {
            "id": event.id,
            "actor_id": event.actor_id,
            "tenant_id": event.tenant_id,
            "action": event.action,
            "target": event.target,
            "details": event.details,
            "created_at": event.created_at.isoformat() + "Z",
        },
    )


@router.get("/settings", tags=["Adminisztráció"])
def settings(
    who: Identity = Depends(require("system.manage")), db: Session = Depends(database)
):
    return {setting.key: setting.value for setting in db.scalars(select(Setting))}


@router.put("/settings/{key}", tags=["Adminisztráció"])
def setting(
    key: Literal["display_name", "admin_notice"],
    body: SettingInput,
    who: Identity = Depends(require("system.manage")),
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
        if user.superadmin or memberships_count != 1:
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
        user.password_hash = hash_password(body.password)
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
