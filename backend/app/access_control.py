"""One authorization service for legacy APIs, custom RBAC and resource scopes."""

from sqlalchemy import select
from fastapi import HTTPException
from app.models import Tenant, Membership, RolePermission, ROLE_PERMISSIONS
from app.access_models import (
    AccessRole,
    AccessBinding,
    SystemAccess,
    ResourceAccess,
    PermissionException,
    Company,
    Webshop,
)

# Legacy grants expand forward; reverse aliases require every constituent grant.
ALIASES = {
    "system.manage": {
        "system.settings.read",
        "system.settings.manage",
        "reference.manage",
    },
    "users.manage": {"system.users.read", "system.users.manage"},
    "tenants.manage": {
        "tenants.read",
        "tenants.create",
        "tenants.edit",
        "tenants.suspend",
        "tenants.access.manage",
    },
    "tenant.manage": {"tenants.edit"},
    "exports.manage": {"exports.fields.manage", "exports.read"},
    "imports.manage": {
        "imports.manage",
        "imports.read",
        "imports.create",
        "imports.approve",
        "imports.cancel",
        "products.read",
    },
}
SYSTEM = {
    "system.settings.read",
    "system.settings.manage",
    "system.roles.read",
    "system.roles.manage",
    "system.users.read",
    "system.users.manage",
    "system.audit.read",
    "tenants.create",
    "tenants.suspend",
    "tenants.access.manage",
    "exports.fields.manage",
    "reference.manage",
}
TENANT = {
    "tenants.read",
    "tenants.edit",
    "members.read",
    "members.invite",
    "members.manage",
    "members.roles.manage",
    "imports.read",
    "imports.create",
    "imports.manage",
    "imports.approve",
    "imports.cancel",
    "products.read",
    "exports.read",
    "exports.profile",
    "reference.read",
    "audit.read",
    "companies.read",
    "companies.manage",
    "webshops.read",
    "webshops.manage",
}
CATALOG = SYSTEM | TENANT | {"tenants.read"}


def expand(codes, legacy=False):
    result = set(codes)
    for code in list(result):
        if code != "imports.manage" or legacy:
            result |= ALIASES.get(code, set())
    if legacy and "members.manage" in result:
        result |= {
            "members.read",
            "members.invite",
            "members.roles.manage",
            "companies.read",
            "companies.manage",
            "webshops.read",
            "webshops.manage",
        }
    if legacy and "reference.read" in result:
        result.add("tenants.read")
    if legacy and "imports.read" in result:
        result |= {"products.read", "exports.read"}  # old read API contract
    return result


def defaults():
    alltenant = expand(ROLE_PERMISSIONS["tenant_admin"], True) | TENANT
    return {
        "system_admin": {
            "tenants.read",
            "tenants.create",
            "tenants.edit",
            "system.users.read",
            "system.settings.read",
            "system.roles.read",
        }
        | alltenant,
        "system_operator": expand(ROLE_PERMISSIONS["processor"], True),
        "system_auditor": {
            "system.users.read",
            "system.roles.read",
            "system.settings.read",
            "system.audit.read",
            "tenants.read",
            "reference.read",
            "products.read",
            "imports.read",
            "exports.read",
            "audit.read",
        },
        "viewer": {
            "reference.read",
            "products.read",
            "imports.read",
            "exports.read",
            "companies.read",
            "webshops.read",
        },
    }


def seed_access(connection):
    for code in CATALOG:
        from app.models import Permission

        if not connection.scalar(
            select(Permission.code).where(Permission.code == code)
        ):
            connection.execute(Permission.__table__.insert().values(code=code))
    for code in ["superadmin", "tenant_admin", "processor", "reviewer"]:
        connection.execute(
            AccessRole.__table__.insert().values(
                owner="system" if code == "superadmin" else "template",
                code=code,
                name={
                    "superadmin": "Superadmin",
                    "tenant_admin": "Ügyféladminisztrátor",
                    "processor": "Adatfeldolgozó",
                    "reviewer": "Ellenőr",
                }[code],
                permissions=[],
                legacy_code=code,
                managed=False,
                protected=code == "superadmin",
            )
        )
    for code, permissions in defaults().items():
        connection.execute(
            AccessRole.__table__.insert().values(
                owner="template" if code == "viewer" else "system",
                code=code,
                name={
                    "system_admin": "Rendszeradminisztrátor",
                    "system_operator": "Rendszeroperátor",
                    "system_auditor": "Rendszerellenőr",
                    "viewer": "Megtekintő",
                }[code],
                permissions=sorted(permissions),
                legacy_code=None,
                managed=True,
                protected=False,
            )
        )


def is_system(db, user):
    return user.superadmin or db.get(SystemAccess, user.id) is not None


def can_access(db, user, tenant_id):
    t = db.get(Tenant, tenant_id)
    if not t or not t.active or not user.active:
        return False
    if user.superadmin:
        return True
    account = db.get(SystemAccess, user.id)
    if account:
        return (
            account.mode == "all"
            or account.mode == "selected"
            and tenant_id in account.tenants
        )
    m = db.get(Membership, (tenant_id, user.id))
    return bool(m and m.active)


def role_permissions(db, role):
    if role.managed:
        return expand(role.permissions)
    return expand(
        db.scalars(
            select(RolePermission.permission).where(
                RolePermission.role == role.legacy_code
            )
        ),
        True,
    ) | (TENANT if role.legacy_code == "tenant_admin" else set())


def roles_for(db, user, tenant_id):
    context = "system" if is_system(db, user) else f"tenant:{tenant_id}"
    roles = list(
        db.scalars(
            select(AccessRole)
            .join(AccessBinding, AccessBinding.role_id == AccessRole.id)
            .where(AccessBinding.user_id == user.id, AccessBinding.context == context)
        )
    )
    if context == "system":
        return roles
    m = db.get(Membership, (tenant_id, user.id)) if tenant_id else None
    resource = db.get(ResourceAccess, (user.id, tenant_id)) if tenant_id else None
    if m and m.active and not (resource and resource.roles_managed):
        legacy = db.scalar(
            select(AccessRole)
            .where(
                AccessRole.code == m.role, AccessRole.owner.in_(["template", context])
            )
            .order_by(AccessRole.owner.desc())
        )
        if legacy and legacy not in roles:
            roles.append(legacy)
    return roles


def effective(db, user, tenant_id):
    if not user.active:
        return set(), {}
    if user.superadmin:
        codes = (
            CATALOG | {p for ps in ROLE_PERMISSIONS.values() for p in ps} | set(ALIASES)
        )
        return set(codes), {
            c: {"roles": ["Superadmin"], "exception": None, "allowed": True}
            for c in codes
        }
    if tenant_id is not None and not can_access(db, user, tenant_id):
        return set(), {}
    system = is_system(db, user)
    if tenant_id is None and not system:
        return set(), {}
    roles = roles_for(db, user, tenant_id)
    sources = {}
    granted = set()
    for r in roles:
        for p in role_permissions(db, r):
            granted.add(p)
            sources.setdefault(p, {"roles": [], "exception": None})["roles"].append(
                r.name
            )
    context = "system" if system else f"tenant:{tenant_id}"
    denies = set()
    for x in db.scalars(
        select(PermissionException).where(
            PermissionException.user_id == user.id,
            PermissionException.context == context,
        )
    ):
        affected = expand([x.permission])
        if x.allowed:
            granted |= affected
        else:
            denies |= affected
        for p in affected:
            sources.setdefault(p, {"roles": []})["exception"] = (
                "allow" if x.allowed else "deny"
            )
    granted -= denies
    resource = (
        db.get(ResourceAccess, (user.id, tenant_id)) if tenant_id is not None else None
    )
    if resource and resource.mode != "all":
        unavailable = {
            p
            for p in granted
            if p.startswith(("imports.", "products.", "members."))
            or p in {"exports.profile", "audit.read"}
            or (not system and p == "tenants.edit")
        }
        granted -= unavailable
        for p in unavailable:
            sources.setdefault(p, {"roles": [], "exception": None})["scope"] = (
                "requires_full_workspace"
            )
    if not system:
        granted -= SYSTEM | {
            "users.manage",
            "system.manage",
            "tenants.manage",
            "exports.manage",
        }
    # Keep safe backward aliases; a fine-grained deny must remove its broad alias.
    for old, new in ALIASES.items():
        if new <= granted and old not in denies:
            granted.add(old)
        elif old != "imports.manage":
            granted.discard(old)
    for p in sources:
        sources[p]["allowed"] = p in granted
    return granted, sources


def workspaces(db, user, q="", offset=0, limit=50):
    stmt = (
        select(Tenant)
        .where(Tenant.active.is_(True), Tenant.name.contains(q, autoescape=True))
        .order_by(Tenant.name, Tenant.id)
    )
    if not user.superadmin:
        system = db.get(SystemAccess, user.id)
        if system:
            if system.mode != "all":
                stmt = stmt.where(
                    Tenant.id.in_(system.tenants if system.mode == "selected" else [])
                )
        else:
            stmt = stmt.join(Membership).where(
                Membership.user_id == user.id, Membership.active.is_(True)
            )
    return [
        {"tenant_id": t.id, "name": t.name}
        for t in db.scalars(stmt.offset(offset).limit(limit))
    ]


def full_resources(db, who):
    if who.user.superadmin:
        return True
    tid = who.session.tenant_id
    if tid is None:
        return True
    r = db.get(ResourceAccess, (who.user.id, tid))
    return r is None or r.mode == "all"


def resource_allowed(db, who, company=None, shop=None):
    tid = who.session.tenant_id
    if not tid or not can_access(db, who.user, tid):
        return False
    if shop:
        s = db.get(Webshop, shop)
        if not s or s.tenant_id != tid or not s.active:
            return False
        company = s.company_id
    c = db.get(Company, company) if company else None
    if not c or c.tenant_id != tid or not c.active:
        return False
    if full_resources(db, who):
        return True
    r = db.get(ResourceAccess, (who.user.id, tid))
    return shop in r.shops if shop is not None else company in r.companies


def need(who, permission):
    if permission not in who.permissions:
        raise HTTPException(403, "Nincs jogosultság ehhez a művelethez.")


def protected_admin(who):
    if not who.user.superadmin:
        raise HTTPException(
            403, "Ez a védett művelet csak Superadmin számára engedélyezett."
        )


def validate_grants(who, permissions, system=False):
    expanded = expand(permissions)
    if not expanded <= CATALOG | set(ALIASES) | {"tenant.manage", "members.manage"}:
        raise HTTPException(422, "Ismeretlen vagy még nem megvalósított jogosultság.")
    if not system and expanded & SYSTEM:
        raise HTTPException(403, "Rendszerjogosultság nem delegálható ügyfélhez.")
    if not who.user.superadmin and not expanded <= who.permissions:
        raise HTTPException(403, "Csak saját, delegálható jogosultság osztható ki.")


def system_tenant_scope(db, user, tenant_id):
    if user.superadmin:
        return db.get(Tenant, tenant_id) is not None
    account = db.get(SystemAccess, user.id)
    return bool(
        account
        and (
            account.mode == "all"
            or account.mode == "selected"
            and tenant_id in account.tenants
        )
    )


def revoke_pending(
    db, email, tenant_id, actor_id=None, exclude=None, all_contexts=False
):
    """An older invitation must never restore access revoked by an administrator."""
    from app.access_models import Invitation
    from app.models import Audit

    stmt = select(Invitation).where(
        Invitation.email == email, Invitation.state == "pending"
    )
    if not all_contexts:
        stmt = stmt.where(Invitation.tenant_id == tenant_id)
    if exclude is not None:
        stmt = stmt.where(Invitation.id != exclude)
    for i in db.scalars(stmt.with_for_update()):
        i.state = "revoked"
        db.add(
            Audit(
                actor_id=actor_id,
                tenant_id=i.tenant_id,
                action="access.invite_superseded",
                target=str(i.id),
                details={"reason": "newer_access_decision"},
            )
        )
