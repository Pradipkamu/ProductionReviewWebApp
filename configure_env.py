"""Initialize persistent secrets without breaking an existing database."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parent / ".env"
created = not path.exists()
if created:
    path.write_text(path.with_name(".env.example").read_text(encoding="utf-8"), encoding="utf-8")

lines = path.read_text(encoding="utf-8").splitlines()


def get_value(key: str) -> str | None:
    prefix = key + "="
    for line in lines:
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return None


def set_value(key: str, value: str) -> None:
    prefix = key + "="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = prefix + value
            return
    lines.append(prefix + value)


secret = get_value("SECRET_KEY")
if not secret or "CHANGE" in secret.upper() or secret == "dev-secret-change-me":
    set_value("SECRET_KEY", secrets.token_urlsafe(48))

db_placeholder = (get_value("POSTGRES_PASSWORD") or "").upper().startswith("CHANGE_") or "CHANGE_THIS" in (get_value("DATABASE_URL") or "").upper()
if created or db_placeholder:
    db_password = secrets.token_hex(24)
    set_value("POSTGRES_PASSWORD", db_password)
    set_value("DATABASE_URL", f"postgresql+psycopg://pms:{db_password}@db:5432/pms")
if created:
    admin_password = get_value("ADMIN_PASSWORD")
    if not admin_password or admin_password == "ChangeMe123!" or "CHANGE" in admin_password.upper():
        set_value("ADMIN_PASSWORD", "Init-" + secrets.token_urlsafe(18) + "!9aA")

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
try:
    path.chmod(0o600)
except OSError:
    pass

db_url = get_value("DATABASE_URL") or ""
legacy_db = "@db:5432/pms" in db_url and (":pms@" in db_url or "CHANGE_THIS" in db_url)
legacy_admin = (get_value("ADMIN_PASSWORD") or "") == "ChangeMe123!"
print("Environment initialized; existing non-placeholder settings preserved.")
if created:
    print("Fresh-install application/database credentials were generated in .env.")
else:
    if legacy_db:
        print("SECURITY WARNING: legacy/default database password detected; run the database password rotation script.")
    if legacy_admin:
        print("SECURITY WARNING: bootstrap ADMIN_PASSWORD is still the legacy default; change it in .env after confirming the real admin account password.")
