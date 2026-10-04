#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 configure_env.py

new_password="${1:-}"
if [ -z "$new_password" ]; then
  new_password="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
)"
fi
if ! printf '%s' "$new_password" | grep -Eq '^[A-Za-z0-9._~-]{24,128}$'; then
  echo 'Database password must be 24-128 URL-safe characters: A-Z a-z 0-9 . _ ~ -' >&2
  exit 1
fi
docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U pms -d pms >/dev/null; then break; fi
  if [ "$attempt" -eq 30 ]; then echo 'PostgreSQL did not become ready.' >&2; exit 1; fi
  sleep 2
done

env_backup="$(mktemp .env.rotation.XXXXXX)"
cp .env "$env_backup"
chmod 600 "$env_backup" 2>/dev/null || true
database_changed=0
restore_env_on_failure() {
  if [ "$database_changed" -eq 0 ] && [ -f "$env_backup" ]; then
    mv -f "$env_backup" .env
  else
    rm -f "$env_backup"
  fi
}
trap restore_env_on_failure EXIT

NEW_DB_PASSWORD="$new_password" python3 - <<'PY'
import os
from pathlib import Path
from urllib.parse import quote

path=Path('.env')
lines=path.read_text(encoding='utf-8').splitlines()
password=os.environ['NEW_DB_PASSWORD']
values={
    'POSTGRES_PASSWORD':password,
    'DATABASE_URL':'postgresql+psycopg://pms:'+quote(password,safe='')+'@db:5432/pms',
}
seen=set()
out=[]
for line in lines:
    key=line.split('=',1)[0] if '=' in line and not line.lstrip().startswith('#') else None
    if key in values:
        out.append(key+'='+values[key]); seen.add(key)
    else:
        out.append(line)
for key,value in values.items():
    if key not in seen: out.append(key+'='+value)
path.write_text('\n'.join(out)+'\n',encoding='utf-8')
try:path.chmod(0o600)
except OSError:pass
PY

sql_password="$(printf '%s' "$new_password" | sed "s/'/''/g")"
docker compose exec -T db psql -U pms -d pms -v ON_ERROR_STOP=1 -c "ALTER ROLE pms WITH PASSWORD '$sql_password';"
database_changed=1
rm -f "$env_backup"

docker compose up -d --force-recreate backend
for attempt in $(seq 1 40); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo 'Database password rotated and backend reconnected successfully.'
    echo 'The new password is stored only in .env. Keep that file private.'
    exit 0
  fi
  sleep 2
done
echo 'Password was changed, but backend health did not recover. Check .env and docker compose logs backend.' >&2
exit 1
