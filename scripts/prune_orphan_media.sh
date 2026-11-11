#!/usr/bin/env bash
# Удаляет сироты в media/products (файлы без ссылок в БД).
#
# Prod:
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/prune_orphan_media.sh
#   API_SERVICE=api-blue ./scripts/prune_orphan_media.sh --dry-run
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API_SERVICE="${API_SERVICE:-api-blue}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found" >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" exec -T "$API_SERVICE" uv run python scripts/prune_orphan_media.py "$@"
