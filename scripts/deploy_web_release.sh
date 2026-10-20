#!/usr/bin/env bash
# Deploy only the web service from origin/release-web-2026-10.
# Run as root (for Docker); never stashes, resets, or checks out the source working tree.
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 2
fi

# Persist the complete transcript, while still showing it in the terminal.
LOG_ROOT="${LOG_ROOT:-/opt/medical-assistant-logs}"
mkdir -p "$LOG_ROOT"
chmod 700 "$LOG_ROOT"
LOG_FILE="$LOG_ROOT/deploy-web-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'rc=$?; echo "[ERROR] line=$LINENO exit=$rc command=$BASH_COMMAND"; echo "Full deployment log: $LOG_FILE"; exit "$rc"' ERR
echo "Deployment started: $(date -u +%FT%TZ)"
echo "Full deployment log: $LOG_FILE"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${SOURCE_ROOT:-$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)}"
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

# Fail closed before backup/build/restart. Never auto-edit .env during deployment.
python3 "$DEPLOY_WORKTREE/scripts/check_production_env.py" --mode testing --env-file "$DEPLOY_WORKTREE/.env"

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
    result = check.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise SystemExit("SQLite backup quick_check failed: " + repr(result))
finally:
    check.close()
PY
echo "Database backup created: $BACKUP_FILE"

SERVICE="medical-archive-web"
COMPOSE=(docker compose -p medical-assistant-bot -f "$DEPLOY_WORKTREE/docker-compose.yml")
"${COMPOSE[@]}" config --quiet

# Capture the existing web container before changing anything.
OLD_CONTAINER_ID="$(docker inspect -f '{{.Id}}' "$SERVICE")"
OLD_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$SERVICE")"
OLD_IMAGE_NAME="$(docker inspect -f '{{.Config.Image}}' "$SERVICE")"
OLD_PROJECT="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$SERVICE" 2>/dev/null || true)"
OLD_SERVICE="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$SERVICE" 2>/dev/null || true)"
ROLLBACK_TAG="medical-archive-web:rollback-$STAMP"
docker image tag "$OLD_IMAGE_ID" "$ROLLBACK_TAG"
echo "Existing container: id=$OLD_CONTAINER_ID image=$OLD_IMAGE_NAME project=${OLD_PROJECT:-<none>} service=${OLD_SERVICE:-<none>}"

"${COMPOSE[@]}" build --pull "$SERVICE"

# An unmanaged container with the fixed Compose container_name blocks Compose from
# creating its replacement. Validate its data mount and published port, then stop
# and rename it (do not delete it) so it remains available for rollback.
RENAMED_CONTAINER=""
if [[ -z "$OLD_PROJECT" || "$OLD_SERVICE" != "$SERVICE" || "$OLD_PROJECT" != "medical-assistant-bot" ]]; then
  python3 - "$SERVICE" "$SOURCE_ROOT/data" <<'PY'
import json, os, subprocess, sys
name, expected_data = sys.argv[1:3]
obj = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
mounts = {m.get("Destination"): os.path.realpath(m.get("Source", "")) for m in obj.get("Mounts", [])}
if mounts.get("/app/data") != os.path.realpath(expected_data):
    raise SystemExit("Refusing to replace unmanaged web container: /app/data mount does not match " + expected_data)
bindings = obj.get("HostConfig", {}).get("PortBindings", {}).get("8000/tcp") or []
if not any(b.get("HostIp") == "127.0.0.1" and b.get("HostPort") == "8000" for b in bindings):
    raise SystemExit("Refusing to replace unmanaged web container: expected 127.0.0.1:8000 binding not found")
print("Existing unmanaged container validated: data mount and loopback port match.")
PY
  RENAMED_CONTAINER="medical-archive-web-preserved-$STAMP"
  docker stop "$SERVICE"
  docker rename "$SERVICE" "$RENAMED_CONTAINER"
  echo "Preserved previous web container as $RENAMED_CONTAINER (stopped, not deleted)."
fi

restore_preserved_container() {
  if [[ -n "$RENAMED_CONTAINER" ]] && docker inspect "$RENAMED_CONTAINER" >/dev/null 2>&1; then
    # Remove only the newly created Compose web container, if it is ours.
    if docker inspect "$SERVICE" >/dev/null 2>&1; then
      NEW_PROJECT="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$SERVICE" 2>/dev/null || true)"
      NEW_SERVICE="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$SERVICE" 2>/dev/null || true)"
      if [[ "$NEW_PROJECT" == "medical-assistant-bot" && "$NEW_SERVICE" == "$SERVICE" ]]; then
        docker stop "$SERVICE" || true
        docker rm "$SERVICE" || true
      else
        echo "Cannot safely remove conflicting container named $SERVICE; preserved container remains $RENAMED_CONTAINER." >&2
        return 1
      fi
    fi
    docker rename "$RENAMED_CONTAINER" "$SERVICE"
    docker start "$SERVICE"
    echo "Restored original web container $OLD_CONTAINER_ID."
  fi
}

if ! "${COMPOSE[@]}" up -d --no-deps "$SERVICE"; then
  echo "Compose failed to replace the web service; restoring preserved container if applicable." >&2
  restore_preserved_container || true
  exit 6
fi

if python3 "$DEPLOY_WORKTREE/scripts/smoke_test_web.py" --env-file "$DEPLOY_WORKTREE/.env"; then
  echo "Deployment verified. Telegram/bot service was not restarted."
  echo "Rollback image retained as $ROLLBACK_TAG"
  if [[ -n "$RENAMED_CONTAINER" ]]; then
    echo "Previous container retained (stopped) as $RENAMED_CONTAINER."
  fi
else
  echo "Smoke test failed; collecting new web container diagnostics before rollback." >&2
  if docker inspect "$SERVICE" >/dev/null 2>&1; then
    echo "=== Failed web container state ===" >&2
    docker inspect -f 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}}' "$SERVICE" >&2 || true
    echo "=== Failed web container logs (last 160 lines) ===" >&2
    docker logs --tail 160 "$SERVICE" 2>&1 || true
  else
    echo "Failed web container no longer exists; container logs unavailable." >&2
  fi
  echo "Smoke test failed; attempting rollback." >&2
  if [[ -n "$RENAMED_CONTAINER" ]]; then
    restore_preserved_container || true
  else
    docker image tag "$OLD_IMAGE_ID" "$OLD_IMAGE_NAME"
    "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate "$SERVICE" || true
  fi
  echo "Rollback attempted. Inspect this log and the web container logs before retrying." >&2
  exit 7
fi
