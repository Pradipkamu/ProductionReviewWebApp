#!/usr/bin/env bash
# Guarded ProductionReviewWebApp server update helper.
# Commands: check | backup | verify-backup <dump> | verify |
#           prepare <branch> | deploy <branch> --confirm | rollback
#
# Safety:
# - Preserves untracked files/directories (including backups/).
# - Refuses tracked local modifications and incoming untracked-file conflicts.
# - Creates verified PostgreSQL and Git bundle backups before deployment.
# - Builds/restarts backend and frontend only.
# - NEVER runs Alembic migrations or restores the database automatically.

set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-$HOME/ProductionReviewWebApp}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/ProductionReviewWebApp-backups}"
BACKUP_DIR="$BACKUP_ROOT/database"
CODE_BACKUP_DIR="$BACKUP_ROOT/code"
LOG_DIR="$BACKUP_ROOT/logs"
STATE_FILE="$BACKUP_ROOT/last_update.env"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG=""
REMOTE_REF=""

say() {
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"
}

stop() {
  say "STOP: $*"
  exit 1
}

init() {
  command -v docker >/dev/null || { echo "STOP: docker is required"; exit 1; }
  command -v git >/dev/null || { echo "STOP: git is required"; exit 1; }
  command -v curl >/dev/null || { echo "STOP: curl is required"; exit 1; }
  [[ -d "$APP_DIR/.git" ]] || { echo "STOP: Git checkout not found: $APP_DIR"; exit 1; }

  mkdir -p "$BACKUP_DIR" "$CODE_BACKUP_DIR" "$LOG_DIR"
  LOG="$LOG_DIR/update-$STAMP.log"
  touch "$LOG"
  chmod 600 "$LOG"

  cd "$APP_DIR"
  docker compose config --quiet || stop "Compose configuration is invalid"
}

status() {
  say "Host: $(hostname)"
  say "Application: $APP_DIR"
  say "Branch: $(git branch --show-current)"
  say "Commit: $(git rev-parse HEAD)"
  say "OS: $(. /etc/os-release; echo "$PRETTY_NAME")"
  df -h "$APP_DIR" | tee -a "$LOG"
  docker --version | tee -a "$LOG"
  docker compose version | tee -a "$LOG"
  docker compose ps 2>&1 | tee -a "$LOG"
  say "Compose configuration valid. Secrets were not printed."
}

check_worktree() {
  git status --short --branch | tee -a "$LOG"

  git diff --quiet ||
    stop "Tracked working-tree changes detected. Preserve or commit them first."

  git diff --cached --quiet ||
    stop "Staged changes detected. Nothing will be stashed or discarded."

  say "Tracked working tree is clean. Untracked files will be preserved."
}

fetch_branch() {
  local branch="$1"
  REMOTE_REF="refs/remotes/origin/$branch"

  git fetch origin "refs/heads/$branch:$REMOTE_REF" ||
    stop "Could not fetch origin/$branch"

  git show-ref --verify --quiet "$REMOTE_REF" ||
    stop "Remote branch reference not found: $REMOTE_REF"
}

check_untracked_conflicts() {
  local branch_ref="$1"
  local incoming p u

  incoming="$(git diff --name-only HEAD "$branch_ref")"

  while IFS= read -r -d '' u; do
    [[ -n "$u" ]] || continue

    while IFS= read -r p; do
      [[ -n "$p" ]] || continue

      if [[ "$u" == "$p" || "$u" == "$p/"* || "$p" == "$u/"* ]]; then
        stop "Incoming file conflicts with untracked local data: $u"
      fi
    done <<< "$incoming"
  done < <(git ls-files --others --exclude-standard -z)

  say "No incoming-file conflicts with untracked local files."
}

verify_database_backup() {
  local db_file="$1"
  local scratch container_file core_tables schema_version table_count

  [[ -s "$db_file" ]] || stop "Backup file is missing or empty: $db_file"
  db_file="$(realpath "$db_file")"
  scratch="pms_verify_$(date -u +%Y%m%d%H%M%S)_${BASHPID}"
  container_file="/tmp/${scratch}.dump"

  say "Verifying backup by restoring into isolated database: $scratch"
  docker compose cp "$db_file" "db:$container_file" ||
    stop "Could not copy backup into the PostgreSQL container"

  if ! docker compose exec -T db pg_restore --list "$container_file" >/dev/null; then
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Backup archive cannot be read by pg_restore"
  fi

  if ! docker compose exec -T db createdb -U pms "$scratch"; then
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Could not create isolated verification database"
  fi

  if ! docker compose exec -T db pg_restore -U pms -d "$scratch" --no-owner --no-privileges "$container_file"; then
    docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null 2>&1 || true
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Restore into isolated verification database failed"
  fi

  if ! core_tables="$(docker compose exec -T db psql -U pms -d "$scratch" -Atc "SELECT CASE WHEN to_regclass('public.users') IS NOT NULL AND to_regclass('public.products') IS NOT NULL AND to_regclass('public.alembic_version') IS NOT NULL THEN 'OK' ELSE 'MISSING' END")"; then
    docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null 2>&1 || true
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Could not validate required tables in isolated database"
  fi
  if ! schema_version="$(docker compose exec -T db psql -U pms -d "$scratch" -Atc "SELECT COALESCE((SELECT version_num FROM public.alembic_version LIMIT 1),'')")"; then
    docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null 2>&1 || true
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Could not read Alembic revision from isolated database"
  fi
  if ! table_count="$(docker compose exec -T db psql -U pms -d "$scratch" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")"; then
    docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null 2>&1 || true
    docker compose exec -T db rm -f "$container_file" >/dev/null 2>&1 || true
    stop "Could not count restored public tables"
  fi

  docker compose exec -T db dropdb -U pms --if-exists --force "$scratch" >/dev/null ||
    stop "Verification passed, but temporary database cleanup failed: $scratch"
  docker compose exec -T db rm -f "$container_file" >/dev/null ||
    stop "Verification passed, but temporary dump cleanup failed: $container_file"

  [[ "$core_tables" == "OK" ]] || stop "Restored database is missing users, products, or alembic_version"
  [[ -n "$schema_version" ]] || stop "Restored database has no Alembic revision"
  [[ "$table_count" =~ ^[0-9]+$ && "$table_count" -gt 0 ]] ||
    stop "Restored database has no public tables"

  say "TEMPORARY RESTORE VERIFIED: core tables OK; public tables=$table_count; Alembic revision=$schema_version"
  say "Live database pms was not modified."
}

create_files_backup() {
  local archive p
  local -a paths=()

  archive="$CODE_BACKUP_DIR/files_before_update_$STAMP.tar.gz"
  [[ -f "$APP_DIR/.env" ]] || stop "Production .env file is missing; configuration backup is mandatory"
  for p in .env docker-compose.yml database/imports database/attachments database/backups mqtt/config mqtt/certs; do
    [[ -e "$APP_DIR/$p" ]] && paths+=("$p")
  done
  ((${#paths[@]} > 0)) || stop "No application data/configuration paths found for file backup"

  say "Creating protected application-data/configuration archive..."
  tar -czf "$archive" -C "$APP_DIR" "${paths[@]}" ||
    stop "Application data/configuration backup failed"
  tar -tzf "$archive" >/dev/null ||
    stop "Application data/configuration archive verification failed"
  chmod 600 "$archive"
  say "VERIFIED FILES/CONFIG BACKUP: $archive"
  printf 'FILES_BACKUP=%q\n' "$archive" >> "$STATE_FILE"
}

create_backups() {
  local db_file bundle_file

  db_file="$BACKUP_DIR/pms_before_update_$STAMP.dump"
  bundle_file="$CODE_BACKUP_DIR/code_before_update_$STAMP.bundle"

  say "Creating PostgreSQL backup..."
  docker compose exec -T db pg_dump -U pms -d pms -Fc > "$db_file" ||
    stop "Database backup command failed"

  [[ -s "$db_file" ]] || stop "Database backup is empty"

  docker compose exec -T db pg_restore --list < "$db_file" >/dev/null ||
    stop "Database backup archive verification failed"

  chmod 600 "$db_file"
  say "VERIFIED DATABASE BACKUP ARCHIVE: $db_file"
  verify_database_backup "$db_file"

  say "Creating Git rollback snapshot..."
  git bundle create "$bundle_file" --all ||
    stop "Git bundle creation failed"

  git bundle verify "$bundle_file" ||
    stop "Git bundle verification failed"

  chmod 600 "$bundle_file"
  say "VERIFIED CODE BACKUP: $bundle_file"

  {
    printf 'DB_BACKUP=%q\n' "$db_file"
    printf 'CODE_BACKUP=%q\n' "$bundle_file"
    printf 'OLD_COMMIT=%q\n' "$(git rev-parse HEAD)"
    printf 'BRANCH=%q\n' "$(git branch --show-current)"
  } > "$STATE_FILE"
  chmod 600 "$STATE_FILE"

  create_files_backup
}

migration_preflight() {
  local current heads sql_file
  sql_file="$LOG_DIR/migration-preview-$STAMP.sql"

  say "Checking database migration state against application source..."
  current="$(docker compose run --rm --no-deps backend alembic current 2>&1)" ||
    stop "Could not read current database Alembic revision"
  heads="$(docker compose run --rm --no-deps backend alembic heads 2>&1)" ||
    stop "Could not read Alembic migration heads"
  say "Current database revision: $current"
  say "Application migration head(s): $heads"

  if ! docker compose run --rm --no-deps backend alembic upgrade head --sql > "$sql_file" 2>>"$LOG"; then
    stop "Could not generate offline migration preview; inspect $LOG"
  fi
  chmod 600 "$sql_file"
  say "Offline migration SQL preview saved to: $sql_file"
  say "No migration was applied. Review it before running: bash server_update.sh migrate --confirm"
}

apply_migrations() {
  local confirm="${1:-}"
  [[ "$confirm" == "--confirm" ]] || stop "Use migrate --confirm to apply migrations"
  [[ -f "$STATE_FILE" ]] || stop "No deployment backup state found. Run backup first."

  # shellcheck disable=SC1090
  source "$STATE_FILE"
  [[ -n "${DB_BACKUP:-}" && -s "$DB_BACKUP" ]] || stop "Saved database backup is missing or empty"
  [[ -n "${BRANCH:-}" && "$(git branch --show-current)" == "$BRANCH" ]] ||
    stop "Current branch does not match saved deployment branch"

  verify_database_backup "$DB_BACKUP"
  migration_preflight
  say "Applying Alembic migrations after explicit confirmation..."
  docker compose run --rm backend alembic upgrade head ||
    stop "Migration failed. Do not attempt automatic downgrade; inspect database and logs."
  docker compose run --rm --no-deps backend alembic current ||
    stop "Migration ran but current revision could not be verified"
  say "MIGRATIONS APPLIED. Database rollback is NOT automatic; use a planned restore procedure if needed."
}

health_check() {
  local backend_ok=false frontend_ok=false db_ok=false i

  for i in $(seq 1 40); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null; then
      backend_ok=true
    fi

    if curl -fsS --max-time 3 http://127.0.0.1:5173/ >/dev/null; then
      frontend_ok=true
    fi

    if docker compose exec -T db pg_isready -U pms -d pms >/dev/null 2>&1; then
      db_ok=true
    fi

    if [[ "$backend_ok" == true && "$frontend_ok" == true && "$db_ok" == true ]]; then
      say "Backend API, frontend HTTP, and PostgreSQL readiness checks passed."
      docker compose ps 2>&1 | tee -a "$LOG"
      return 0
    fi

    sleep 3
  done

  docker compose ps 2>&1 | tee -a "$LOG"
  docker compose logs --tail=100 backend frontend 2>&1 | tee -a "$LOG"
  return 1
}

capture_running_images() {
  local backend_container frontend_container
  local backend_ref frontend_ref backend_id frontend_id

  # Resolve containers through Compose service names; never assume generated names.
  backend_container="$(docker compose ps -q backend | head -n 1)"
  frontend_container="$(docker compose ps -q frontend | head -n 1)"
  [[ -n "$backend_container" ]] || stop "Backend container is not running; cannot capture rollback image"
  [[ -n "$frontend_container" ]] || stop "Frontend container is not running; cannot capture rollback image"

  backend_ref="$(docker inspect "$backend_container" --format '{{.Config.Image}}')" ||
    stop "Could not identify the running backend image"
  frontend_ref="$(docker inspect "$frontend_container" --format '{{.Config.Image}}')" ||
    stop "Could not identify the running frontend image"
  backend_id="$(docker inspect "$backend_container" --format '{{.Image}}')" ||
    stop "Could not identify the running backend image ID"
  frontend_id="$(docker inspect "$frontend_container" --format '{{.Image}}')" ||
    stop "Could not identify the running frontend image ID"

  [[ -n "$backend_ref" && -n "$frontend_ref" && -n "$backend_id" && -n "$frontend_id" ]] ||
    stop "Running image metadata is incomplete"

  {
    printf 'BACKEND_IMAGE_REF=%q\n' "$backend_ref"
    printf 'FRONTEND_IMAGE_REF=%q\n' "$frontend_ref"
    printf 'BACKEND_IMAGE_ID=%q\n' "$backend_id"
    printf 'FRONTEND_IMAGE_ID=%q\n' "$frontend_id"
  } >> "$STATE_FILE"

  say "Captured current backend and frontend image IDs for exact rollback."
}
rollback_to() {
  local old_commit="$1"
  local backend_id="$2"
  local frontend_id="$3"
  local backend_ref="$4"
  local frontend_ref="$5"

  say "Restoring application code to $old_commit"
  git reset --hard "$old_commit" ||
    stop "Git rollback failed"

  [[ -n "$backend_id" && -n "$frontend_id" && -n "$backend_ref" && -n "$frontend_ref" ]] ||
    stop "Saved container image rollback metadata is incomplete"

  docker image tag "$backend_id" "$backend_ref" ||
    stop "Could not restore previous backend image tag"
  docker image tag "$frontend_id" "$frontend_ref" ||
    stop "Could not restore previous frontend image tag"

  docker compose up -d --no-deps backend frontend ||
    stop "Previous application services could not be restarted"

  health_check || stop "Rollback completed but health checks failed"
  say "CODE AND IMAGE ROLLBACK COMPLETED. Database was not changed or restored."
}

usage() {
  cat <<'EOF'
Usage:
  bash server_update.sh check
  bash server_update.sh backup
  bash server_update.sh verify-backup <dump-path>
  bash server_update.sh verify
  bash server_update.sh migration-check
  bash server_update.sh migrate --confirm
  bash server_update.sh prepare <branch>
  bash server_update.sh deploy <branch> --confirm
  bash server_update.sh rollback

Deployment safeguards:
  - Requested branch must already be checked out.
  - Tracked working tree must be clean.
  - Untracked files/directories are preserved.
  - Database dump is restored and checked in an isolated temporary database.
  - Git bundle is verified before deployment.
  - Backend/frontend are built and restarted.
  - Post-deploy verification checks API, frontend, and PostgreSQL readiness.
  - Alembic migrations are NOT run by deploy; use migration-check then migrate --confirm.
  - Database restore is NOT run automatically.
  - .env, Compose config, uploads, attachments, app backups, MQTT config and certificates are archived when present.
  - MQTT named-volume contents are not modified by this helper and are not included in the file archive.
  - Database rollback after a migration requires a separately planned restore.
EOF
}

main() {
  init

  case "${1:-}" in
    check)
      status
      ;;

    backup)
      status
      create_backups
      ;;

    verify-backup)
      local backup_path="${2:-}"
      [[ -n "$backup_path" ]] || stop "Usage: verify-backup <dump-path>"
      verify_database_backup "$backup_path"
      ;;

    verify)
      status
      health_check || stop "Application verification failed; inspect the update log."
      say "APPLICATION VERIFICATION PASSED."
      ;;

    migration-check)
      status
      migration_preflight
      ;;

    migrate)
      status
      apply_migrations "${2:-}"
      ;;

    prepare)
      local branch="${2:-}"
      [[ -n "$branch" ]] || stop "Branch name required"

      check_worktree
      fetch_branch "$branch"

      say "Current commit: $(git rev-parse --short HEAD)"
      say "Remote commit: $(git rev-parse --short "$REMOTE_REF")"
      git --no-pager log --oneline "HEAD..$REMOTE_REF" | tee -a "$LOG"
      git --no-pager diff --stat "HEAD...$REMOTE_REF" | tee -a "$LOG"

      check_untracked_conflicts "$REMOTE_REF"
      say "PREPARE ONLY. No checkout, database or service changes performed."
      ;;

    deploy)
      local branch="${2:-}"
      local confirm="${3:-}"
      local old_commit

      [[ -n "$branch" && "$confirm" == "--confirm" ]] ||
        stop "Use deploy <branch> --confirm"

      check_worktree
      [[ "$(git branch --show-current)" == "$branch" ]] ||
        stop "Switch to '$branch' manually before deployment."

      status
      fetch_branch "$branch"

      git merge-base --is-ancestor HEAD "$REMOTE_REF" ||
        stop "Remote is not a fast-forward. Manual review required."

      check_untracked_conflicts "$REMOTE_REF"
      old_commit="$(git rev-parse HEAD)"

      create_backups
      capture_running_images

      # Load the image IDs before any operation that may need automatic rollback.
      # The state file is generated locally using Bash %q escaping.
      # shellcheck disable=SC1090
      source "$STATE_FILE"
      [[ -n "${BACKEND_IMAGE_ID:-}" && -n "${FRONTEND_IMAGE_ID:-}" &&
         -n "${BACKEND_IMAGE_REF:-}" && -n "${FRONTEND_IMAGE_REF:-}" ]] ||
        stop "Rollback image metadata could not be loaded from $STATE_FILE"

      if [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$REMOTE_REF")" ]]; then
        say "Source is already at the requested commit; rebuilding current source and refreshing containers."
      else
        say "Fast-forwarding application code..."
      fi
      if ! git merge --ff-only "$REMOTE_REF"; then
        rollback_to "$old_commit" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" "$BACKEND_IMAGE_REF" "$FRONTEND_IMAGE_REF"
        stop "Code update failed; previous code and images restored."
      fi

      if ! docker compose build backend frontend; then
        rollback_to "$old_commit" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" "$BACKEND_IMAGE_REF" "$FRONTEND_IMAGE_REF"
        stop "Build failed; previous code and images restored."
      fi

      if ! docker compose up -d --no-deps backend frontend; then
        rollback_to "$old_commit" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" "$BACKEND_IMAGE_REF" "$FRONTEND_IMAGE_REF"
        stop "Service restart failed; previous code and images restored."
      fi

      if ! health_check; then
        rollback_to "$old_commit" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" "$BACKEND_IMAGE_REF" "$FRONTEND_IMAGE_REF"
        stop "Health check failed; previous code and images restored."
      fi

      say "UPDATE COMPLETED."
      say "Alembic migrations were NOT run. Review/apply separately with migration-check and migrate --confirm."
      say "Database backup: $BACKUP_DIR/pms_before_update_$STAMP.dump"
      say "Files/config backup: $CODE_BACKUP_DIR/files_before_update_$STAMP.tar.gz"
      say "Code backup: $CODE_BACKUP_DIR/code_before_update_$STAMP.bundle"
      ;;

    rollback)
      [[ -f "$STATE_FILE" ]] || stop "No saved update state found."

      # State file is generated by this helper using Bash %q escaping.
      # shellcheck disable=SC1090
      source "$STATE_FILE"

      [[ -n "${OLD_COMMIT:-}" && -n "${BRANCH:-}" ]] ||
        stop "Rollback state is incomplete."

      [[ "$(git branch --show-current)" == "$BRANCH" ]] ||
        stop "Current branch does not match saved update branch."

      rollback_to "$OLD_COMMIT" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" "$BACKEND_IMAGE_REF" "$FRONTEND_IMAGE_REF"
      ;;

    *)
      usage
      exit 2
      ;;
  esac

  say "Log: $LOG"
}

main "$@"
