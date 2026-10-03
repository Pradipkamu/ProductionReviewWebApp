#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

backup="${1:-}"
if [ -z "$backup" ]; then
  backup="$(find database/backups -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
fi
if [ -z "$backup" ] || [ ! -s "$backup" ]; then
  echo 'No non-empty .dump backup was found. Pass the backup path as the first argument.' >&2
  exit 1
fi
if [ -f "$backup.sha256" ]; then
  sha256sum -c "$backup.sha256"
fi

docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U pms -d pms >/dev/null; then break; fi
  if [ "$attempt" -eq 30 ]; then echo 'PostgreSQL did not become ready.' >&2; exit 1; fi
  sleep 2
done

scratch="pms_restore_verify_$(date -u +%Y%m%d%H%M%S)_$$"
container_file="/tmp/${scratch}.dump"
cleanup() {
  docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null 2>&1 || true
  docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose cp "$backup" "db:$container_file"
docker compose exec -T db pg_restore --list "$container_file" >/dev/null
docker compose exec -T db createdb -U pms "$scratch"
docker compose exec -T db pg_restore -U pms -d "$scratch" --no-owner --no-privileges "$container_file"
core_tables="$(docker compose exec -T db psql -U pms -d "$scratch" -Atc "SELECT CASE WHEN to_regclass('public.users') IS NOT NULL AND to_regclass('public.products') IS NOT NULL THEN 'OK' ELSE 'MISSING' END")"
if [ "$core_tables" != "OK" ]; then
  echo 'Restore completed but required users/products tables are missing.' >&2
  exit 1
fi
echo "Restore verification passed in isolated database $scratch. Live database pms was not modified."
