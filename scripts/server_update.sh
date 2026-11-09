#!/usr/bin/env bash
# ProductionReviewWebApp — guarded Pradipweb update helper
#
# Install/run from the repository root:
#   bash scripts/server_update.sh check
#   bash scripts/server_update.sh backup
#   bash scripts/server_update.sh prepare <branch>
#   bash scripts/server_update.sh deploy <branch> --confirm
#
# Optional overrides:
#   APP_DIR, BACKUP_DIR, LOG_DIR
#
# Safety guarantees:
# - Does not print .env or rendered Compose configuration.
# - Never stashes, resets, checks out, or discards local changes.
# - Stops if the Git working tree is dirty or deployment is not fast-forward.
# - Creates and verifies a PostgreSQL custom-format backup before migration.
# - Does not delete database rows, Docker volumes, or attachments.
# - Requires explicit --confirm for deployment.

set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-$HOME/ProductionReviewWebApp}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/ProductionReviewWebApp-backups/database}"
LOG_DIR="${LOG_DIR:-$HOME/ProductionReviewWebApp-backups/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE=""

log() {
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_FILE"
}

stop() {
  log "STOP: $*"
  exit 1
}

init() {
  command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
  command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
  [[ -d "$APP_DIR/.git" ]] || { echo "Git checkout not found: $APP_DIR" >&2; exit 1; }

  mkdir -p "$BACKUP_DIR" "$LOG_DIR"
  LOG_FILE="$LOG_DIR/update-$STAMP.log"
  touch "$LOG_FILE"
  chmod 600 "$LOG_FILE"

  cd "$APP_DIR"
  docker compose config --quiet || stop "Docker Compose configuration is invalid."
}

check_git_clean() {
  log "Branch: $(git branch --show-current)"
  log "Commit: $(git rev-parse --short HEAD)"
  log "Remote: $(git remote get-url origin 2>/dev/null || echo unavailable)"
  git status --short --branch | tee -a "$LOG_FILE"

  [[ -z "$(git status --porcelain)" ]] ||
    stop "Local or untracked changes detected. Nothing was stashed or discarded."
}

show_status() {
  log "===== SERVER INFORMATION ====="
  log "Host: $(hostname)"
  log "OS: $(. /etc/os-release && printf '%s' "$PRETTY_NAME")"
  log "Application directory: $APP_DIR"
  log "Disk space:"
  df -h "$APP_DIR" | tee -a "$LOG_FILE"

  log "Docker version:"
  docker --version | tee -a "$LOG_FILE"
  log "Compose version:"
  docker compose version | tee -a "$LOG_FILE"

  log "===== GIT STATUS ====="
  git status --short --branch | tee -a "$LOG_FILE"

  log "===== DOCKER SERVICES ====="
  docker compose ps 2>&1 | tee -a "$LOG_FILE"

  log "Compose configuration is valid. Secrets were not displayed."
}

database_backup() {
  local db_user db_name backup_file

  log "Checking database container availability."
  docker compose ps db | tee -a "$LOG_FILE"
  docker compose exec -T db pg_isready >/dev/null ||
    stop "PostgreSQL is not accepting connections."

  db_user="$(docker compose exec -T db sh -lc 'printf %s "$POSTGRES_USER"')"
  db_name="$(docker compose exec -T db sh -lc 'printf %s "$POSTGRES_DB"')"
  [[ -n "$db_user" && -n "$db_name" ]] ||
    stop "Could not determine database user/name from the db container."

  backup_file="$BACKUP_DIR/pms_before_update_$STAMP.dump"
  log "Creating PostgreSQL backup for database '$db_name'."
  log "Backup destination: $backup_file"

  docker compose exec -T db pg_dump -U "$db_user" -d "$db_name" -Fc > "$backup_file"
  [[ -s "$backup_file" ]] || stop "Backup file is missing or empty."

  docker compose exec -T db pg_restore -l < "$backup_file" >/dev/null ||
    stop "PostgreSQL backup archive verification failed."

  chmod 600 "$backup_file"
  log "VERIFIED DATABASE BACKUP: $backup_file"
  log "Backup size: $(du -h "$backup_file" | awk '{print $1}')"
}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/server_update.sh check
  bash scripts/server_update.sh backup
  bash scripts/server_update.sh prepare <branch>
  bash scripts/server_update.sh deploy <branch> --confirm

Environment overrides:
  APP_DIR       Repository path (default: ~/ProductionReviewWebApp)
  BACKUP_DIR    Database backup directory outside Git (default: ~/ProductionReviewWebApp-backups/database)
  LOG_DIR       Update log directory outside Git (default: ~/ProductionReviewWebApp-backups/logs)

The deploy command expects the requested branch to already be checked out.
It will not switch branches.
EOF
}

main() {
  init

  case "${1:-}" in
    check)
      show_status
      ;;
    backup)
      show_status
      database_backup
      ;;
    prepare)
      local branch="${2:-}"
      [[ -n "$branch" ]] || stop "Branch name is required."
      check_git_clean
      log "Fetching origin/$branch."
      git fetch origin "$branch" || stop "Git fetch failed."

      log "Current HEAD: $(git rev-parse --short HEAD)"
      log "Remote HEAD:  $(git rev-parse --short FETCH_HEAD)"
      log "===== COMMITS TO BE DEPLOYED ====="
      git --no-pager log --oneline HEAD..FETCH_HEAD | tee -a "$LOG_FILE"
      log "===== FILE CHANGE SUMMARY ====="
      git --no-pager diff --stat HEAD...FETCH_HEAD | tee -a "$LOG_FILE"
      log "PREPARE ONLY: no checkout, migration, build, or restart was performed."
      ;;
    deploy)
      local branch="${2:-}"
      local confirmation="${3:-}"

      [[ -n "$branch" ]] || stop "Branch name is required."
      [[ "$confirmation" == "--confirm" ]] ||
        stop "Explicit confirmation required: deploy <branch> --confirm"

      check_git_clean
      [[ "$(git branch --show-current)" == "$branch" ]] ||
        stop "Current branch must already be '$branch'. This helper will not switch branches."

      show_status
      log "Fetching origin/$branch."
      git fetch origin "$branch" || stop "Git fetch failed."

      git merge-base --is-ancestor HEAD FETCH_HEAD ||
        stop "Remote branch is not a fast-forward. Manual review is required."

      [[ "$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)" ]] ||
        stop "Already up to date; no deployment is required."

      log "Creating and verifying database backup before changing code."
      database_backup

      log "Fast-forwarding branch '$branch'."
      git merge --ff-only FETCH_HEAD || stop "Fast-forward failed."

      log "Building backend and frontend images."
      docker compose build backend frontend ||
        stop "Image build failed. Database backup is retained."

      log "Applying database migrations."
      docker compose run --rm backend alembic upgrade head ||
        stop "Migration failed. Stop and inspect before retrying; backup is retained."

      log "Restarting backend and frontend."
      docker compose up -d --no-deps backend frontend ||
        stop "Service restart failed. Database backup is retained."

      log "===== POST-DEPLOY SERVICE STATUS ====="
      docker compose ps 2>&1 | tee -a "$LOG_FILE"

      log "Deployment commands completed."
      log "IMPORTANT: Verify login, Personnel list/create, OEE entry, and key production pages in the browser."
      log "This helper does not automatically roll back migrations or database contents."
      ;;
    *)
      usage
      exit 2
      ;;
  esac

  log "Operation finished. Log file: $LOG_FILE"
}

main "$@"
