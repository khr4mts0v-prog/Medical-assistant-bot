#!/usr/bin/env bash
# Deploy only the web service from origin/release/web-2026-10.
# Run as root (for Docker); never stashes, resets, or checks out the working tree.
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)"
RELEASE_BRANCH="${RELEASE_BRANCH:-release/web-2026-10}"
DEPLOY_WORKTREE="${DEPLOY_WORKTREE:-/opt/medical-archive-release}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/medical-archive-backups}"
DB_FILE="$SOURCE_ROOT/data/archive.sqlite3"

git -c safe.directory="$SOURCE_ROOT" -C "$SOURCE_ROOT" fetch origin "$RELEASE_BRANCH"

if [[ -e "$DEPLOY_WORKTREE" ]]; then
  if ! git -C "$DEPLOY_WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Refusing to use existing non-worktree path: $DEPLOY_WORKTREE" >&2
    exit 3
  fi
  if [[ "$(git -C "$DEPLOY_WORKTREE" rev-parse --show-toplevel)" != "$DEPLOY_WORKTREE" ]]; then
    echo "Deployment path is not the root of its own worktree." >&2
    exit 3
  fi
  if [[ -n "$(git -C "$DEPLOY_WORKTREE" status --porcelain --untracked-files=no)" ]]; then
    echo "Deployment worktree has tracked changes; refusing to overwrite them." >&2
    exit 3
  fi
  git -C "$DEPLOY_WORKTREE" fetch origin "$RELEASE_BRANCH"
  git -C "$DEPLOY_WORKTREE" checkout --detach "origin/$RELEASE_BRANCH"
else
  git -c safe.directory="$SOURCE_ROOT" -C "$SOURCE_ROOT" worktree add --detach "$DEPLOY_WORKTREE" "origin/$RELEASE_BRANCH"
fi

for item in .env data; do
  source_path="$SOURCE_ROOT/$item"
  target_path="$DEPLOY_WORKTREE/$item"
  [[ -e "$source_path" ]] || { echo "Required existing path is missing: $source_path" >&2; exit 4; }
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    [[ "$(readlink -f "$target_path")" == "$(readlink -f "$source_path")" ]] || {
      echo "Refusing to replace existing $target_path; expected link to $source_path" >&2; exit 4;
    }
  else
    ln -s "$source_path" "$target_path"
  fi
done

[[ -f "$DB_FILE" ]] || { echo "Database not found at $DB_FILE; refusing deployment without a verified backup." >&2; exit 5; }
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="$BACKUP_ROOT/archive-$STAMP.sqlite3"
python3 - "$DB_FILE" "$BACKUP_FILE" <<'PY'
import os, sqlite3, sys
source, target = sys.argv[1:3]
src = sqlite3.connect("file:" + source + "?mode=ro", uri=True, timeout=30)
dst = sqlite3.connect(target)
try:
    src.backup(dst)
    dst.commit()
finally:
    dst.close()
    src.close()
os.chmod(target, 0o600)
check = sqlite3.connect("file:" + target + "?mode=ro", uri=True)
try:
    check.execute("PRAGMA quick_check").fetchone()
finally:
    check.close()
PY
echo "Database backup created: $BACKUP_FILE"

SERVICE="medical-archive-web"
PROJECT="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$SERVICE" 2>/dev/null || true)"
PROJECT="${PROJECT:-medical-assistant-bot}"
OLD_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$SERVICE")"
OLD_IMAGE_NAME="$(docker inspect -f '{{.Config.Image}}' "$SERVICE")"
ROLLBACK_TAG="medical-archive-web:rollback-$STAMP"
docker image tag "$OLD_IMAGE_ID" "$ROLLBACK_TAG"

COMPOSE=(docker compose -p "$PROJECT" -f "$DEPLOY_WORKTREE/docker-compose.yml")
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build --pull "$SERVICE"
"${COMPOSE[@]}" up -d --no-deps "$SERVICE"

if python3 "$DEPLOY_WORKTREE/scripts/smoke_test_web.py" --env-file "$DEPLOY_WORKTREE/.env"; then
  echo "Deployment verified. Telegram/bot service was not restarted."
  echo "Rollback image retained as $ROLLBACK_TAG"
else
  echo "Smoke test failed; restoring the previous web image." >&2
  docker image tag "$OLD_IMAGE_ID" "$OLD_IMAGE_NAME"
  "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate "$SERVICE" || true
  echo "Rollback attempted. Inspect medical-archive-web logs before retrying." >&2
  exit 6
fi
