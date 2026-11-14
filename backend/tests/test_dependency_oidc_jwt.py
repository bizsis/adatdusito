"""DEPENDENCY-01: Google OIDC ID-token verification through the real PyJWT path.

Unlike test_auth09 (which stubs oidc_api.google_key), these tests resolve the
signing key with the real jwt.PyJWKClient from a JWKS document; only the
network fetch is replaced. They pin the security behaviour that the PyJWT
upgrade must keep (issuer, audience, expiry, nonce, azp, algorithm
allow-list, key selection) and the fixes it must bring (crit header,
non-Base64URL signature segments, non-string iss).
"""

import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import oidc_api

CLIENT = "test.apps.googleusercontent.com"
NONCE = "nonce-value-1234567890"


@pytest.fixture(scope="module")
def keys():
    primary = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return primary, other


@pytest.fixture
def jwks(monkeypatch, keys):
    primary, other = keys

    def jwk(key, kid):
        value = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        return value | {"kid": kid, "alg": "RS256", "use": "sig"}

    document = {"keys": [jwk(primary, "google-1"), jwk(other, "google-2")]}
    fetched = []

    def fetch(self):
        assert self.uri == "https://www.googleapis.com/oauth2/v3/certs"
        fetched.append(self.uri)
        return document

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch)
    return fetched


def claims(**changes):
    now = int(time.time())
    value = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "sub": "subject-1",
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
        "email": "user@example.hu",
        "email_verified": True,
    }
    value.update(changes)
    return {k: v for k, v in value.items() if v is not None}


def token(key, kid="google-1", headers=None, **changes):
    return jwt.encode(
        claims(**changes), key, algorithm="RS256", headers={"kid": kid, **(headers or {})}
    )


def verify(value):
    return oidc_api.claims(value, CLIENT, NONCE)


def test_valid_google_token_verifies_with_jwks_key(jwks, keys):
    result = verify(token(keys[0]))
    assert result["sub"] == "subject-1" and result["email_verified"] is True
    assert jwks  # the key really came from the JWKS document
    assert verify(token(keys[1], kid="google-2"))["sub"] == "subject-1"
    assert verify(token(keys[0], iss="accounts.google.com"))["sub"] == "subject-1"


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "other.apps.googleusercontent.com"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 120},  # beyond the 30 s leeway
        {"nonce": "different-nonce"},
        {"nonce": None},
        {"sub": None},
        {"iat": None},
        {"azp": "other-client"},
        {"email_verified": False},
        {"sub": "x" * 256},
    ],
    ids=["aud", "iss", "expired", "nonce", "no-nonce", "no-sub", "no-iat", "azp", "unverified-email", "long-sub"],
)
def test_invalid_claims_are_rejected(jwks, keys, changes):
    with pytest.raises((jwt.PyJWTError, ValueError)):
        verify(token(keys[0], **changes))


def test_expiry_leeway_is_kept(jwks, keys):
    assert verify(token(keys[0], exp=int(time.time()) - 10))


def test_wrong_key_unknown_kid_and_kid_swap_are_rejected(jwks, keys):
    primary, other = keys
    with pytest.raises(jwt.PyJWTError):
        verify(token(other, kid="google-1"))  # signed by a key that is not google-1
    with pytest.raises(jwt.PyJWTError):
        verify(token(primary, kid="unknown"))


def test_algorithm_confusion_and_none_are_rejected(jwks, keys):
    public_pem = keys[0].public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "kid": "google-1"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(claims()).encode()).rstrip(b"=")
    import hashlib
    import hmac

    signature = base64.urlsafe_b64encode(
        hmac.new(public_pem, header + b"." + body, hashlib.sha256).digest()
    ).rstrip(b"=")
    with pytest.raises(jwt.PyJWTError):
        verify((header + b"." + body + b"." + signature).decode())
    unsigned = jwt.encode(claims(), None, algorithm="none", headers={"kid": "google-1"})
    with pytest.raises(jwt.PyJWTError):
        verify(unsigned)


def test_unknown_critical_header_is_rejected(jwks, keys):
    """RFC 7515 4.1.11; accepted by PyJWT <= 2.11 (GHSA-752w-5fwx-jx9f)."""
    value = token(keys[0], headers={"crit": ["x-unknown-extension"], "x-unknown-extension": True})
    with pytest.raises(jwt.PyJWTError):
        verify(value)


def test_non_base64url_signature_characters_are_rejected(jwks, keys):
    """Accepted by PyJWT < 2.14 (GHSA-hxm8-2xgr-2p9m)."""
    with pytest.raises(jwt.PyJWTError):
        verify(token(keys[0]) + "!!!!")


def test_non_string_issuer_is_rejected(jwks, keys):
    with pytest.raises((jwt.PyJWTError, ValueError, TypeError)):
        verify(token(keys[0], iss=["https://accounts.google.com"]))


def test_tampered_payload_is_rejected(jwks, keys):
    header, body, signature = token(keys[0]).split(".")
    forged = base64.urlsafe_b64encode(json.dumps(claims(sub="admin")).encode()).rstrip(b"=").decode()
    with pytest.raises(jwt.PyJWTError):
        verify(".".join([header, forged, signature]))
