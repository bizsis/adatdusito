"""Create credentials for isolated, synthetic cloud fixtures; never connect to the VPS."""

from pathlib import Path
import secrets

root = Path("/workspace/adatdusito/.cloud-state/codex02")
root.mkdir(mode=0o700, exist_ok=True, parents=True)
if not (root / "mysql.env").exists():
    password = secrets.token_hex(24)
    files = {
        "mysql.env": f"MYSQL_ROOT_PASSWORD={password}\n",
        "app.env": f"APP_DATABASE_URL=mysql+pymysql://app:{password}@testmysql/adatdusito_dev\nREFERENCE_DATABASE_URL=mysql+pymysql://ref:{password}@testmysql/pinfo_db\nREDIS_URL=redis://redis:6379/0\n",
        "init.sql": Path("scripts/cloud-fixture.sql")
        .read_text()
        .format(password=password),
    }
    for name, content in files.items():
        with (root / name).open("x") as output:
            (root / name).chmod(0o600)
            output.write(content)

(root / "init.sql").chmod(
    0o644
)  # Container mysql UID must read this bind-mounted fixture.
