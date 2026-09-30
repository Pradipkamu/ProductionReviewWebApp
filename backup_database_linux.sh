#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
mkdir -p database/backups
TS=$(date +%Y%m%d_%H%M%S)
docker compose exec -T db pg_dump -U pms -d pms > "database/backups/pms_${TS}.sql"
echo "Backup created: database/backups/pms_${TS}.sql"
