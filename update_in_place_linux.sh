#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 configure_env.py
mkdir -p database/backups
docker compose build backend frontend
# Validate the newly built source before stopping the currently running app.
# This catches partially copied update packages (for example, a stale auth.py).
docker compose run --rm --no-deps backend python -c 'from app.auth import record_security_event; from app.main import app; print("Backend import preflight passed")'
docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U pms -d pms >/dev/null; then break; fi
  if [ "$attempt" -eq 30 ]; then echo 'PostgreSQL did not become ready; no backup or migration was attempted.' >&2; exit 1; fi
  sleep 2
done
# Quiesce app writes before taking the pre-migration database snapshot.
docker compose stop frontend backend
backup="database/backups/pms_before_update_$(date -u +%Y%m%dT%H%M%SZ).dump"
if ! docker compose exec -T db pg_dump -U pms -d pms -Fc > "$backup"; then
  rm -f "$backup"
  echo 'Backup failed; database migration has NOT run.' >&2
  exit 1
fi
test -s "$backup"
docker compose exec -T db pg_restore --list < "$backup" >/dev/null
sha256sum "$backup" > "$backup.sha256"
# Build is complete, backup is verified, and database bind mount is unchanged.
docker compose up -d --no-deps backend frontend
for attempt in $(seq 1 40); do
  if curl -fsS http://localhost:8000/api/health >/dev/null; then
    echo "Update ready. Verified backup: $backup"
    exit 0
  fi
  sleep 2
done
docker compose logs --tail=100 backend
echo 'Health check failed. Keep the backup and see docs/UPDATE_v0.3.0.md.' >&2
exit 1
