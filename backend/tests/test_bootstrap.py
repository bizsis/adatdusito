import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import bootstrap
from app.models import User, Audit
from app.security import verify_password


def cli(monkeypatch, password, tty=True):
    monkeypatch.setattr(
        "sys.argv", ["bootstrap", "--email", "first@example.hu", "--name", "Első admin"]
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    monkeypatch.setattr(bootstrap.getpass, "getpass", lambda *args: password)


def test_bootstrap_creates_first_admin_and_audit(environment, monkeypatch, capsys):
    _, engine, *_ = environment
    with Session(engine) as db:
        db.get(User, 1).superadmin = False
        db.commit()
    cli(monkeypatch, "Secure-bootstrap-password!")
    monkeypatch.setattr(bootstrap, "engine", lambda: engine)
    bootstrap.main()
    captured = capsys.readouterr()
    assert "Secure-bootstrap-password!" not in captured.out + captured.err
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.email == "first@example.hu"))
        assert user.superadmin and verify_password(
            "Secure-bootstrap-password!", user.password_hash
        )
        assert db.scalar(
            select(Audit).where(Audit.action == "user.bootstrap_superadmin")
        )
    with pytest.raises(SystemExit, match="Már létezik"):
        bootstrap.main()


def test_bootstrap_rejects_noninteractive_and_never_prints_invalid_password(
    monkeypatch,
):
    cli(monkeypatch, "short-secret", tty=False)
    with pytest.raises(SystemExit, match="Interaktív terminál"):
        bootstrap.main()
    cli(monkeypatch, "short", tty=True)
    with pytest.raises(SystemExit) as result:
        bootstrap.main()
    assert "short" not in str(result.value)
