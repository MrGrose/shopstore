#!/usr/bin/env bash
# PROD gate: preflight, проверка образа, wait-ready (без git pull).
#
# Команды: preflight | verify-image-built | verify-image-running | wait-ready
#
# Env:
#   PROD_PROD_ALLOW_DIRTY=1     — грязное дерево (только локально)
#   PROD_PROD_REQUIRE_ORIGIN=1  — HEAD == origin/main (после git fetch)
#   PROD_API_WAIT_TIMEOUT=210  — таймаут readiness (сек)
#   PROD_API_WAIT_INTERVAL=3   — интервал опроса (сек)
#   API_WAIT_BASE              — base URL (по умолч. http://127.0.0.1:8001)
#   COMPOSE_FILE               — compose (по умолч. docker-compose.prod.yml)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
IMAGE_NAME="${PROD_PROD_IMAGE:-shopstore-api}"
ALLOW_DIRTY="${PROD_PROD_ALLOW_DIRTY:-0}"
REQUIRE_ORIGIN="${PROD_PROD_REQUIRE_ORIGIN:-0}"
WAIT_TIMEOUT="${PROD_API_WAIT_TIMEOUT:-210}"
WAIT_INTERVAL="${PROD_API_WAIT_INTERVAL:-3}"
WAIT_BASE="${API_WAIT_BASE:-http://127.0.0.1:8001}"

image_id_for_tag() {
  docker image inspect -f '{{.Id}}' "$IMAGE_NAME" 2>/dev/null
}

cmd_preflight() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "FAIL not a git repository: $ROOT" >&2
    return 1
  fi

  local head branch dirty
  head="$(git rev-parse HEAD)"
  branch="$(git rev-parse --abbrev-ref HEAD)"
  dirty="$(git status --porcelain)"

  echo "git branch=$branch"
  echo "git HEAD=$head"
  git log -1 --oneline

  if [[ -n "$dirty" ]]; then
    if [[ "$ALLOW_DIRTY" == "1" ]]; then
      echo "WARN dirty working tree allowed (PROD_PROD_ALLOW_DIRTY=1)" >&2
    else
      echo "FAIL uncommitted changes — commit/stash or set PROD_PROD_ALLOW_DIRTY=1 for local dev" >&2
      git status --short >&2
      return 1
    fi
  else
    echo "OK clean working tree"
  fi

  if [[ "$REQUIRE_ORIGIN" == "1" ]]; then
    if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
      echo "FAIL origin/main not found — run: git fetch origin" >&2
      return 1
    fi
    local origin_main
    origin_main="$(git rev-parse origin/main)"
    echo "git origin/main=$origin_main"
    if [[ "$head" != "$origin_main" ]]; then
      echo "FAIL HEAD != origin/main — pull/rebase before deploy" >&2
      return 1
    fi
    echo "OK HEAD matches origin/main"
  fi

  echo "OK preflight"
}

cmd_verify_image_built() {
  local image_id
  image_id="$(image_id_for_tag || true)"
  if [[ -z "$image_id" ]]; then
    echo "FAIL image tag not found: $IMAGE_NAME (run prod-migrate or compose build api-blue first)" >&2
    return 1
  fi
  echo "OK built image $IMAGE_NAME Id=$image_id"
}

cmd_verify_image_running() {
  local service="${1:-api-blue}"
  local image_id container_id running_id
  image_id="$(image_id_for_tag || true)"
  if [[ -z "$image_id" ]]; then
    echo "FAIL image tag not found: $IMAGE_NAME" >&2
    return 1
  fi

  container_id="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null | head -n1 || true)"
  if [[ -z "$container_id" ]]; then
    echo "FAIL no running container for service $service" >&2
    return 1
  fi

  running_id="$(docker inspect -f '{{.Image}}' "$container_id")"
  echo "service=$service container=$container_id"
  echo "tag image Id=$image_id"
  echo "running image Id=$running_id"

  if [[ "$running_id" != "$image_id" ]]; then
    echo "FAIL container image differs from tag $IMAGE_NAME — rebuild and recreate $service" >&2
    return 1
  fi
  echo "OK running $service uses $IMAGE_NAME"
}

http_ok() {
  local url="$1"
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")"
  [[ "$code" == "200" ]]
}

cmd_wait_ready() {
  local base="${1:-$WAIT_BASE}"
  local elapsed=0
  local last_err="connection failed"

  echo "==> waiting for readiness at $base (timeout=${WAIT_TIMEOUT}s interval=${WAIT_INTERVAL}s)"

  while (( elapsed <= WAIT_TIMEOUT )); do
    if http_ok "$base/health"; then
      if http_ok "$base/ready"; then
        echo "OK readiness $base/ready (${elapsed}s)"
        return 0
      fi
      last_err="/ready not HTTP 200"
    else
      last_err="/health not HTTP 200"
    fi
    sleep "$WAIT_INTERVAL"
    elapsed=$((elapsed + WAIT_INTERVAL))
  done

  echo "FAIL readiness timeout after ${WAIT_TIMEOUT}s — last: $last_err" >&2
  echo "Hint: docker compose -f $COMPOSE_FILE logs --tail=80 $(
    case "$base" in
      *:8002*) echo api-green ;;
      *) echo api-blue ;;
    esac
  )" >&2
  return 1
}

usage() {
  echo "Usage: $0 {preflight|verify-image-built|verify-image-running [service]|wait-ready [base_url]}" >&2
  exit 2
}

main="${1:-}"
shift || true

case "$main" in
  preflight) cmd_preflight ;;
  verify-image-built) cmd_verify_image_built ;;
  verify-image-running) cmd_verify_image_running "${1:-api-blue}" ;;
  wait-ready) cmd_wait_ready "${1:-$WAIT_BASE}" ;;
  *) usage ;;
esac
