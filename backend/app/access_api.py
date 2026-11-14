"""Administrative RBAC, workspace and organization endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.security import identity, database, require, audit
from app.models import User, Tenant, Membership, Audit
from app.access_models import (
    AccessRole,
    AccessBinding,
    SystemAccess,
    PermissionException,
    ResourceAccess,
    Company,
    Webshop,
)
from app import access_control as ac

router = APIRouter(prefix="/api/v1/access", tags=["Jogosultságkezelés"])


def context(tenant_id):
    return "system" if tenant_id is None else f"tenant:{tenant_id}"


def admin(who, tenant_id, permission="members.roles.manage"):
    if tenant_id is None:
        ac.need(who, "system.roles.manage")
    else:
        if who.session.tenant_id != tenant_id:
            raise HTTPException(404, "Az ügyfél nem található.")
        ac.need(who, permission)
        if not who.full_resources:
            raise HTTPException(403, "Ehhez teljes ügyfél-hozzáférés szükséges.")


def role_dto(db, r):
    return {
        "id": r.id,
        "owner": r.owner,
        "code": r.code,
        "name": r.name,
        "permissions": sorted(
            ac.CATALOG if r.protected else ac.role_permissions(db, r) & ac.CATALOG
        ),
        "protected": r.protected,
    }


class RoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(max_length=100)


@router.get("/catalog")
def catalog(who=Depends(identity)):
    ac.need(
        who, "system.roles.read" if who.session.tenant_id is None else "members.read"
    )
    return [
        {
            "code": p,
            "level": "system" if p in ac.SYSTEM else "tenant",
            "delegatable": p not in ac.SYSTEM,
            "group": p.split(".")[0],
            "label": permission_label(p),
        }
        for p in sorted(ac.CATALOG)
    ]


@router.get("/roles")
def roles(
    tenant_id: int | None = None, who=Depends(identity), db: Session = Depends(database)
):
    admin(who, tenant_id, "members.read") if tenant_id is not None else ac.need(
        who, "system.roles.read"
    )
    owners = ["system"] if tenant_id is None else ["template", context(tenant_id)]
    items = list(
        db.scalars(
            select(AccessRole)
            .where(AccessRole.owner.in_(owners))
            .order_by(AccessRole.name)
        )
    )
    overridden = (
        {r.code for r in items if r.owner == context(tenant_id)}
        if tenant_id is not None
        else set()
    )
    return [
        role_dto(db, r)
        for r in items
        if not (r.owner == "template" and r.code in overridden)
    ]


@router.post("/roles")
def create_role(
    body: RoleInput,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    admin(who, tenant_id)
    ac.validate_grants(who, body.permissions, tenant_id is None)
    if tenant_id is not None and db.scalar(
        select(AccessRole.id).where(
            AccessRole.owner == "template", AccessRole.code == body.code
        )
    ):
        raise HTTPException(409, "Beépített szerepkörhöz a szerkesztést használd.")
    if body.code == "superadmin":
        raise HTTPException(403, "Védett szerepkör.")
    r = AccessRole(
        owner=context(tenant_id),
        code=body.code,
        name=body.name,
        permissions=body.permissions,
        managed=True,
        protected=False,
    )
    db.add(r)
    db.flush()
    audit(db, who, "access.role_create", r.id, tenant_id, after=body.model_dump())
    db.commit()
    return role_dto(db, r)


def target_role(db, id, tenant_id):
    r = db.get(AccessRole, id)
    if not r or r.owner not in (
        ["system"] if tenant_id is None else ["template", context(tenant_id)]
    ):
        raise HTTPException(404, "A szerepkör nem található.")
    if r.protected:
        raise HTTPException(403, "A Superadmin szerepkör védett.")
    return r


@router.put("/roles/{id}")
def edit_role(
    id: int,
    body: RoleInput,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    admin(who, tenant_id)
    if tenant_id is not None:
        db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if body.code == "superadmin":
        raise HTTPException(403, "Védett szerepkör.")
    r = target_role(db, id, tenant_id)
    before = role_dto(db, r)
    ac.validate_grants(who, body.permissions, tenant_id is None)
    if not who.user.superadmin and not ac.role_permissions(db, r) <= who.permissions:
        raise HTTPException(403, "A szerepkör meghaladja a delegálási jogosultságot.")
    if r.owner == "template":
        original = r
        r = AccessRole(
            owner=context(tenant_id),
            code=body.code,
            name=body.name,
            permissions=[],
            managed=True,
            protected=False,
        )
        db.add(r)
        db.flush()
        for b in db.scalars(
            select(AccessBinding).where(
                AccessBinding.context == context(tenant_id),
                AccessBinding.role_id == original.id,
            )
        ):
            db.delete(b)
            db.add(AccessBinding(user_id=b.user_id, context=b.context, role_id=r.id))
        from app.access_models import Invitation

        for invitation in db.scalars(
            select(Invitation)
            .where(Invitation.tenant_id == tenant_id, Invitation.state == "pending")
            .with_for_update()
        ):
            if original.id in invitation.role_ids:
                changed = [
                    r.id if id == original.id else id for id in invitation.role_ids
                ]
                invitation.role_ids = changed
                invitation.access = {**invitation.access, "roles": changed}
        # Old clients can still have unconverted membership rows created later.
        for m in db.scalars(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.role == (original.legacy_code or original.code),
            )
        ):
            s = db.get(ResourceAccess, (m.user_id, tenant_id))
            if not s or not s.roles_managed:
                if not s:
                    s = ResourceAccess(
                        user_id=m.user_id,
                        tenant_id=tenant_id,
                        mode="all",
                        companies=[],
                        shops=[],
                    )
                    db.add(s)
                s.roles_managed = True
                db.merge(
                    AccessBinding(
                        user_id=m.user_id, context=context(tenant_id), role_id=r.id
                    )
                )
    r.code = body.code
    r.name = body.name
    r.permissions = body.permissions
    r.managed = True
    audit(
        db,
        who,
        "access.role_update",
        r.id,
        tenant_id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return role_dto(db, r)


@router.delete("/roles/{id}")
def delete_role(
    id: int,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    admin(who, tenant_id)
    r = target_role(db, id, tenant_id)
    if r.owner == "template" or db.scalar(
        select(AccessBinding.user_id).where(AccessBinding.role_id == id).limit(1)
    ):
        raise HTTPException(
            409, "Beépített vagy használatban lévő szerepkör nem törölhető."
        )
    audit(db, who, "access.role_delete", id, tenant_id, before=role_dto(db, r))
    db.delete(r)
    db.commit()
    return {"deleted": True}


class UserAccessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[int] = Field(default_factory=list, max_length=30)
    allow: list[str] = Field(default_factory=list, max_length=100)
    deny: list[str] = Field(default_factory=list, max_length=100)
    tenant_mode: str = "none"
    tenants: list[int] = Field(default_factory=list, max_length=1000)
    resource_mode: str = "all"
    companies: list[int] = Field(default_factory=list, max_length=1000)
    shops: list[int] = Field(default_factory=list, max_length=1000)


def validate_roles(db, who, body, tenant_id):
    owners = ["system"] if tenant_id is None else ["template", context(tenant_id)]
    for id in set(body.roles):
        r = db.get(AccessRole, id)
        if not r or r.owner not in owners or r.protected:
            raise HTTPException(403, "Nem kiosztható szerepkör.")
        if (
            tenant_id is not None
            and r.owner == "template"
            and db.scalar(
                select(AccessRole.id)
                .where(
                    AccessRole.owner == context(tenant_id), AccessRole.code == r.code
                )
                .with_for_update()
            )
        ):
            raise HTTPException(409, "A szerepkör helyi ügyfélváltozatát válaszd.")
        ac.validate_grants(who, ac.role_permissions(db, r), tenant_id is None)
    ac.validate_grants(who, body.allow, tenant_id is None)
    if not set(body.deny) <= ac.CATALOG | set(ac.ALIASES):
        raise HTTPException(422, "Ismeretlen tiltás.")
    if tenant_id is not None and (set(body.deny) & ac.SYSTEM):
        raise HTTPException(403, "Rendszerjogosultság nem írható felül ügyféloldalon.")
    if body.tenant_mode not in (
        "none",
        "all",
        "selected",
    ) or body.resource_mode not in ("all", "selected"):
        raise HTTPException(422, "Ismeretlen hozzáférési mód.")
    if tenant_id is None:
        if body.tenant_mode != "none" or body.tenants:
            ac.need(who, "tenants.access.manage")
        if not who.user.superadmin:
            actor = db.get(SystemAccess, who.user.id)
            restricted = list(
                db.scalars(
                    select(ResourceAccess.tenant_id).where(
                        ResourceAccess.user_id == who.user.id,
                        ResourceAccess.mode != "all",
                    )
                )
            )
            if (
                body.tenant_mode == "all"
                and restricted
                or body.tenant_mode == "selected"
                and set(restricted) & set(body.tenants)
            ):
                raise HTTPException(
                    403,
                    "Szűkített erőforrás-hozzáférésből nem delegálható teljes ügyfél-hozzáférés.",
                )
            if body.tenant_mode == "all" and (not actor or actor.mode != "all"):
                raise HTTPException(
                    403, "Saját ügyfélhozzáférési körön túl nem delegálható hozzáférés."
                )
            if body.tenant_mode == "selected" and (
                not actor
                or actor.mode == "none"
                or actor.mode == "selected"
                and not set(body.tenants) <= set(actor.tenants)
            ):
                raise HTTPException(403, "Más ügyfélhez nem delegálható hozzáférés.")
        if set(body.tenants) - set(db.scalars(select(Tenant.id))):
            raise HTTPException(422, "Ismeretlen ügyfél.")
    for model, ids in [(Company, body.companies), (Webshop, body.shops)]:
        if ids and (
            tenant_id is None
            or set(ids)
            - set(db.scalars(select(model.id).where(model.tenant_id == tenant_id)))
        ):
            raise HTTPException(422, "Másik ügyfél erőforrása nem rendelhető hozzá.")


def apply_user_access(db, user, body, tenant_id, actor_id=None, invitation_id=None):
    ac.revoke_pending(db, user.email, tenant_id, actor_id, exclude=invitation_id)
    ctx = context(tenant_id)
    db.execute(
        delete(AccessBinding).where(
            AccessBinding.user_id == user.id, AccessBinding.context == ctx
        )
    )
    for id in set(body.roles):
        db.add(AccessBinding(user_id=user.id, context=ctx, role_id=id))
    db.execute(
        delete(PermissionException).where(
            PermissionException.user_id == user.id, PermissionException.context == ctx
        )
    )
    for code in set(body.allow) | set(body.deny):
        db.add(
            PermissionException(
                user_id=user.id,
                context=ctx,
                permission=code,
                allowed=code not in body.deny,
            )
        )
    if tenant_id is None:
        s = db.get(SystemAccess, user.id)
        if not s:
            s = SystemAccess(user_id=user.id)
            db.add(s)
        s.mode = body.tenant_mode
        s.tenants = body.tenants if body.tenant_mode == "selected" else []
    else:
        s = db.get(ResourceAccess, (user.id, tenant_id))
        if not s:
            s = ResourceAccess(user_id=user.id, tenant_id=tenant_id)
            db.add(s)
        s.mode = body.resource_mode
        s.companies = body.companies
        s.shops = body.shops
        s.roles_managed = True
        member = db.get(Membership, (tenant_id, user.id))
        if member:
            legacy = [
                db.get(AccessRole, id).legacy_code
                for id in body.roles
                if db.get(AccessRole, id)
            ]
            member.role = (
                "tenant_admin"
                if "tenant_admin" in legacy
                else "processor"
                if "processor" in legacy
                else "reviewer"
                if "reviewer" in legacy
                else "viewer"
            )


def user_state(db, user, tenant_id):
    ctx = context(tenant_id)
    scope = (
        db.get(SystemAccess, user.id)
        if tenant_id is None
        else db.get(ResourceAccess, (user.id, tenant_id))
    )
    perms, sources = ac.effective(db, user, tenant_id)
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "active": user.active,
            "membership_active": db.get(Membership, (tenant_id, user.id)).active
            if tenant_id is not None and db.get(Membership, (tenant_id, user.id))
            else None,
            "superadmin": user.superadmin,
        },
        "roles": [role_dto(db, r) for r in ac.roles_for(db, user, tenant_id)],
        "exceptions": [
            {"permission": e.permission, "allowed": e.allowed}
            for e in db.scalars(
                select(PermissionException).where(
                    PermissionException.user_id == user.id,
                    PermissionException.context == ctx,
                )
            )
        ],
        "tenant_mode": scope.mode if scope and tenant_id is None else "none",
        "tenants": scope.tenants if scope and tenant_id is None else [],
        "tenant_choices": [
            {"id": t.id, "name": t.name}
            for t in db.scalars(select(Tenant).where(Tenant.id.in_(scope.tenants)))
        ]
        if scope and tenant_id is None
        else [],
        "resource_mode": scope.mode if scope and tenant_id is not None else "all",
        "companies": scope.companies if scope and tenant_id is not None else [],
        "shops": scope.shops if scope and tenant_id is not None else [],
        "permissions": sorted(perms),
        "sources": sources,
    }


def access_target(db, who, user_id, tenant_id, write=True):
    if tenant_id is None:
        ac.need(who, "system.users.manage" if write else "system.users.read")
    else:
        admin(who, tenant_id, "members.manage" if write else "members.read")
    user = db.get(User, user_id, populate_existing=write, with_for_update=write)
    if (
        not user
        or tenant_id is not None
        and not db.get(Membership, (tenant_id, user_id))
    ):
        raise HTTPException(404, "A felhasználó nem található.")
    if tenant_id is not None and ac.is_system(db, user):
        raise HTTPException(403, "Rendszerfelhasználó nem módosítható ügyféloldalon.")
    if write and user.superadmin:
        ac.protected_admin(who)
    return user


@router.get("/users/{user_id}")
def user_access(
    user_id: int,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    user = access_target(db, who, user_id, tenant_id, False)
    return user_state(db, user, tenant_id)


@router.put("/users/{user_id}")
def edit_user_access(
    user_id: int,
    body: UserAccessInput,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    if tenant_id is not None:
        ac.need(who, "members.roles.manage")
    if tenant_id is not None:
        db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    user = access_target(db, who, user_id, tenant_id)
    if user.superadmin:
        raise HTTPException(
            403, "A védett Superadmin-hozzáférés ezen az űrlapon nem írható felül."
        )
    before = user_state(db, user, tenant_id)
    if tenant_id is None and (
        body.tenant_mode != before["tenant_mode"]
        or set(body.tenants) != set(before["tenants"])
    ):
        ac.need(who, "tenants.access.manage")
    validate_roles(db, who, body, tenant_id)
    apply_user_access(db, user, body, tenant_id, who.user.id)
    audit(
        db,
        who,
        "access.user_update",
        user.id,
        tenant_id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return user_state(db, user, tenant_id)


@router.get("/workspaces")
def workspaces(
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    who=Depends(identity),
    db: Session = Depends(database),
):
    return {"items": ac.workspaces(db, who.user, q, offset, 100), "system": who.system}


class OrgInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    company_id: int | None = None
    active: bool = True


@router.get("/companies")
def companies(who=Depends(require("companies.read")), db: Session = Depends(database)):
    tid = who.session.tenant_id
    return [
        {"id": r.id, "name": r.name, "active": r.active}
        for r in db.scalars(select(Company).where(Company.tenant_id == tid))
        if ac.resource_allowed(db, who, company=r.id)
    ]


@router.post("/companies")
def create_company(
    body: OrgInput,
    who=Depends(require("companies.manage")),
    db: Session = Depends(database),
):
    if not who.full_resources or not who.session.tenant_id:
        raise HTTPException(403, "Teljes ügyfél-hozzáférés szükséges.")
    r = Company(tenant_id=who.session.tenant_id, name=body.name, active=body.active)
    db.add(r)
    db.flush()
    audit(db, who, "access.company_create", r.id, r.tenant_id, after=body.model_dump())
    db.commit()
    return {"id": r.id, "name": r.name}


@router.get("/webshops")
def shops(who=Depends(require("webshops.read")), db: Session = Depends(database)):
    return [
        {"id": r.id, "name": r.name, "company_id": r.company_id, "active": r.active}
        for r in db.scalars(
            select(Webshop).where(Webshop.tenant_id == who.session.tenant_id)
        )
        if ac.resource_allowed(db, who, shop=r.id)
    ]


@router.post("/webshops")
def create_shop(
    body: OrgInput,
    who=Depends(require("webshops.manage")),
    db: Session = Depends(database),
):
    if not ac.resource_allowed(db, who, company=body.company_id):
        raise HTTPException(404, "A cég nem található.")
    r = Webshop(
        tenant_id=who.session.tenant_id,
        company_id=body.company_id,
        name=body.name,
        active=body.active,
    )
    db.add(r)
    db.flush()
    audit(db, who, "access.webshop_create", r.id, r.tenant_id, after=body.model_dump())
    db.commit()
    return {"id": r.id, "name": r.name}


@router.get("/history/{user_id}")
def history(
    user_id: int,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    access_target(db, who, user_id, tenant_id, False)
    return [
        {
            "action": r.action,
            "details": r.details,
            "created_at": r.created_at.isoformat() + "Z",
            "actor_id": r.actor_id,
            "actor_name": db.get(User, r.actor_id).name
            if r.actor_id and db.get(User, r.actor_id)
            else "Meghívott / rendszer",
        }
        for r in db.scalars(
            select(Audit)
            .where(
                Audit.tenant_id == tenant_id,
                Audit.target == str(user_id),
                (
                    Audit.action.like("access.%")
                    | Audit.action.in_(
                        [
                            "user.update",
                            "member.update",
                            "member.assign",
                            "member.create_user",
                        ]
                    )
                ),
            )
            .order_by(Audit.id.desc())
            .limit(100)
        )
    ]


@router.get("/companies/{id}")
def company_detail(
    id: int, who=Depends(require("companies.read")), db: Session = Depends(database)
):
    if not ac.resource_allowed(db, who, company=id):
        raise HTTPException(404, "A cég nem található.")
    c = db.get(Company, id)
    return {"id": c.id, "name": c.name, "tenant_id": c.tenant_id, "active": c.active}


@router.patch("/companies/{id}")
def company_update(
    id: int,
    body: OrgInput,
    who=Depends(require("companies.manage")),
    db: Session = Depends(database),
):
    owned = db.get(Company, id)
    if not (
        owned
        and owned.tenant_id == who.session.tenant_id
        and (who.full_resources or ac.resource_allowed(db, who, company=id))
    ):
        raise HTTPException(404, "A cég nem található.")
    c = db.get(Company, id)
    before = {"name": c.name, "active": c.active}
    c.name = body.name
    c.active = body.active
    audit(
        db,
        who,
        "access.company_update",
        id,
        c.tenant_id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return {"id": c.id, "name": c.name, "active": c.active}


@router.get("/webshops/{id}")
def shop_detail(
    id: int, who=Depends(require("webshops.read")), db: Session = Depends(database)
):
    if not ac.resource_allowed(db, who, shop=id):
        raise HTTPException(404, "A webáruház nem található.")
    s = db.get(Webshop, id)
    return {
        "id": s.id,
        "name": s.name,
        "company_id": s.company_id,
        "company_name": db.get(Company, s.company_id).name,
        "active": s.active,
    }


@router.patch("/webshops/{id}")
def shop_update(
    id: int,
    body: OrgInput,
    who=Depends(require("webshops.manage")),
    db: Session = Depends(database),
):
    owned = db.get(Webshop, id)
    if not (
        owned
        and owned.tenant_id == who.session.tenant_id
        and (who.full_resources or ac.resource_allowed(db, who, shop=id))
    ):
        raise HTTPException(404, "A webáruház nem található.")
    s = db.get(Webshop, id)
    if body.company_id not in (None, s.company_id):
        raise HTTPException(
            422, "A webáruház másik céghez helyezése külön migrációt igényel."
        )
    before = {"name": s.name, "active": s.active}
    s.name = body.name
    s.active = body.active
    audit(
        db,
        who,
        "access.webshop_update",
        id,
        s.tenant_id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return {"id": s.id, "name": s.name, "active": s.active}


def permission_label(code):
    modules = {
        "system.settings": "Rendszerbeállítások",
        "system.roles": "Rendszerszerepkörök",
        "system.users": "Rendszerfelhasználók",
        "system.audit": "Rendszeraudit",
        "tenants": "Ügyfelek",
        "members": "Munkatársak",
        "members.roles": "Munkatársi szerepkörök",
        "tenants.access": "Ügyfélhozzáférés",
        "imports": "Import",
        "exports": "Export",
        "exports.fields": "Központi exportmezők",
        "reference": "Referenciák",
        "products": "Beszállítói termékek",
        "audit": "Ügyfélaudit",
        "companies": "Cégek",
        "webshops": "Webáruházak",
    }
    prefix, action = code.rsplit(".", 1)
    actions = {
        "read": "Megtekintés",
        "create": "Létrehozás",
        "edit": "Módosítás",
        "manage": "Adminisztráció",
        "approve": "Jóváhagyás",
        "cancel": "Megszakítás",
        "invite": "Meghívás",
        "suspend": "Felfüggesztés",
        "profile": "Saját profil",
    }
    return modules.get(prefix, prefix) + " – " + actions.get(action, action)


@router.get("/system-users")
def system_users(
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    who=Depends(require("system.users.read")),
    db: Session = Depends(database),
):
    stmt = (
        select(User)
        .where(
            User.superadmin.is_(True)
            | select(SystemAccess.user_id)
            .where(SystemAccess.user_id == User.id)
            .exists()
        )
        .where(
            User.name.contains(q, autoescape=True)
            | User.email.contains(q, autoescape=True)
        )
        .order_by(User.name)
    )
    return {
        "items": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "active": u.active,
                "superadmin": u.superadmin,
            }
            for u in db.scalars(stmt.offset(offset).limit(50))
        ]
    }


@router.put("/users/{user_id}/resources")
def system_resources(
    user_id: int,
    body: UserAccessInput,
    tenant_id: int,
    who=Depends(identity),
    db: Session = Depends(database),
):
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    user = db.get(User, user_id, populate_existing=True, with_for_update=True)
    if not user:
        raise HTTPException(404, "A felhasználó nem található.")
    if ac.is_system(db, user):
        ac.protected_admin(who)
    else:
        admin(who, tenant_id, "members.manage")
    if not ac.is_system(db, user) and not db.get(Membership, (tenant_id, user_id)):
        raise HTTPException(404, "A tagság nem található.")
    if (
        not user
        or user.superadmin
        or ac.is_system(db, user)
        and not ac.can_access(db, user, tenant_id)
    ):
        raise HTTPException(
            404, "A rendszerfelhasználó vagy ügyfélhozzáférése nem található."
        )
    validate_roles(
        db,
        who,
        UserAccessInput(
            resource_mode=body.resource_mode, companies=body.companies, shops=body.shops
        ),
        tenant_id,
    )
    ac.revoke_pending(db, user.email, tenant_id, who.user.id)
    r = db.get(ResourceAccess, (user_id, tenant_id))
    before = (
        {"mode": r.mode, "companies": r.companies, "shops": r.shops}
        if r
        else {"mode": "all"}
    )
    if not r:
        r = ResourceAccess(user_id=user_id, tenant_id=tenant_id, roles_managed=False)
        db.add(r)
    r.mode = body.resource_mode
    r.companies = body.companies
    r.shops = body.shops
    audit(
        db,
        who,
        "access.system_resources",
        user_id,
        tenant_id,
        before=before,
        after={"mode": r.mode, "companies": r.companies, "shops": r.shops},
    )
    db.commit()
    return {"saved": True}


@router.get("/users/{user_id}/resources")
def system_resource_detail(
    user_id: int, tenant_id: int, who=Depends(identity), db: Session = Depends(database)
):
    ac.protected_admin(who)
    user = db.get(User, user_id)
    if (
        not user
        or user.superadmin
        or not ac.is_system(db, user)
        or not ac.can_access(db, user, tenant_id)
    ):
        raise HTTPException(
            404, "A rendszerfelhasználó ügyfélhozzáférése nem található."
        )
    r = db.get(ResourceAccess, (user_id, tenant_id))
    return {
        "mode": r.mode if r else "all",
        "companies": r.companies if r else [],
        "shops": r.shops if r else [],
        "company_options": [
            {"id": x.id, "name": x.name}
            for x in db.scalars(select(Company).where(Company.tenant_id == tenant_id))
        ],
        "shop_options": [
            {"id": x.id, "name": x.name}
            for x in db.scalars(select(Webshop).where(Webshop.tenant_id == tenant_id))
        ],
    }
