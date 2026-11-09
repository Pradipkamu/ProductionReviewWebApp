#!/usr/bin/env bash
# ProductionReviewWebApp — guarded Pradipweb branch-switch and deployment helper
#
# Run from the repository root after downloading this helper:
#   bash /tmp/server_update.sh deploy feature/oee-refinement-web-android \
#     --reuse-db-backup /home/ubuntu/ProductionReviewWebApp-backups/database/pms_before_update_20261109T041725Z.dump \
#     --code-snapshot /home/ubuntu/ProductionReviewWebApp-backups/server-code/server-code-20261109T042833Z \
#     --confirm
#
# Safety:
# - Preserves the current branch and all local changes in an external snapshot.
# - Never resets, cleans, stashes, or deletes user files.
# - Allows tracked local edits only when each edited file already matches target.
# - Stages only those verified target-identical files so Git can switch safely.
# - Refuses untracked-file collisions with incoming tracked files.
# - Switches to the target branch (tracking origin/<branch>) for future deployments.
# - Requires an existing, verified DB backup; does not create a duplicate backup.
# - Builds, migrates, restarts, and performs basic post-deploy checks.
# - No automatic database rollback is attempted.

set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-$HOME/ProductionReviewWebApp}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/ProductionReviewWebApp-backups/database}"
CODE_BACKUP_DIR="${CODE_BACKUP_DIR:-$HOME/ProductionReviewWebApp-backups/server-code}"
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
usage() {
  cat <<'EOF'
Usage:
  bash /tmp/server_update.sh check
  bash /tmp/server_update.sh deploy <target-branch> --reuse-db-backup <dump-file> --code-snapshot <snapshot-dir> --confirm

The deploy command reuses the supplied existing backup and code snapshot.
It does not create another database backup.
EOF
}
init() {
  command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
  command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
  [[ -d "$APP_DIR/.git" ]] || { echo "Git checkout not found: $APP_DIR" >&2; exit 1; }
  mkdir -p "$BACKUP_DIR" "$CODE_BACKUP_DIR" "$LOG_DIR"
  LOG_FILE="$LOG_DIR/update-$STAMP.log"
  touch "$LOG_FILE"
  chmod 600 "$LOG_FILE"
  cd "$APP_DIR"
}
check_untracked_collisions() {
  local collisions
  collisions="$(comm -12 \
    <(git ls-files --others --exclude-standard | sort) \
    <(git ls-tree -r --name-only "$1" | sort))"
  [[ -z "$collisions" ]] || {
    printf '%s\n' "$collisions" | tee -a "$LOG_FILE"
    stop "Untracked files collide with incoming tracked files. Nothing was switched."
  }
}
verify_existing_backups() {
  local db_backup="$1" code_snapshot="$2"
  [[ -s "$db_backup" ]] || stop "Existing database backup is missing or empty: $db_backup"
  [[ -d "$code_snapshot" && -s "$code_snapshot/git-status.txt" && -s "$code_snapshot/tracked-changes.patch" ]] ||
    stop "Existing code-preservation snapshot is incomplete: $code_snapshot"
  docker compose ps db | tee -a "$LOG_FILE"
  docker compose exec -T db pg_isready >/dev/null || stop "PostgreSQL is not accepting connections."
  docker compose exec -T db pg_restore -l < "$db_backup" >/dev/null ||
    stop "Existing database backup failed archive verification."
  log "Verified and reusing existing database backup: $db_backup"
  log "Verified code-preservation snapshot: $code_snapshot"
}
deploy() {
  local branch="$1" db_backup="$2" code_snapshot="$3"
  local target_ref current_branch current_head target_head changed_files file

  [[ -n "$branch" && "$branch" != -* ]] || stop "Invalid target branch."
  [[ -s "$db_backup" ]] || stop "Supply --reuse-db-backup with the existing dump."
  [[ -d "$code_snapshot" ]] || stop "Supply --code-snapshot with the existing snapshot."
  current_branch="$(git branch --show-current)"
  current_head="$(git rev-parse HEAD)"
  log "Current branch: $current_branch"
  log "Current commit: $current_head"
  log "Fetching target branch origin/$branch."
  git fetch origin "$branch" || stop "Fetch failed."
  target_ref="FETCH_HEAD"
  target_head="$(git rev-parse "$target_ref")"
  log "Target commit: $target_head"

  git merge-base --is-ancestor "$current_head" "$target_ref" ||
    stop "Target is not a descendant of current HEAD; refusing non-fast-forward transition."

  check_untracked_collisions "$target_ref"

  # Any tracked local edit is accepted only if its working-tree contents
  # already equal the fetched target. Stage only those exact files: this
  # aligns the index with the target and lets git switch proceed without
  # discarding or overwriting user work.
  changed_files="$(git diff HEAD --name-only)"
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    git diff --quiet "$target_ref" -- "$file" ||
      stop "Local tracked edit differs from target branch: $file. No local changes were discarded."
    git add -- "$file" || stop "Could not stage verified target-identical file: $file"
    log "Safely staged target-identical local file: $file"
  done <<< "$changed_files"

  verify_existing_backups "$db_backup" "$code_snapshot"

  log "Switching server checkout to target branch '$branch'."
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git switch "$branch" || stop "Could not switch to existing local target branch."
  else
    git switch --track -c "$branch" "origin/$branch" ||
      stop "Could not create local tracking branch '$branch'."
  fi

  git merge --ff-only "$target_ref" || stop "Target branch could not be fast-forwarded after switching."

  log "Target branch now active: $(git branch --show-current) @ $(git rev-parse --short HEAD)"
  log "Validating Docker Compose."
  docker compose config --quiet || stop "Docker Compose configuration is invalid."

  log "Building backend and frontend."
  docker compose build backend frontend || stop "Image build failed; existing DB backup retained."

  log "Applying Alembic migrations."
  docker compose run --rm backend alembic upgrade head ||
    stop "Migration failed. Stop and inspect; backup retained."

  log "Restarting backend and frontend."
  docker compose up -d --no-deps backend frontend ||
    stop "Service restart failed; backup retained."

  log "Waiting briefly for containers to settle."
  sleep 8
  docker compose ps | tee -a "$LOG_FILE"
  docker compose logs --tail=80 backend frontend 2>&1 | tee -a "$LOG_FILE"

  log "Deployment command sequence completed."
  log "Verify web login, OEE entry/edit, rejection images, and key production pages in browser."
  log "Database backup retained at: $db_backup"
  log "Code snapshot retained at: $code_snapshot"
  log "No database rows, Docker volumes, attachments, or backup files were deleted."
}
main() {
  init
  case "${1:-}" in
    check)
      log "Branch: $(git branch --show-current)"
      log "Commit: $(git rev-parse --short HEAD)"
      git status --short --branch | tee -a "$LOG_FILE"
      docker compose ps | tee -a "$LOG_FILE"
      ;;
    deploy)
      [[ "${2:-}" != "" ]] || { usage; exit 2; }
      shift
      branch="$1"; shift
      db_backup=""; code_snapshot=""; confirm=""
      while (($#)); do
        case "$1" in
          --reuse-db-backup) db_backup="${2:-}"; shift 2 ;;
          --code-snapshot) code_snapshot="${2:-}"; shift 2 ;;
          --confirm) confirm="yes"; shift ;;
          *) stop "Unknown argument: $1" ;;
        esac
      done
      [[ "$confirm" == yes ]] || stop "Explicit --confirm is required."
      deploy "$branch" "$db_backup" "$code_snapshot"
      ;;
    *) usage; exit 2 ;;
  esac
  log "Log file: $LOG_FILE"
}
main "$@"
