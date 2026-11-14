"""Google Authorization Code + PKCE; explicit authenticated linking, never email merging."""

import base64
import hashlib
import hmac
import os
import secrets
from urllib.parse import urlencode
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import LoginSession
from app.auth_models import ExternalIdentity
from app.security import database, identity, digest
from app.auth_service import challenge, consume, recent, complete_login, event
from app.auth_api import throttle, user_for
from app.system_config import config, get_secret, store, encrypt, decrypt

router = APIRouter(prefix="/api/v1/auth/google", tags=["Google OIDC"])
FLOW_COOKIE = "adatdusito_oidc_flow"


def callback_uri():
    return (
        os.getenv("APP_ORIGIN", "https://dev.pinfo.hu").rstrip("/")
        + "/api/v1/auth/google/callback"
    )


def exchange_token(code, verifier, client, secret):
    r = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client,
            "client_secret": secret,
            "redirect_uri": callback_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def google_key(token):
    return (
        jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=10)
        .get_signing_key_from_jwt(token)
        .key
    )


def claims(token, client, nonce):
    value = jwt.decode(
        token,
        google_key(token),
        algorithms=["RS256"],
        audience=client,
        issuer=["https://accounts.google.com", "accounts.google.com"],
        options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        leeway=30,
    )
    if (
        not isinstance(value["sub"], str)
        or not value["sub"]
        or len(value["sub"]) > 255
        or not hmac.compare_digest(value["nonce"], nonce)
        or value.get("azp", client) != client
    ):
        raise ValueError("Invalid OIDC binding")
    if value.get("email") and value.get("email_verified") is not True:
        raise ValueError("Unverified email")
    return value


class Start(BaseModel):
    link: bool = False


@router.post("/start")
def start(body: Start, request: Request, db: Session = Depends(database)):
    throttle(request, db, "google-start", per_client=True)
    p = config(db, "auth")
    if not p["google"]:
        raise HTTPException(403, "A Google-bejelentkezés nincs engedélyezve.")
    who = identity(request, db) if body.link else None
    if who:
        recent(who, db)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(32)
    binding = secrets.token_urlsafe(32)
    state = challenge(
        db,
        "google",
        who.user.id if who else None,
        {
            "verifier": encrypt(verifier),
            "nonce": nonce,
            "cookie": digest(binding),
            "session": who.session.token_hash if who else None,
            "client": p["google_client_id"],
        },
    )
    db.commit()
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": p["google_client_id"],
            "redirect_uri": callback_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .decode()
            .rstrip("="),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    from fastapi.responses import JSONResponse

    response = JSONResponse({"url": url})
    response.set_cookie(
        FLOW_COOKIE,
        binding,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/v1/auth/google",
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    db: Session = Depends(database),
):
    throttle(request, db, "google-callback", per_client=True)
    p = config(db, "auth")
    if not p["google"]:
        raise HTTPException(403, "A Google-bejelentkezés nincs engedélyezve.")
    c = consume(db, state, ["google"])
    if (
        not hmac.compare_digest(
            c.payload["cookie"], digest(request.cookies.get(FLOW_COOKIE, ""))
        )
        or c.payload["client"] != p["google_client_id"]
    ):
        raise HTTPException(403, "Érvénytelen OIDC állapot vagy böngészőkötés.")
    # Commit consumption before network exchange: concurrent/replayed callbacks fail.
    c.used = True
    payload = dict(c.payload)
    link_user = c.user_id
    db.commit()
    if error or not code:
        raise HTTPException(403, "A Google-hitelesítés megszakadt.")
    try:
        tokens = exchange_token(
            code,
            decrypt(payload["verifier"]),
            p["google_client_id"],
            get_secret(db, "google.client_secret"),
        )
        identity_claims = claims(
            tokens["id_token"], p["google_client_id"], payload["nonce"]
        )
    except Exception:
        raise HTTPException(
            403, "A Google OIDC token ellenőrzése sikertelen."
        ) from None
    store(
        db,
        "google_verified",
        {
            "client_id": p["google_client_id"],
            "secret_hash": digest(get_secret(db, "google.client_secret")),
        },
    )
    subject = identity_claims["sub"]
    external = db.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.provider == "google", ExternalIdentity.subject == subject
        )
        .with_for_update()
    )
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path="/api/v1/auth/google")
    if link_user:
        user = user_for(db, link_user)
        session = db.get(LoginSession, payload["session"])
        from app.models import now
        from datetime import timedelta

        if (
            not session
            or session.user_id != user.id
            or session.expires_at <= now()
            or session.created_at
            + timedelta(hours=config(db, "security")["session_hours"])
            <= now()
            or not session.reauthenticated_at
            or session.reauthenticated_at < now() - timedelta(minutes=5)
        ):
            raise HTTPException(403, "Az összekapcsolás munkamenete lejárt.")
        from app.auth_service import needs_mfa

        if needs_mfa(db, user) and not session.mfa_verified:
            raise HTTPException(403, "Második faktor szükséges.")
        if external and external.user_id != user.id:
            raise HTTPException(409, "A Google-fiók másik felhasználóhoz kapcsolódik.")
        if not external:
            db.add(
                ExternalIdentity(user_id=user.id, provider="google", subject=subject)
            )
        event(db, user, "google_linked")
        db.commit()
        response.headers["Location"] = "/#security"
        return response
    if not external:
        raise HTTPException(
            409,
            "Ez a Google-fiók még nincs összekapcsolva. Jelentkezz be a meglévő fiókoddal, majd a Biztonság oldalon kapcsold hozzá.",
        )
    user = user_for(db, external.user_id)
    result = complete_login(db, user, request, response, "google")
    if result.get("mfa_required"):
        response.headers["Location"] = "/#mfa=" + result["mfa_token"]
    return response


@router.delete("/link")
def unlink(who=Depends(identity), db: Session = Depends(database)):
    recent(who, db)
    rows = list(
        db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.user_id == who.user.id,
                ExternalIdentity.provider == "google",
            )
        )
    )
    p = config(db, "auth")
    # Remove all Google links for this user atomically; require another enabled method.
    from app.auth_models import Passkey

    if not p["password"] and not (
        p["passkey"]
        and db.scalar(select(Passkey.id).where(Passkey.user_id == who.user.id))
    ):
        raise HTTPException(
            409, "Előbb állíts be másik használható bejelentkezési módot."
        )
    for r in rows:
        db.delete(r)
    event(db, who.user, "google_unlinked")
    db.commit()
    return {"unlinked": True}
