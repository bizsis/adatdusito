"""Validated live configuration and envelope encryption with an operator-owned key."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.models import Setting
from app.auth_models import Configuration, SecretSetting

DEFAULTS = {
    "general": {
        "display_name": "Adatdúsító",
        "system_name": "Paksi Informatika",
        "language": "hu",
        "timezone": "Europe/Budapest",
        "environment": "development",
    },
    "auth": {
        "password": True,
        "google": False,
        "passkey": False,
        "google_client_id": "",
        "registration": False,
    },
    "mfa": {"enabled": True, "required_roles": [], "passkey_mfa": True},
    "security": {
        "session_hours": 8,
        "login_attempts": 10,
        "login_window_minutes": 15,
        "password_min_length": 12,
        "invite_ttl_hours": 48,
    },
}


def config(db, group):
    row = db.get(Configuration, group)
    value = {**DEFAULTS.get(group, {}), **(row.value if row else {})}
    if group == "general":
        old = db.get(Setting, "display_name")
        if old:
            value["display_name"] = old.value
    if group == "security" and not row:
        value["invite_ttl_hours"] = max(
            1, min(168, int(os.getenv("INVITE_TTL_HOURS", "48")))
        )
    return value


def cipher():
    # No web-supplied key, no automatically generated ephemeral key, no plaintext fallback.
    try:
        key = (
            Path(os.getenv("APP_ENCRYPTION_KEY_FILE", "/run/secrets/adatdusito_key"))
            .read_bytes()
            .strip()
        )
        return Fernet(key)
    except (OSError, ValueError):
        raise HTTPException(
            503, "A külső titkosítási kulcs nincs biztonságosan konfigurálva."
        ) from None


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(
            503, "A titkosítási kulcs nem illeszkedik a tárolt titokhoz."
        ) from None


def get_secret(db, key, fallback=""):
    row = db.get(SecretSetting, key)
    return decrypt(row.ciphertext) if row else fallback


def put_secret(db, key, value):
    encoded = encrypt(value)
    row = db.get(SecretSetting, key)
    if row:
        row.ciphertext = encoded
    else:
        db.add(SecretSetting(key=key, ciphertext=encoded))


def store(db, group, value):
    row = db.get(Configuration, group)
    if row:
        row.value = value
    else:
        db.add(Configuration(key=group, value=value))


def password_policy(db, password):
    if (
        len(password) < config(db, "security")["password_min_length"]
        or len(password) > 128
    ):
        raise HTTPException(
            422,
            f"A jelszó legalább {config(db, 'security')['password_min_length']} és legfeljebb 128 karakter hosszú legyen.",
        )


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ValueError, KeyError):
        raise HTTPException(422, "Ismeretlen időzóna.") from None
    return value
