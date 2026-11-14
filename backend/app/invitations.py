"""Single-use hashed invitations; SMTP delivery never stores/logs token plaintext."""

import os
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.security import identity, database, digest, hash_password, audit
from app.models import User, Tenant, Membership, now
from app.access_models import Invitation
from app.access_api import (
    UserAccessInput,
    admin,
    validate_roles,
    apply_user_access,
    context,
)
from app import access_control as ac

router = APIRouter(prefix="/api/v1/invitations", tags=["Meghívások"])


def send_email(email, token, workspace):
    from app.mail_service import transport, mail_database

    origin = os.getenv("APP_ORIGIN", "https://dev.pinfo.hu").rstrip("/")
    transport(
        mail_database.get(),
        email,
        "Adatdúsító – munkaterületi meghívás",
        f"Meghívást kaptál ehhez a munkaterülethez: {workspace}.\n\nElfogadás: {origin}/#invite={token}\n\nA link egyszer használható, korlátozott ideig érvényes.",
    )


def authorize(who, tid):
    if tid is None:
        ac.need(who, "system.users.manage")
    else:
        admin(who, tid, "members.invite")


def visible(invite):
    state = (
        "expired"
        if invite.state == "pending" and invite.expires_at <= now()
        else invite.state
    )
    return {
        "id": invite.id,
        "email": invite.email,
        "tenant_id": invite.tenant_id,
        "role_ids": invite.role_ids,
        "state": state,
        "delivery": invite.delivery,
        "expires_at": invite.expires_at.isoformat() + "Z",
        "created_at": invite.created_at.isoformat() + "Z",
    }


def deliver(db, invite, token):
    workspace = (
        db.get(Tenant, invite.tenant_id).name
        if invite.tenant_id
        else "Paksi Informatika"
    )
    try:
        from app.mail_service import mail_database

        context_token = mail_database.set(db)
        try:
            send_email(invite.email, token, workspace)
        finally:
            mail_database.reset(context_token)
    except Exception:
        invite.delivery = "failed"
        db.commit()
        # Provider errors can contain credentials/message bodies: do not echo them.
        raise HTTPException(
            503,
            "A meghívás mentve, de az e-mail nem küldhető el. Ellenőrizd az SMTP-beállításokat, majd küldd újra.",
        )
    invite.delivery = "sent"
    db.commit()


class InvitationInput(UserAccessInput):
    email: str = Field(max_length=254)


@router.get("")
def list_invites(
    tenant_id: int | None = None, who=Depends(identity), db: Session = Depends(database)
):
    authorize(who, tenant_id)
    return [
        visible(i)
        for i in db.scalars(
            select(Invitation)
            .where(Invitation.tenant_id == tenant_id)
            .order_by(Invitation.id.desc())
            .limit(100)
        )
    ]


@router.post("")
def invite(
    body: InvitationInput,
    tenant_id: int | None = None,
    who=Depends(identity),
    db: Session = Depends(database),
):
    import re

    authorize(who, tenant_id)
    email = body.email.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Érvénytelen email-cím.")
    if tenant_id is not None:
        db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    db.scalar(select(User).where(User.email == email).with_for_update())
    validate_roles(db, who, body, tenant_id)
    ac.revoke_pending(db, email, tenant_id, who.user.id)
    token = secrets.token_urlsafe(32)
    i = Invitation(
        tenant_id=tenant_id,
        email=email,
        role_ids=body.roles,
        access=body.model_dump(exclude={"email"}),
        token_hash=digest(token),
        expires_at=now()
        + timedelta(
            hours=__import__("app.system_config", fromlist=["config"]).config(
                db, "security"
            )["invite_ttl_hours"]
        ),
        actor_id=who.user.id,
    )
    db.add(i)
    db.flush()
    audit(
        db, who, "access.invite_create", i.id, tenant_id, email=email, roles=body.roles
    )
    db.commit()
    deliver(db, i, token)
    return visible(i)


@router.post("/{id}/resend")
def resend(id: int, who=Depends(identity), db: Session = Depends(database)):
    i = db.get(Invitation, id, with_for_update=True)
    if not i:
        raise HTTPException(404, "A meghívás nem található.")
    authorize(who, i.tenant_id)
    if i.state != "pending":
        raise HTTPException(409, "Lezárt meghívás nem küldhető újra.")
    body = UserAccessInput(**i.access)
    validate_roles(db, who, body, i.tenant_id)
    token = secrets.token_urlsafe(32)
    i.token_hash = digest(token)
    i.expires_at = now() + timedelta(
        hours=__import__("app.system_config", fromlist=["config"]).config(
            db, "security"
        )["invite_ttl_hours"]
    )
    i.delivery = "pending"
    audit(db, who, "access.invite_resend", i.id, i.tenant_id)
    db.commit()
    deliver(db, i, token)
    return visible(i)


@router.post("/{id}/revoke")
def revoke_invite(id: int, who=Depends(identity), db: Session = Depends(database)):
    i = db.get(Invitation, id, with_for_update=True)
    if not i:
        raise HTTPException(404, "A meghívás nem található.")
    authorize(who, i.tenant_id)
    if i.state != "pending":
        raise HTTPException(409, "A meghívás már lezárt.")
    i.state = "revoked"
    audit(db, who, "access.invite_revoke", i.id, i.tenant_id)
    db.commit()
    return visible(i)


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)


def token_invite(db, token, locked=False):
    stmt = select(Invitation).where(Invitation.token_hash == digest(token))
    if locked:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    i = db.scalar(stmt)
    if not i or i.state != "pending" or i.expires_at <= now():
        raise HTTPException(400, "A meghívó érvénytelen, lejárt vagy már felhasznált.")
    if i.tenant_id and (
        not db.get(Tenant, i.tenant_id) or not db.get(Tenant, i.tenant_id).active
    ):
        raise HTTPException(403, "A munkaterület nem aktív.")
    return i


@router.post("/inspect")
def inspect_invitation(
    body: TokenInput, request: Request, db: Session = Depends(database)
):
    from app import api

    api.limit_login(request, "invite:" + digest(body.token))
    i = token_invite(db, body.token)
    return {
        "email": i.email,
        "workspace": db.get(Tenant, i.tenant_id).name
        if i.tenant_id
        else "Paksi Informatika",
        "expires_at": i.expires_at,
        "existing_account": db.scalar(select(User.id).where(User.email == i.email))
        is not None,
    }


class AcceptInput(TokenInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=12, max_length=128)


@router.post("/accept")
def accept(body: AcceptInput, request: Request, db: Session = Depends(database)):
    from app import api

    api.limit_login(request, "invite:" + digest(body.token))
    preview = token_invite(db, body.token)
    existing = db.scalar(select(User).where(User.email == preview.email))
    who = None
    if existing:
        who = identity(request, db)
        if who.user.id != existing.id or not existing.active:
            raise HTTPException(403, "A meghívott fiókkal kell bejelentkezni.")
    if preview.tenant_id is not None:
        db.scalar(
            select(Tenant)
            .where(Tenant.id == preview.tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    user = db.scalar(
        select(User)
        .where(User.email == preview.email)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    i = token_invite(db, body.token, True)
    if user:
        if not who or who.user.id != user.id or not user.active:
            raise HTTPException(401, "A meglévő fiókkal kell bejelentkezni.")
    else:
        if not body.name or not body.name.strip() or not body.password:
            raise HTTPException(422, "Név és saját jelszó megadása szükséges.")
        from app.system_config import password_policy

        password_policy(db, body.password)
        user = User(
            email=i.email,
            email_verified=True,
            name=body.name.strip(),
            password_hash=hash_password(body.password),
        )
        db.add(user)
        db.flush()
    if ac.is_system(db, user) and i.tenant_id is not None:
        raise HTTPException(
            409,
            "Rendszerfelhasználó ügyfélhozzáférését a rendszeradminisztráció kezeli.",
        )
    # Revalidate immutable invitation roles against current scopes, never trust IDs.
    for id in i.role_ids:
        from app.access_models import AccessRole

        r = db.get(AccessRole, id)
        if (
            not r
            or r.protected
            or r.owner
            not in (
                ["system"]
                if i.tenant_id is None
                else ["template", context(i.tenant_id)]
            )
        ):
            raise HTTPException(
                409, "A meghívás szerepköre megváltozott; új meghívás szükséges."
            )
    if i.tenant_id is not None:
        m = db.get(Membership, (i.tenant_id, user.id))
        if not m:
            m = Membership(
                tenant_id=i.tenant_id, user_id=user.id, role="viewer", active=True
            )
            db.add(m)
        else:
            m.active = True
    apply_user_access(
        db, user, UserAccessInput(**i.access), i.tenant_id, user.id, invitation_id=i.id
    )
    i.state = "accepted"
    i.accepted_by = user.id
    from types import SimpleNamespace

    audit(
        db,
        who or SimpleNamespace(user=user),
        "access.invite_accept",
        user.id,
        i.tenant_id,
        invitation_id=i.id,
    )
    db.commit()
    return {"accepted": True, "tenant_id": i.tenant_id, "login_required": who is None}
