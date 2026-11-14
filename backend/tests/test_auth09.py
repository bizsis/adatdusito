"""Real authentication ceremonies, settings secrecy and CODEX 08 boundaries."""

import base64
import hashlib
import json
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
import pytest
import pyotp
import jwt
import cbor2
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import User, LoginSession, Audit, now, Membership
from app.auth_models import (
    Configuration,
    SecretSetting,
    TotpDevice,
    RecoveryCode,
    AuthChallenge,
    Passkey,
    ExternalIdentity,
)
from app.system_config import store, decrypt
from app import mail_service, oidc_api, registration
from conftest import login


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch, tmp_path):
    path = tmp_path / "key"
    path.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", str(path))


def settings(c):
    r = c.get("/api/v1/system/settings")
    assert r.status_code == 200, r.text
    return r.json()


def update(c, group, data):
    r = c.put("/api/v1/system/settings/" + group, json=data)
    assert r.status_code == 200, r.text
    return r.json()


def enable(c, **changes):
    a = settings(c)["auth"]
    a.pop("google_secret_set")
    a.update(changes)
    return update(c, "auth", a)


def login_pending(c, email="root@example.hu"):
    r = c.post(
        "/api/v1/auth/login", json={"email": email, "password": "Test-password-2026!"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def enroll(c):
    r = c.post("/api/v1/auth/totp/setup")
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = c.post("/api/v1/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def test_username_optional_email_and_password_change_without_rbac_loss(environment):
    c, t, *_ = environment
    login(c)
    role = next(
        r["id"]
        for r in c.get("/api/v1/access/roles").json()
        if r["code"] == "system_operator"
    )
    r = c.post(
        "/api/v1/auth/system-users",
        json={
            "username": "no-email",
            "name": "Email nélkül",
            "password": "Temporary-password!",
            "roles": [role],
        },
    )
    assert r.status_code == 200, r.text
    id = r.json()["id"]
    assert r.json()["email"] is None
    c.post("/api/v1/auth/logout")
    r = c.post(
        "/api/v1/auth/login",
        json={"identifier": "no-email", "password": "Temporary-password!"},
    )
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    me = c.get("/api/v1/auth/me").json()
    assert me["user"]["must_change_password"] and me["permissions"] == []
    assert c.get("/api/v1/imports/engines").status_code == 403
    assert (
        c.post(
            "/api/v1/auth/password",
            json={
                "current_password": "Temporary-password!",
                "password": "Own-permanent-password!",
            },
        ).status_code
        == 204
    )
    r = c.post(
        "/api/v1/auth/login",
        json={"identifier": "NO-EMAIL", "password": "Own-permanent-password!"},
    )
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    me = c.get("/api/v1/auth/me").json()
    assert (
        not me["user"]["must_change_password"]
        and me["system"]
        and "imports.read" in me["permissions"]
    )
    with Session(t) as db:
        assert db.get(User, id).email is None


def test_existing_email_username_and_settings_compatibility(environment):
    c, t, *_ = environment
    login(c)
    old = c.get("/api/v1/auth/me").json()["user"]
    username = old["username"]
    assert login_pending(c)["csrf_token"]
    r = c.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": "Test-password-2026!"},
    )
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    general = settings(c)["general"] | {
        "display_name": "Teszt alkalmazás",
        "timezone": "UTC",
    }
    update(c, "general", general)
    assert c.get("/api/v1/settings").json()["display_name"] == "Teszt alkalmazás"
    assert c.get("/api/v1/auth/methods").json()["branding"]["timezone"] == "UTC"
    with Session(t) as db:
        assert db.get(User, 1).email == old["email"]
    assert (
        c.put(
            "/api/v1/system/settings/general", json=general | {"timezone": "Not/AZone"}
        ).status_code
        == 422
    )
    login(c, "admin@example.hu")
    assert c.get("/api/v1/system/settings").status_code == 403


def test_smtp_ciphertext_redaction_live_use_and_failed_save_retains_previous(
    environment, monkeypatch
):
    c, t, *_ = environment
    login(c)
    candidates = []

    class SMTP:
        def send_message(self, message):
            candidates.append(message)
            return {}

        def quit(self):
            pass

    monkeypatch.setattr(mail_service, "connect", lambda cfg, web=True: SMTP())
    value = {
        "host": "smtp.example.hu",
        "port": 465,
        "security": "tls",
        "username": "sender",
        "password": "private-smtp-secret",
        "from_email": "sender@example.hu",
        "from_name": "Teszt feladó",
    }
    update(c, "smtp", value)
    output = settings(c)
    assert (
        "private-smtp-secret" not in json.dumps(output)
        and output["smtp"]["password_set"]
    )
    assert "smtp" not in c.get("/api/v1/settings").json()
    with Session(t) as db:
        assert (
            db.get(SecretSetting, "smtp.password").ciphertext != "private-smtp-secret"
        )
        assert "private-smtp-secret" not in str(
            [r.details for r in db.scalars(select(Audit))]
        )
        mail_service.transport(db, "recipient@example.hu", "Teszt", "Body")
    assert str(candidates[-1]["From"]).startswith("Teszt feladó")

    def fail(*a, **kw):
        raise OSError("private-smtp-secret provider details")

    monkeypatch.setattr(mail_service, "connect", fail)
    r = c.put(
        "/api/v1/system/settings/smtp",
        json=value | {"host": "bad.example.hu", "password": "changed-secret"},
    )
    assert r.status_code == 422 and "private-smtp-secret" not in r.text
    assert settings(c)["smtp"]["host"] == value["host"]
    with Session(t) as db:
        assert (
            decrypt(db.get(SecretSetting, "smtp.password").ciphertext)
            == "private-smtp-secret"
        )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "0.0.0.0",
        "224.0.0.1",
        "::ffff:169.254.169.254",
    ],
)
def test_smtp_private_targets_and_metadata_are_rejected(monkeypatch, address):
    monkeypatch.setattr(
        mail_service.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (address, 465))],
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        mail_service.resolve_smtp("smtp.example.hu", 465)
    if address in ["169.254.169.254", "fe80::1", "::ffff:169.254.169.254"]:
        monkeypatch.setenv("SMTP_ALLOWED_HOSTS", "smtp.example.hu")
        with pytest.raises(HTTPException):
            mail_service.resolve_smtp("smtp.example.hu", 465)


def test_dns_mixed_targets_fail_closed_and_explicit_operator_allowlist(monkeypatch):
    monkeypatch.setattr(
        mail_service.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("8.8.8.8", 465)),
            (2, 1, 6, "", ("10.1.1.1", 465)),
        ],
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        mail_service.resolve_smtp("allowed.example.hu", 465)
    monkeypatch.setenv("SMTP_ALLOWED_HOSTS", "allowed.example.hu")
    assert mail_service.resolve_smtp("allowed.example.hu", 465) == "8.8.8.8"


def test_totp_and_recovery_single_use_no_full_session_before_second_factor(environment):
    c, t, *_ = environment
    login(c)
    secret, codes = enroll(c)
    assert len(codes) == 10 and len(set(codes)) == 10
    sec = c.get("/api/v1/auth/security").json()
    assert (
        sec["mfa_enabled"]
        and sec["recovery_remaining"] == 10
        and secret not in json.dumps(sec)
    )
    c.post("/api/v1/auth/logout")
    pending = login_pending(c)
    assert pending["mfa_required"] and "csrf_token" not in pending
    assert c.get("/api/v1/auth/me").status_code == 401
    # The setup code has already been consumed, even within the same 30-second window.
    assert (
        c.post(
            "/api/v1/auth/mfa/complete",
            json={"token": pending["mfa_token"], "code": pyotp.TOTP(secret).now()},
        ).status_code
        == 403
    )
    r = c.post(
        "/api/v1/auth/mfa/complete",
        json={"token": pending["mfa_token"], "code": codes[0]},
    )
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.get("/api/v1/auth/me").json()["user"]["superadmin"]
    assert (
        c.post(
            "/api/v1/auth/mfa/complete",
            json={"token": pending["mfa_token"], "code": codes[1]},
        ).status_code
        == 400
    )
    c.post("/api/v1/auth/logout")
    pending = login_pending(c)
    assert (
        c.post(
            "/api/v1/auth/mfa/complete",
            json={"token": pending["mfa_token"], "code": codes[0]},
        ).status_code
        == 403
    )
    with Session(t) as db:
        assert db.get(TotpDevice, 1).secret != secret
        assert codes[0] not in str(list(db.scalars(select(RecoveryCode.code_hash))))
        details = str([r.details for r in db.scalars(select(Audit))])
        assert secret not in details and codes[0] not in details
        assert db.scalar(select(Audit.id).where(Audit.action == "auth09.recovery_used"))


def test_required_mfa_restricts_existing_sessions_and_enrolls_before_new_session(
    environment,
):
    c, t, *_ = environment
    login(c)
    role = next(
        r["id"]
        for r in c.get("/api/v1/access/roles").json()
        if r["code"] == "superadmin"
    )
    update(c, "mfa", {"enabled": True, "required_roles": [role], "passkey_mfa": True})
    me = c.get("/api/v1/auth/me").json()
    assert me["mfa_required"] and me["permissions"] == []
    assert c.get("/api/v1/users").status_code == 403
    pending = login_pending(c)
    assert pending["enrollment_required"]
    r = c.post("/api/v1/auth/mfa/setup", json={"token": pending["mfa_token"]})
    assert r.status_code == 200, r.text
    code = pyotp.TOTP(r.json()["secret"]).now()
    r = c.post(
        "/api/v1/auth/mfa/complete", json={"token": pending["mfa_token"], "code": code}
    )
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.get("/api/v1/users").status_code == 200
    assert c.post("/api/v1/auth/totp/disable").status_code == 409


def test_expired_mfa_inactive_user_and_session_revocation(environment):
    c, t, *_ = environment
    login(c)
    _, codes = enroll(c)
    c.post("/api/v1/auth/logout")
    p = login_pending(c)
    with Session(t) as db:
        from app.security import digest

        db.get(AuthChallenge, digest(p["mfa_token"])).expires_at = now() - timedelta(
            seconds=1
        )
        db.commit()
    assert (
        c.post(
            "/api/v1/auth/mfa/complete",
            json={"token": p["mfa_token"], "code": codes[0]},
        ).status_code
        == 400
    )
    p = login_pending(c)
    with Session(t) as db:
        db.get(User, 1).active = False
        db.commit()
    assert (
        c.post(
            "/api/v1/auth/mfa/complete",
            json={"token": p["mfa_token"], "code": codes[0]},
        ).status_code
        == 401
    )
    login(c, "admin@example.hu")
    s = c.get("/api/v1/auth/sessions").json()[0]
    assert "token_hash" not in s
    assert c.delete("/api/v1/auth/sessions/" + s["id"]).status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401


def test_disabling_all_admin_methods_is_rejected_and_policy_requires_reauthentication(
    environment,
):
    c, t, *_ = environment
    login(c)
    a = settings(c)["auth"]
    a.pop("google_secret_set")
    a["password"] = False
    assert c.put("/api/v1/system/settings/auth", json=a).status_code == 409
    assert settings(c)["auth"]["password"]
    with Session(t) as db:
        for s in db.scalars(select(LoginSession)):
            s.reauthenticated_at = now() - timedelta(minutes=6)
        db.commit()
    assert (
        c.put(
            "/api/v1/system/settings/security", json=settings(c)["security"]
        ).status_code
        == 403
    )
    r = c.post("/api/v1/auth/reauth", json={"password": "Test-password-2026!"})
    assert r.status_code == 200
    security = settings(c)["security"] | {"session_hours": 1, "password_min_length": 20}
    update(c, "security", security)
    assert (
        c.post(
            "/api/v1/auth/system-users",
            json={"name": "N", "username": "short-pwd", "password": "Short-password!"},
        ).status_code
        == 422
    )


def b64(v):
    return base64.urlsafe_b64encode(v).decode().rstrip("=")


def registration_credential(options, key=None, origin="https://testserver", uv=True):
    key = key or ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    id = secrets.token_bytes(32)
    cose = cbor2.dumps(
        {
            1: 2,
            3: -7,
            -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }
    )
    auth = (
        hashlib.sha256(b"testserver").digest()
        + bytes([0x45 if uv else 0x41])
        + b"\0" * 4
        + b"\0" * 16
        + len(id).to_bytes(2, "big")
        + id
        + cose
    )
    client = json.dumps(
        {
            "type": "webauthn.create",
            "challenge": options["challenge"],
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode()
    attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
    return {
        "id": b64(id),
        "rawId": b64(id),
        "type": "public-key",
        "response": {
            "clientDataJSON": b64(client),
            "attestationObject": b64(attestation),
            "transports": ["internal"],
        },
        "clientExtensionResults": {},
    }, key


def assertion(
    options, credential, key, counter=1, origin="https://testserver", uv=True, user_id=1
):
    auth = (
        hashlib.sha256(b"testserver").digest()
        + bytes([5 if uv else 1])
        + counter.to_bytes(4, "big")
    )
    client = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": options["challenge"],
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode()
    signature = key.sign(
        auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
    )
    return {
        "id": credential["id"],
        "rawId": credential["id"],
        "type": "public-key",
        "response": {
            "clientDataJSON": b64(client),
            "authenticatorData": b64(auth),
            "signature": b64(signature),
            "userHandle": b64(str(user_id).encode()),
        },
        "clientExtensionResults": {},
    }


def create_passkey(c):
    enable(c, passkey=True)
    r = c.post("/api/v1/auth/passkeys/register/options")
    assert r.status_code == 200, r.text
    begin = r.json()
    credential, key = registration_credential(begin["options"])
    r = c.post(
        "/api/v1/auth/passkeys/register/verify",
        json={
            "token": begin["token"],
            "credential": credential,
            "name": "Teszt eszköz",
        },
    )
    assert r.status_code == 200, r.text
    return credential, key


def test_real_webauthn_registration_signature_uv_and_counter_verification(environment):
    c, t, *_ = environment
    login(c)
    credential, key = create_passkey(c)
    c.post("/api/v1/auth/logout")
    r = c.post("/api/v1/auth/passkeys/login/options", json={})
    begin = r.json()
    payload = {
        "token": begin["token"],
        "credential": assertion(begin["options"], credential, key),
    }
    r = c.post("/api/v1/auth/passkeys/login/verify", json=payload)
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.get("/api/v1/auth/me").json()["user"]["id"] == 1
    assert c.post("/api/v1/auth/passkeys/login/verify", json=payload).status_code == 400
    with Session(t) as db:
        assert db.scalar(select(Passkey)).sign_count == 1
    for kwargs in [
        {"counter": 1},
        {"uv": False, "counter": 2},
        {"origin": "https://evil.invalid", "counter": 2},
        {"user_id": 2, "counter": 2},
    ]:
        begin = c.post("/api/v1/auth/passkeys/login/options", json={}).json()
        r = c.post(
            "/api/v1/auth/passkeys/login/verify",
            json={
                "token": begin["token"],
                "credential": assertion(begin["options"], credential, key, **kwargs),
            },
        )
        assert r.status_code == 403, r.text


def test_passkey_cannot_disable_last_enabled_method_and_uv_policy_is_respected(
    environment,
):
    c, t, *_ = environment
    login(c)
    credential, key = create_passkey(c)
    enable(c, password=False, passkey=True)
    p = c.get("/api/v1/auth/security").json()["passkeys"][0]
    assert c.delete("/api/v1/auth/passkeys/" + str(p["id"])).status_code == 409
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"identifier": "root@example.hu", "password": "Test-password-2026!"},
        ).status_code
        == 403
    )
    with Session(t) as db:
        store(db, "mfa", {"enabled": True, "required_roles": [], "passkey_mfa": False})
        db.commit()
    c.post("/api/v1/auth/logout")
    begin = c.post("/api/v1/auth/passkeys/login/options", json={}).json()
    r = c.post(
        "/api/v1/auth/passkeys/login/verify",
        json={
            "token": begin["token"],
            "credential": assertion(begin["options"], credential, key),
        },
    )
    assert (
        r.status_code == 200
    )  # no MFA requirement, but the authenticator still verifies UV


def test_registration_verifies_email_and_never_grants_unlimited_trial(
    environment, monkeypatch
):
    c, t, *_ = environment
    login(c)
    with Session(t) as db:
        store(
            db,
            "auth",
            {
                "password": True,
                "google": False,
                "passkey": False,
                "google_client_id": "",
                "registration": True,
            },
        )
        db.commit()
    sent = []
    monkeypatch.setattr(registration, "quota", lambda request: None)
    monkeypatch.setattr(
        registration, "transport", lambda db, email, subject, text: sent.append(text)
    )
    c.post("/api/v1/auth/logout")
    r = c.post(
        "/api/v1/auth/register",
        json={
            "name": "Új Ügyfél",
            "email": "new-tenant@example.hu",
            "password": "Own-new-tenant-password!",
            "workspace": "Új munkaterület",
        },
    )
    assert r.status_code == 200, r.text
    assert "token" not in r.text and len(sent) == 1
    token = sent[0].split("#register=")[1].split()[0]
    with Session(t) as db:
        assert not db.scalar(
            select(User.id).where(User.email == "new-tenant@example.hu")
        )
    assert (
        c.post("/api/v1/auth/register/confirm", json={"token": token}).status_code
        == 200
    )
    assert (
        c.post("/api/v1/auth/register/confirm", json={"token": token}).status_code
        == 400
    )
    r = c.post(
        "/api/v1/auth/login",
        json={"email": "new-tenant@example.hu", "password": "Own-new-tenant-password!"},
    )
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    me = c.get("/api/v1/auth/me").json()
    assert (
        "imports.create" not in me["permissions"]
        and me["workspace"]["onboarding_state"] == "pending_subscription"
    )
    assert (
        c.post(
            "/api/v1/imports/suppliers", json={"name": "No quota bypass"}
        ).status_code
        == 403
    )
    with Session(t) as db:
        u = db.scalar(select(User).where(User.email == "new-tenant@example.hu"))
        assert u.email_verified
        assert db.get(Membership, (me["tenant_id"], u.id)).role == "tenant_admin"


@pytest.fixture
def google_signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(oidc_api, "google_key", lambda token: key.public_key())

    def sign(nonce, **claims):
        value = {
            "iss": "https://accounts.google.com",
            "aud": "test.apps.googleusercontent.com",
            "sub": "subject-root",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": nonce,
            "email": "root@example.hu",
            "email_verified": True,
        } | claims
        return jwt.encode(value, key, algorithm="RS256")

    return sign


def google_begin(c, t, signer, monkeypatch, link=False, **claims):
    r = c.post("/api/v1/auth/google/start", json={"link": link})
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    state = q["state"][0]
    assert q["code_challenge_method"] == ["S256"]
    with Session(t) as db:
        from app.security import digest

        payload = db.get(AuthChallenge, digest(state)).payload
        assert (
            b64(hashlib.sha256(decrypt(payload["verifier"]).encode()).digest())
            == q["code_challenge"][0]
        )
    monkeypatch.setattr(
        oidc_api,
        "exchange_token",
        lambda code, verifier, client, secret: {
            "id_token": signer(payload["nonce"], **claims)
        },
    )
    return state


def test_google_oidc_explicit_linking_state_nonce_and_no_email_merge(
    environment, monkeypatch, google_signer
):
    c, t, *_ = environment
    login(c)
    enable(
        c,
        google=True,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="private-google-secret",
    )
    # Matching email without an existing subject mapping does not merge accounts.
    state = google_begin(c, t, google_signer, monkeypatch)
    r = c.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert r.status_code == 409, r.text
    with Session(t) as db:
        assert not db.scalar(select(ExternalIdentity.id))
    state = google_begin(c, t, google_signer, monkeypatch, link=True)
    r = c.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert (
        c.get(
            "/api/v1/auth/google/callback", params={"state": state, "code": "code"}
        ).status_code
        == 400
    )
    c.post("/api/v1/auth/logout")
    state = google_begin(c, t, google_signer, monkeypatch)
    r = c.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert c.get("/api/v1/auth/me").json()["user"]["id"] == 1
    with Session(t) as db:
        assert "private-google-secret" not in str(
            [a.details for a in db.scalars(select(Audit))]
        )


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "wrong"},
        {"aud": "other-client"},
        {"iss": "https://evil.invalid"},
        {"exp": 1},
        {"azp": "other-client"},
        {"email_verified": False},
    ],
)
def test_google_invalid_signed_claims_rejected(
    environment, monkeypatch, google_signer, claims
):
    c, t, *_ = environment
    login(c)
    enable(
        c,
        google=True,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="secret",
    )
    state = google_begin(c, t, google_signer, monkeypatch, **claims)
    r = c.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert r.status_code == 403, r.text


def test_google_state_bound_to_initiating_browser(
    environment, monkeypatch, google_signer
):
    c, t, *_ = environment
    login(c)
    enable(
        c,
        google=True,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="secret",
    )
    state = google_begin(c, t, google_signer, monkeypatch)
    c.cookies.delete(oidc_api.FLOW_COOKIE)
    assert (
        c.get(
            "/api/v1/auth/google/callback", params={"state": state, "code": "code"}
        ).status_code
        == 403
    )


def test_tls_smtp_real_authentication_and_test_letter(
    environment, monkeypatch, tmp_path
):
    import socketserver
    import ssl
    import threading
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timezone

    c, t, *_ = environment
    login(c)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / "smtp.pem"
    key_file = tmp_path / "smtp.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    messages = []

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 test TLS SMTP\r\n")
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                verb = line.split(b" ", 1)[0].strip().upper()
                if verb == b"EHLO":
                    self.wfile.write(b"250-test\r\n250 AUTH PLAIN\r\n")
                elif verb == b"AUTH":
                    value = base64.b64decode(line.strip().split()[-1])
                    self.wfile.write(
                        b"235 authenticated\r\n"
                        if value == b"\x00sender\x00secret-test-password"
                        else b"535 rejected\r\n"
                    )
                elif verb == b"DATA":
                    self.wfile.write(b"354 data\r\n")
                    body = []
                    while True:
                        part = self.rfile.readline()
                        if part in [b".\r\n", b""]:
                            break
                        body.append(part)
                    messages.append(b"".join(body))
                    self.wfile.write(b"250 accepted\r\n")
                elif verb == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    class Server(socketserver.TCPServer):
        def get_request(self):
            sock, address = super().get_request()
            return context.wrap_socket(sock, server_side=True), address

    server = Server(("127.0.0.1", 0), SMTP)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_context = ssl.create_default_context
    monkeypatch.setattr(
        mail_service.ssl,
        "create_default_context",
        lambda: original_context(cafile=cert_file),
    )
    monkeypatch.setenv("SMTP_ALLOWED_HOSTS", "localhost")
    value = {
        "host": "localhost",
        "port": server.server_address[1],
        "security": "tls",
        "username": "sender",
        "password": "secret-test-password",
        "from_email": "sender@example.hu",
        "from_name": "Teszt",
    }
    try:
        update(c, "smtp", value)
        r = c.post(
            "/api/v1/system/settings/smtp/test",
            json={"recipient": "recipient@example.hu"},
        )
        assert r.status_code == 200, r.text
        assert (
            r.json()["encrypted"]
            and r.json()["authentication"] == "success"
            and r.json()["smtp_accepted"]
            and messages
        )
        r = c.put(
            "/api/v1/system/settings/smtp", json=value | {"password": "wrong-password"}
        )
        assert r.status_code == 422 and "hitelesítési" in r.text
        with Session(t) as db:
            assert (
                decrypt(db.get(SecretSetting, "smtp.password").ciphertext)
                == "secret-test-password"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mfa_recovery_needs_independent_two_factor_admin_approval(environment):
    c, t, *_ = environment
    login(c)
    _, root_codes = enroll(c)
    r = c.post(
        "/api/v1/users",
        json={
            "name": "Második Root",
            "email": "root2@example.hu",
            "password": "Second-root-password!",
            "superadmin": True,
        },
    )
    assert r.status_code == 201, r.text
    second_id = r.json()["id"]
    r = c.post(
        "/api/v1/auth/admin-recovery/request",
        json={
            "user_id": 3,
            "reason": "Ellenőrzött személyazonosság, ügyfélszolgálati jegy ABC-123.",
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["approval_token"]
    assert (
        c.post("/api/v1/auth/admin-recovery/approve", json={"token": token}).status_code
        == 403
    )
    c.post("/api/v1/auth/logout")
    login(c, "root2@example.hu", "Second-root-password!")
    enroll(c)
    assert (
        c.post("/api/v1/auth/admin-recovery/approve", json={"token": token}).status_code
        == 200
    )
    assert (
        c.post("/api/v1/auth/admin-recovery/approve", json={"token": token}).status_code
        == 400
    )
    with Session(t) as db:
        assert db.get(User, 3).mfa_reset_required
        assert not db.scalar(
            select(LoginSession.token_hash).where(LoginSession.user_id == 3)
        )
        record = db.scalar(
            select(Audit).where(Audit.action == "auth09.recovery_approved")
        )
        assert record.actor_id == second_id and record.details["requester_id"] == 1
    c.post("/api/v1/auth/logout")
    p = login_pending(c, "processor@example.hu")
    assert p["mfa_required"] and p["enrollment_required"]


def test_settings_secrets_read_without_key_and_failure_never_overwrites(
    environment, monkeypatch
):
    c, t, *_ = environment
    login(c)
    from app.system_config import put_secret

    with Session(t) as db:
        store(
            db,
            "smtp",
            {
                "host": "example.hu",
                "port": 465,
                "security": "tls",
                "username": "u",
                "from_email": "s@example.hu",
                "from_name": "S",
            },
        )
        put_secret(db, "smtp.password", "persisted-secret")
        db.commit()
    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", "/nonexistent/key")
    assert settings(c)["smtp"]["password_set"]
    body = settings(c)["smtp"]
    body.pop("password_set")
    body.pop("source")
    body["password"] = "new-secret"
    assert c.put("/api/v1/system/settings/smtp", json=body).status_code == 503
    with Session(t) as db:
        assert db.get(Configuration, "smtp").value["host"] == "example.hu"


def test_mandatory_mfa_follows_local_role_template_copy(environment):
    c, t, *_ = environment
    login(c)
    processor = next(r for r in settings(c)["roles"] if r["name"] == "Adatfeldolgozó")
    update(
        c,
        "mfa",
        {"enabled": True, "required_roles": [processor["id"]], "passkey_mfa": True},
    )
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 200
    role = next(
        r
        for r in c.get("/api/v1/access/roles?tenant_id=1").json()
        if r["code"] == "processor"
    )
    r = c.put(
        f"/api/v1/access/roles/{role['id']}?tenant_id=1",
        json={
            "code": role["code"],
            "name": "Helyi adatfeldolgozó",
            "permissions": role["permissions"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] in settings(c)["mfa"]["required_roles"]
    c.post("/api/v1/auth/logout")
    pending = login_pending(c, "processor@example.hu")
    assert pending["mfa_required"]


def test_oauth_code_and_state_are_redacted_from_access_log():
    import logging
    from app.auth_logging import OAuthAccessFilter

    record = logging.LogRecord(
        "uvicorn.access",
        20,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        (
            "peer",
            "GET",
            "/api/v1/auth/google/callback?code=private-code&state=private-state",
            "1.1",
            303,
        ),
        None,
    )
    assert OAuthAccessFilter().filter(record)
    assert (
        "private-code" not in record.getMessage()
        and "private-state" not in record.getMessage()
    )


def test_new_product_view_keeps_tenant_boundary_and_resource_restriction(environment):
    from app.import_models import Supplier, ImportRun, SupplierProduct
    from app.access_models import ResourceAccess

    c, t, *_ = environment
    with Session(t) as db:
        db.add_all(
            [
                Supplier(id=1, tenant_id=1, name="Saját beszállító"),
                Supplier(id=2, tenant_id=2, name="Másik beszállító"),
            ]
        )
        db.flush()
        db.add_all(
            [
                ImportRun(
                    id=i,
                    tenant_id=i,
                    supplier_id=i,
                    filename="test.csv",
                    state="completed",
                )
                for i in [1, 2]
            ]
        )
        db.flush()
        db.add_all(
            [
                SupplierProduct(
                    id=i,
                    tenant_id=i,
                    supplier_id=i,
                    identity_key="sku" + str(i),
                    data={"sku": "000" + str(i), "name": "Termék"},
                    last_run_id=i,
                    last_line=1,
                )
                for i in [1, 2]
            ]
        )
        db.commit()
    login(c, "processor@example.hu")
    r = c.get("/api/v1/workspace/products")
    assert r.status_code == 200, r.text
    assert [x["supplier_name"] for x in r.json()["items"]] == ["Saját beszállító"]
    assert r.json()["items"][0]["fields"]["sku"] == "0001"
    with Session(t) as db:
        db.add(
            ResourceAccess(
                user_id=3, tenant_id=1, mode="selected", companies=[], shops=[]
            )
        )
        db.commit()
    assert c.get("/api/v1/workspace/products").status_code == 403


def test_passkey_reauth_does_not_bypass_required_totp_policy(environment):
    c, t, *_ = environment
    login(c)
    credential, key = create_passkey(c)
    root_role = next(
        r["id"]
        for r in c.get("/api/v1/access/roles").json()
        if r["code"] == "superadmin"
    )
    update(
        c, "mfa", {"enabled": True, "required_roles": [root_role], "passkey_mfa": False}
    )
    assert c.get("/api/v1/auth/me").json()["mfa_required"]
    begin = c.post("/api/v1/auth/passkeys/login/options", json={"reauth": True}).json()
    r = c.post(
        "/api/v1/auth/passkeys/login/verify",
        json={
            "token": begin["token"],
            "credential": assertion(begin["options"], credential, key),
        },
    )
    assert r.status_code == 403, r.text
    assert c.get("/api/v1/users").status_code == 403


def test_cross_origin_webauthn_registration_is_rejected(environment):
    c, *_ = environment
    login(c)
    enable(c, passkey=True)
    begin = c.post("/api/v1/auth/passkeys/register/options").json()
    credential, _ = registration_credential(begin["options"])
    client = json.loads(
        base64.urlsafe_b64decode(credential["response"]["clientDataJSON"] + "==")
    )
    client["crossOrigin"] = True
    credential["response"]["clientDataJSON"] = b64(json.dumps(client).encode())
    r = c.post(
        "/api/v1/auth/passkeys/register/verify",
        json={
            "token": begin["token"],
            "credential": credential,
            "name": "Tiltott iframe",
        },
    )
    assert r.status_code == 403


def test_google_forged_signature_does_not_authenticate(
    environment, monkeypatch, google_signer
):
    c, t, *_ = environment
    login(c)
    enable(
        c,
        google=True,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="secret",
    )
    state = google_begin(c, t, google_signer, monkeypatch)
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(oidc_api, "google_key", lambda token: wrong.public_key())
    assert (
        c.get(
            "/api/v1/auth/google/callback", params={"state": state, "code": "code"}
        ).status_code
        == 403
    )


def test_hidden_smtp_password_cannot_be_redirected_to_another_server(
    environment, monkeypatch
):
    c, *_ = environment
    login(c)
    calls = []

    class SMTP:
        def quit(self):
            pass

    monkeypatch.setattr(
        mail_service, "connect", lambda cfg, web=True: calls.append(cfg) or SMTP()
    )
    value = {
        "host": "smtp.example.hu",
        "port": 465,
        "security": "tls",
        "username": "sender",
        "password": "hidden-existing-password",
        "from_email": "sender@example.hu",
        "from_name": "S",
    }
    update(c, "smtp", value)
    value.pop("password")
    value["host"] = "attacker.example.hu"
    assert (
        c.post("/api/v1/system/settings/smtp/test", json={"config": value}).status_code
        == 422
    )
    assert len(calls) == 1


def test_system_accounts_do_not_inherit_tenant_role_mfa_requirements(environment):
    from app.access_models import SystemAccess, AccessBinding

    c, t, *_ = environment
    login(c)
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 200
    template = {
        r["code"]: r["id"] for r in c.get("/api/v1/access/roles?tenant_id=1").json()
    }
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": None}).status_code == 200
    system = {r["code"]: r["id"] for r in c.get("/api/v1/access/roles").json()}
    with Session(t) as db:
        db.add(Membership(tenant_id=1, user_id=1, role="tenant_admin", active=True))
        db.add(SystemAccess(user_id=3, mode="none", tenants=[]))
        db.add(
            AccessBinding(
                user_id=3, context="system", role_id=system["system_operator"]
            )
        )
        db.commit()
    update(
        c,
        "mfa",
        {
            "enabled": True,
            "required_roles": [template["tenant_admin"], template["processor"]],
            "passkey_mfa": True,
        },
    )
    assert c.get("/api/v1/auth/me").json()["mfa_required"] is False
    c.post("/api/v1/auth/logout")
    assert "csrf_token" in login_pending(c, "processor@example.hu")


def test_session_list_honors_shortened_lifetime(environment):
    c, t, *_ = environment
    login(c)
    with Session(t) as db:
        db.add(
            LoginSession(
                token_hash="expired-by-policy",
                user_id=1,
                tenant_id=None,
                created_at=now() - timedelta(hours=2),
                expires_at=now() + timedelta(hours=5),
            )
        )
        db.commit()
    update(c, "security", settings(c)["security"] | {"session_hours": 1})
    rows = c.get("/api/v1/auth/sessions").json()
    assert len(rows) == 1 and rows[0]["current"]


def test_stale_root_session_cannot_mint_new_protected_administrator(environment):
    c, t, *_ = environment
    login(c)
    with Session(t) as db:
        for session in db.scalars(select(LoginSession)):
            session.reauthenticated_at = now() - timedelta(minutes=6)
        db.commit()
    assert c.patch("/api/v1/users/3", json={"superadmin": True}).status_code == 403
    with Session(t) as db:
        assert not db.get(User, 3).superadmin


def test_mandatory_totp_can_be_replaced_atomically_with_recovery_proof(environment):
    c, t, *_ = environment
    login(c)
    old_secret, old_codes = enroll(c)
    role = next(
        r["id"]
        for r in c.get("/api/v1/access/roles").json()
        if r["code"] == "superadmin"
    )
    update(c, "mfa", {"enabled": True, "required_roles": [role], "passkey_mfa": True})
    assert (
        c.post(
            "/api/v1/auth/reauth",
            json={"password": "Test-password-2026!", "code": old_codes[0]},
        ).status_code
        == 200
    )
    setup = c.post("/api/v1/auth/totp/setup").json()
    assert setup["setup_token"]
    with Session(t) as db:
        assert decrypt(db.get(TotpDevice, 1).secret) == old_secret
    assert (
        c.post(
            "/api/v1/auth/totp/confirm",
            json={"code": "invalid-code", "setup_token": setup["setup_token"]},
        ).status_code
        == 403
    )
    with Session(t) as db:
        assert decrypt(db.get(TotpDevice, 1).secret) == old_secret
    setup = c.post("/api/v1/auth/totp/setup").json()
    r = c.post(
        "/api/v1/auth/totp/confirm",
        json={
            "code": pyotp.TOTP(setup["secret"]).now(),
            "setup_token": setup["setup_token"],
        },
    )
    assert r.status_code == 200, r.text
    assert not set(r.json()["recovery_codes"]) & set(old_codes)
    assert c.get("/api/v1/auth/me").json()["mfa_required"] is False
    assert c.post("/api/v1/auth/totp/disable").status_code == 409
    with Session(t) as db:
        assert decrypt(db.get(TotpDevice, 1).secret) == setup["secret"]
