#!/usr/bin/env bash
# Копирует Playwright session JSON с локального ПК на prod-сервер.
# DOM 1+1: session-1 и session-2. Default session/ — только если файл есть (availability).
# Lanes в админке: mtime lane-файлов читает API — см. тома session-1/2 у api-* в docker-compose.prod.yml.
#
# Из корня репозитория:
#   make push-scraper-sessions
#   ./scripts/push_scraper_session.sh
#
# Один раз: cp scripts/deploy.env.example scripts/deploy.env
# Или: DEPLOY_SSH=user@server DEPLOY_PROJECT_DIR=/opt/shopstore ./scripts/push_scraper_session.sh
#
# Переменные:
#   DEPLOY_SSH              — user@host
#   DEPLOY_PROJECT_DIR      — каталог проекта на сервере (по умолчанию /opt/shopstore)
#   RESTART_SCRAPER_WORKERS — 1 = перезапустить worker-dom-1 и worker-dom-2 (по умолчанию 1)
#   COMPOSE_FILE            — docker-compose.prod.yml
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/scripts/deploy.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/scripts/deploy.env"
  set +a
fi

DEPLOY_PROJECT_DIR="${DEPLOY_PROJECT_DIR:-/opt/shopstore}"
RESTART_SCRAPER_WORKERS="${RESTART_SCRAPER_WORKERS:-1}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

LANE1_REL="src/scraper/infrastructure/session-1/storage_state.json"
LANE2_REL="src/scraper/infrastructure/session-2/storage_state.json"
DEFAULT_REL="src/scraper/infrastructure/session/storage_state.json"

if [[ -z "${DEPLOY_SSH:-}" ]]; then
  echo "ERROR: задайте DEPLOY_SSH=user@host или создайте scripts/deploy.env" >&2
  exit 1
fi

LANE1_LOCAL="$ROOT/$LANE1_REL"
LANE2_LOCAL="$ROOT/$LANE2_REL"
DEFAULT_LOCAL="$ROOT/$DEFAULT_REL"

missing=0
if [[ ! -f "$LANE1_LOCAL" ]]; then
  echo "ERROR: нет $LANE1_LOCAL" >&2
  echo "Сначала: make login-lane LANE=1" >&2
  missing=1
fi
if [[ ! -f "$LANE2_LOCAL" ]]; then
  echo "ERROR: нет $LANE2_LOCAL" >&2
  echo "Сначала: make login-lane LANE=2" >&2
  missing=1
fi
if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

upload() {
  local local_file="$1"
  local remote_rel="$2"
  local remote_dir="${DEPLOY_PROJECT_DIR}/${remote_rel%/*}"
  echo "Upload: $local_file"
  echo "    -> ${DEPLOY_SSH}:${DEPLOY_PROJECT_DIR}/${remote_rel}"
  ssh "$DEPLOY_SSH" "mkdir -p '$remote_dir'"
  scp "$local_file" "${DEPLOY_SSH}:${DEPLOY_PROJECT_DIR}/${remote_rel}"
}

upload "$LANE1_LOCAL" "$LANE1_REL"
upload "$LANE2_LOCAL" "$LANE2_REL"

if [[ -f "$DEFAULT_LOCAL" ]]; then
  upload "$DEFAULT_LOCAL" "$DEFAULT_REL"
fi

echo "OK: session uploaded"

if [[ "$RESTART_SCRAPER_WORKERS" == "1" ]]; then
  echo "Restarting worker-dom-1 worker-dom-2..."
  ssh "$DEPLOY_SSH" "cd '$DEPLOY_PROJECT_DIR' && docker compose -f '$COMPOSE_FILE' restart worker-dom-1 worker-dom-2"
  echo "OK: workers restarted"
fi
