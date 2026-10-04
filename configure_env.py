"""Initialize persistent secrets without breaking an existing database."""
from pathlib import Path
import secrets
from urllib.parse import quote, unquote, urlsplit

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

db_password = get_value("POSTGRES_PASSWORD")
db_url = get_value("DATABASE_URL") or ""
placeholder_db_password = not db_password or "CHANGE_THIS" in db_password.upper()
parsed_password = unquote(urlsplit(db_url).password or "")
placeholder_database_url = not parsed_password or "CHANGE_THIS" in parsed_password.upper()
if created or (placeholder_db_password and placeholder_database_url):
    db_password = secrets.token_hex(24)
    set_value("POSTGRES_PASSWORD", db_password)
    set_value("DATABASE_URL", f"postgresql+psycopg://pms:{db_password}@db:5432/pms")
elif placeholder_db_password:
    # Older installations had only DATABASE_URL. Preserve its working password
    # until the explicit rotation script safely changes PostgreSQL and .env together.
    set_value("POSTGRES_PASSWORD", parsed_password or "pms")
elif placeholder_database_url:
    set_value("DATABASE_URL", f"postgresql+psycopg://pms:{quote(db_password, safe='')}@db:5432/pms")
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
