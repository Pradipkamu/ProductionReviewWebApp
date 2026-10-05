#!/usr/bin/env bash
# Run from this release on the existing HTTPS server. Never replaces .env or data.
set -Eeuo pipefail
cd "$(dirname "$0")"
test "$(cat VERSION.txt)" = v0.5.7
test -f .env
docker compose exec -T backend python - <<'PY'
from app.config import get_settings
s = get_settings()
assert s.require_https and s.trust_proxy_headers, 'Keep REQUIRE_HTTPS=true and TRUST_PROXY_HEADERS=true before deployment'
PY
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="database/backups/v057_$stamp"
mkdir -p "$backup_dir"
cp -p .env "$backup_dir/environment.env"
git rev-parse HEAD > "$backup_dir/source_commit.txt" 2>/dev/null || true

# Retain the running images so an unsuccessful app update can be rolled back.
for service in backend frontend; do
  cid=$(docker compose ps -q "$service")
  test -n "$cid"
  docker inspect --format '{{.Image}}' "$cid" > "$backup_dir/$service.image-id"
  docker inspect --format '{{.Config.Image}}' "$cid" > "$backup_dir/$service.image-name"
  docker image tag "$(cat "$backup_dir/$service.image-id")" "pms-v057-rollback-$service:$stamp"
done
changed=0
recover() {
  code=$?
  trap - ERR
  if [ "$changed" = 1 ]; then
    echo 'Update failed; restoring the previous application images.' >&2
    for service in backend frontend; do
      docker image tag "$(cat "$backup_dir/$service.image-id")" "$(cat "$backup_dir/$service.image-name")" || true
    done
    docker compose up -d --no-build --no-deps backend frontend || true
  fi
  echo "Deployment did not complete. Backup/log details: $backup_dir" >&2
  exit "$code"
}
trap recover ERR
docker compose build backend frontend
docker compose run --rm --no-deps backend python -m app.preflight
docker compose run --rm --no-deps backend python -c 'from app import __version__; assert __version__ == "0.5.7"'
cmp .env "$backup_dir/environment.env"
changed=1
docker compose stop frontend backend
docker compose exec -T db pg_dump -U pms -d pms -Fc > "$backup_dir/pms.dump"
test -s "$backup_dir/pms.dump"
docker compose exec -T db pg_restore --list < "$backup_dir/pms.dump" > "$backup_dir/restore-list.txt"
sha256sum "$backup_dir/pms.dump" > "$backup_dir/pms.dump.sha256"
docker compose up -d --no-build --no-deps backend frontend
healthy=0
for attempt in $(seq 1 40); do
  if curl --max-time 3 -fsS http://127.0.0.1:8000/api/health | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and d.get("version")=="0.5.7" else 1)' 2>/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
test "$healthy" = 1
curl --max-time 15 -fsS https://machineshop.duckdns.org/api/health | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("version")=="0.5.7" and d.get("status")=="ok"; print(d)'
status=$(curl --max-time 15 -sS -o /dev/null -w '%{http_code}' https://machineshop.duckdns.org/api/auth/me)
test "$status" = 401
cmp .env "$backup_dir/environment.env"
changed=0
trap - ERR
echo "v0.5.7 deployed. HTTPS authentication check: 401 (expected). Backup: $backup_dir/pms.dump"
