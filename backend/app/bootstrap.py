"""Interactive, local-only operator command; no password in argv, logs or defaults."""

import argparse
import getpass
import sys
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api import CreateUser
from app.db import engine
from app.models import Audit, Role, User
from app.security import hash_password


def main():
    parser = argparse.ArgumentParser(
        description="Első Superadmin biztonságos létrehozása"
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit(
            "Interaktív terminál szükséges. Használd a docker compose exec parancsot -T nélkül."
        )
    password = getpass.getpass("Jelszó (legalább 12 karakter): ")
    if password != getpass.getpass("Jelszó megerősítése: "):
        raise SystemExit("A két jelszó nem egyezik.")
    try:
        body = CreateUser(
            email=args.email, name=args.name, password=password, superadmin=True
        )
    except ValidationError:
        raise SystemExit(
            "Érvénytelen email, név vagy jelszó (legalább 12 karakter)."
        ) from None
    with Session(engine()) as db:
        if not db.scalar(
            select(Role).where(Role.code == "superadmin").with_for_update()
        ):
            raise SystemExit("Előbb futtasd az adatbázis-migrációt.")
        if db.scalar(select(User.id).where(User.superadmin.is_(True))):
            raise SystemExit("Már létezik Superadmin. Használd az adminfelületet.")
        if db.scalar(select(User.id).where(User.email == body.email)):
            raise SystemExit("Az email-cím már használatban van.")
        user = User(
            email=body.email,
            name=body.name,
            password_hash=hash_password(body.password),
            superadmin=True,
        )
        db.add(user)
        db.flush()
        db.add(
            Audit(
                actor_id=user.id,
                action="user.bootstrap_superadmin",
                target=str(user.id),
                details={},
            )
        )
        db.commit()
    print("A Superadmin létrejött. Jelszó nem került naplózásra.")


if __name__ == "__main__":
    main()
