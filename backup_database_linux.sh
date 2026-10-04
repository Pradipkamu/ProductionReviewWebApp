#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 configure_env.py

mkdir -p database/backups
docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U pms -d pms >/dev/null; then break; fi
  if [ "$attempt" -eq 30 ]; then echo 'PostgreSQL did not become ready.' >&2; exit 1; fi
  sleep 2
done

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="database/backups/pms_${stamp}.dump"
container_file="/tmp/pms_manual_backup.dump"

cleanup() { docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker compose exec -T db pg_dump -U pms -d pms -Fc -f "$container_file"
docker compose exec -T db pg_restore --list "$container_file" >/dev/null
docker compose cp "db:$container_file" "$backup"
[ -s "$backup" ] || { echo 'Backup is empty; refusing to keep it.' >&2; rm -f "$backup"; exit 1; }
sha256sum "$backup" | awk '{print $1}' > "$backup.sha256"

echo "Verified custom-format backup created: $backup"
echo "SHA-256: $(cat "$backup.sha256")"
