"""Authentication methods and encrypted configuration; no reference metadata."""

from datetime import datetime
from sqlalchemy import (
    String,
    ForeignKey,
    JSON,
    DateTime,
    Text,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, now


class Configuration(Base):
    __tablename__ = "system_configuration"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class SecretSetting(Base):
    __tablename__ = "system_secret_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used: Mapped[bool] = mapped_column(default=False)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Passkey(Base):
    __tablename__ = "user_passkeys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rp_id: Mapped[str] = mapped_column(String(253))
    credential_id: Mapped[str] = mapped_column(Text)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class TotpDevice(Base):
    __tablename__ = "user_totp_devices"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False)
    last_counter: Mapped[int] = mapped_column(BigInteger, default=-1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RecoveryCode(Base):
    __tablename__ = "user_recovery_codes"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
