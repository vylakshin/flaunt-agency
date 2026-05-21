#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/twitch_guess_game_mvp"
SERVICE_NAME="twitch-guess-game.service"
LOG_PREFIX="[twitch-guess-game-auto-update]"

cd "$REPO_DIR"

echo "$LOG_PREFIX checking origin/main"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "$LOG_PREFIX tracked local changes found; skipping update"
  git status --short
  exit 0
fi

before="$(git rev-parse HEAD)"
git fetch origin main
remote="$(git rev-parse origin/main)"

if [[ "$before" == "$remote" ]]; then
  echo "$LOG_PREFIX already up to date at $before"
  exit 0
fi

git merge --ff-only origin/main
after="$(git rev-parse HEAD)"
changed_files="$(git diff --name-only "$before" "$after")"

echo "$LOG_PREFIX updated $before -> $after"

if grep -qE '^requirements\.txt$' <<<"$changed_files"; then
  echo "$LOG_PREFIX installing Python dependencies"
  "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

if grep -qE '^(frontend/package(-lock)?\.json|frontend/src/|frontend/index\.html|frontend/vite\.config\.(ts|js)|frontend/tsconfig|frontend/components\.json)' <<<"$changed_files"; then
  echo "$LOG_PREFIX building frontend"
  cd "$REPO_DIR/frontend"
  if [[ ! -d node_modules ]] || grep -qE '^frontend/package(-lock)?\.json$' <<<"$changed_files"; then
    /opt/node24/bin/npm install
  fi
  /opt/node24/bin/npm run build
  cd "$REPO_DIR"
fi

echo "$LOG_PREFIX restarting $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "$LOG_PREFIX done"
