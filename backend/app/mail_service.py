"""Live SMTP configuration, pinned DNS, verified TLS, redacted transport failures."""

import os
import ipaddress
import socket
import smtplib
import ssl
import time
from contextvars import ContextVar
from email.message import EmailMessage
from email.utils import formataddr
from fastapi import HTTPException
from app.auth_models import Configuration
from app.system_config import get_secret

mail_database = ContextVar("mail_database", default=None)


def smtp_config(db=None):
    row = db.get(Configuration, "smtp") if db is not None else None
    if row:
        return {
            **row.value,
            "password": get_secret(db, "smtp.password"),
            "source": "database",
        }
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(
            os.getenv(
                "SMTP_PORT", "465" if os.getenv("SMTP_SECURITY") == "tls" else "587"
            )
        ),
        "security": os.getenv("SMTP_SECURITY", "starttls"),
        "username": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("SMTP_FROM", ""),
        "from_name": os.getenv("SMTP_FROM_NAME", "Adatdúsító"),
        "source": "environment",
    }


def public_smtp(db):
    c = smtp_config(db)
    return {k: v for k, v in c.items() if k != "password"} | {
        "password_set": bool(c["password"])
    }


def resolve_smtp(host, port, all_addresses=False):
    if not host or any(x in host for x in "/\\@\r\n\x00"):
        raise HTTPException(422, "Érvénytelen SMTP-kiszolgáló.")
    try:
        addresses = list(
            dict.fromkeys(
                x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
    except OSError:
        raise HTTPException(422, "Az SMTP-kiszolgáló címe nem oldható fel.") from None
    allowed = host.casefold() in {
        x.strip().casefold()
        for x in os.getenv("SMTP_ALLOWED_HOSTS", "").split(",")
        if x.strip()
    }
    for value in addresses:
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if isinstance(ip, ipaddress.IPv6Address) and any(
            ip in ipaddress.ip_network(n)
            for n in ["64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"]
        ):
            raise HTTPException(
                422, "Az SMTP-cél fordított IPv6 átjárócím, nem engedélyezett."
            )
        # Metadata/link-local destinations can never be enabled from the web.
        if (
            ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or (not ip.is_global and not allowed)
        ):
            raise HTTPException(
                422,
                "Az SMTP-cél belső vagy tiltott hálózati cím; üzemeltetői engedély szükséges.",
            )
    if not addresses:
        raise HTTPException(422, "Nincs használható SMTP-cím.")
    return addresses[:8] if all_addresses else addresses[0]


def connect(c, web=True):
    if c["security"] not in ("tls", "starttls") and web:
        raise HTTPException(422, "Webes konfigurációhoz TLS vagy STARTTLS kötelező.")
    addresses = (
        resolve_smtp(c["host"], c["port"], all_addresses=True) if web else [c["host"]]
    )

    def pinned_socket(port, timeout):
        deadline = time.monotonic() + timeout
        last_error = None
        for address in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return socket.create_connection((address, port), remaining)
            except OSError as error:
                last_error = error
        if last_error:
            raise last_error
        raise TimeoutError("SMTP connection timeout")

    class PinnedSMTP(smtplib.SMTP):
        def _get_socket(self, host, port, timeout):
            return pinned_socket(port, timeout)

    class PinnedSSL(smtplib.SMTP_SSL):
        def _get_socket(self, host, port, timeout):
            raw = pinned_socket(port, timeout)
            try:
                return self.context.wrap_socket(raw, server_hostname=host)
            except Exception:
                raw.close()
                raise

    cls = PinnedSSL if c["security"] == "tls" else PinnedSMTP
    smtp = cls(
        c["host"],
        c["port"],
        timeout=10,
        **({"context": ssl.create_default_context()} if cls is PinnedSSL else {}),
    )
    try:
        smtp.ehlo()
        if c["security"] == "starttls":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if c["username"]:
            smtp.login(c["username"], c["password"])
        return smtp
    except Exception:
        smtp.close()
        raise


def transport(db, recipient=None, subject="", text="", candidate=None):
    c = candidate or smtp_config(db)
    if not c["host"] or not c["from_email"]:
        raise HTTPException(503, "SMTP nincs konfigurálva.")
    smtp = None
    stage = "connect"
    try:
        smtp = connect(c, web=c.get("source") != "environment" or candidate is not None)
        stage = "send"
        if recipient:
            message = EmailMessage()
            message["From"] = formataddr((c["from_name"], c["from_email"]))
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(text)
            if smtp.send_message(message):
                raise RuntimeError("Recipient rejected")
        return {
            "connection": True,
            "authentication": "success" if c["username"] else "not_configured",
            "encrypted": c["security"] in ("tls", "starttls"),
            "smtp_accepted": bool(recipient),
            "message": "Az SMTP-kiszolgáló elfogadta a levelet; a postaládába érkezés nem igazolt."
            if recipient
            else "SMTP-kapcsolat és beállított hitelesítés sikeres.",
        }
    except HTTPException:
        raise
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(
            422, "SMTP-hitelesítési hiba. A korábbi beállítás megmaradt."
        ) from None
    except (ssl.SSLError, smtplib.SMTPNotSupportedError):
        raise HTTPException(
            422, "Az SMTP titkosított kapcsolata nem ellenőrizhető."
        ) from None
    except Exception:
        raise HTTPException(
            422,
            "Az SMTP-kiszolgáló nem fogadta el a levelet."
            if stage == "send"
            else "Az SMTP-kapcsolat sikertelen; a korábbi beállítás megmaradt.",
        ) from None
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                smtp.close()
