#!/usr/bin/env bash
# Shared helpers for production PROD deploy/rollback (host Caddy + blue/green API).
set -euo pipefail

PROD_PROD_ROOT="${PROD_PROD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROD_PROD_CADDYFILE="${PROD_PROD_CADDYFILE:-/etc/caddy/Caddyfile}"
PROD_PROD_ACTIVE_COLOR_FILE="${PROD_PROD_ACTIVE_COLOR_FILE:-${PROD_PROD_ROOT}/.deploy/active_color}"
PROD_PROD_LOCK_FILE="${PROD_PROD_LOCK_FILE:-${PROD_PROD_ROOT}/.deploy/prod.lock}"
PROD_PROD_DOMAIN="${PROD_PROD_DOMAIN:-https://shopstore.pro}"
PROD_PROD_COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PROD_PROD_LAST_CADDY_BACKUP=""

prod_prod_log() {
  echo "==> $*"
}

prod_prod_fail() {
  echo "FAIL: $*" >&2
  exit 1
}

prod_prod_port_for_color() {
  case "$1" in
    blue) echo 8001 ;;
    green) echo 8002 ;;
    *) prod_prod_fail "unknown color: $1 (expected blue|green)" ;;
  esac
}

prod_prod_color_for_port() {
  case "$1" in
    8001) echo blue ;;
    8002) echo green ;;
    *) prod_prod_fail "unknown API port: $1 (expected 8001|8002)" ;;
  esac
}

prod_prod_service_for_color() {
  case "$1" in
    blue) echo api-blue ;;
    green) echo api-green ;;
    *) prod_prod_fail "unknown color: $1" ;;
  esac
}

prod_prod_container_for_color() {
  case "$1" in
    blue) echo shopstore-api-blue-1 ;;
    green) echo shopstore-api-green-1 ;;
    *) prod_prod_fail "unknown color: $1" ;;
  esac
}

prod_prod_standby_color() {
  case "$1" in
    blue) echo green ;;
    green) echo blue ;;
    *) prod_prod_fail "unknown active color: $1" ;;
  esac
}

# Строки site block shopstore.pro (API blue/green), без CDN.
prod_prod_caddy_api_block_text() {
  local file="${1:-$PROD_PROD_CADDYFILE}"
  sed -n '/^shopstore\.pro/,/^[[:space:]]*}[[:space:]]*$/p' "$file"
}

# Меняет только API upstream в shopstore.pro block (CDN :8888 не трогает).
prod_prod_caddy_apply_api_cutover_sed() {
  local from_port="$1"
  local to_port="$2"
  local file="$3"
  sed -e '/^shopstore\.pro/,/^[[:space:]]*}[[:space:]]*$/ s/reverse_proxy 127\.0\.0\.1:'"${from_port}"'/reverse_proxy 127.0.0.1:'"${to_port}"'/' \
    "$file"
}

prod_prod_read_caddy_upstream_port() {
  local block line port count
  block="$(prod_prod_caddy_api_block_text)"
  if [[ -z "$block" ]]; then
    prod_prod_fail "no shopstore.pro site block in $PROD_PROD_CADDYFILE"
  fi
  count="$(
    grep -cE 'reverse_proxy[[:space:]]+127\.0\.0\.1:(8001|8002)' <<<"$block" || true
  )"
  if [[ "$count" -ne 1 ]]; then
    prod_prod_fail "expected exactly one API reverse_proxy 127.0.0.1:8001|8002 in shopstore.pro block (found ${count})"
  fi
  line="$(
    grep -E 'reverse_proxy[[:space:]]+127\.0\.0\.1:(8001|8002)' <<<"$block" | head -n1 || true
  )"
  port="$(sed -n 's/.*127\.0\.0\.1:\(800[12]\).*/\1/p' <<<"$line" | head -n1)"
  if [[ -z "$port" ]]; then
    prod_prod_fail "could not parse API upstream port from shopstore.pro block"
  fi
  echo "$port"
}

prod_prod_verify_caddy_upstream_port() {
  local expected_port="$1"
  local block count
  block="$(prod_prod_caddy_api_block_text)"
  if [[ -z "$block" ]]; then
    prod_prod_fail "no shopstore.pro site block in $PROD_PROD_CADDYFILE"
  fi
  count="$(
    grep -cE "reverse_proxy[[:space:]]+127\.0\.0\.1:${expected_port}" <<<"$block" || true
  )"
  if [[ "$count" -ne 1 ]]; then
    prod_prod_fail "expected exactly one reverse_proxy 127.0.0.1:${expected_port} in shopstore.pro block (found ${count})"
  fi
}

prod_prod_active_color_from_caddy() {
  prod_prod_color_for_port "$(prod_prod_read_caddy_upstream_port)"
}

prod_prod_read_active_color_file() {
  if [[ ! -f "$PROD_PROD_ACTIVE_COLOR_FILE" ]]; then
    return 1
  fi
  tr -d '[:space:]' <"$PROD_PROD_ACTIVE_COLOR_FILE"
}

prod_prod_write_active_color() {
  local color="$1"
  case "$color" in
    blue | green) ;;
    *) prod_prod_fail "refusing to write invalid active_color: $color" ;;
  esac
  mkdir -p "$(dirname "$PROD_PROD_ACTIVE_COLOR_FILE")"
  local tmp="${PROD_PROD_ACTIVE_COLOR_FILE}.tmp.$$"
  printf '%s\n' "$color" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$PROD_PROD_ACTIVE_COLOR_FILE"
  prod_prod_log "active_color=$color"
}

prod_prod_acquire_lock() {
  mkdir -p "$(dirname "$PROD_PROD_LOCK_FILE")"
  exec 9>"$PROD_PROD_LOCK_FILE"
  if ! flock -n 9; then
    prod_prod_fail "another PROD deploy/rollback is in progress (lock: $PROD_PROD_LOCK_FILE)"
  fi
}

prod_prod_caddy_backup_path() {
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  echo "${PROD_PROD_CADDYFILE}.backup.${ts}"
}

prod_prod_verify_caddy_backup_port() {
  local backup_path="$1"
  local expected_port="$2"
  local block
  if [[ ! -f "$backup_path" ]]; then
    prod_prod_fail "Caddy backup missing: $backup_path"
  fi
  block="$(prod_prod_caddy_api_block_text "$backup_path")"
  if ! grep -qE "reverse_proxy[[:space:]]+127\.0\.0\.1:${expected_port}" <<<"$block"; then
    prod_prod_fail "Caddy backup $backup_path shopstore.pro block missing upstream :${expected_port}"
  fi
}

prod_prod_caddy_cutover_ports() {
  local from_port="$1"
  local to_port="$2"
  local staging backup

  if [[ "$from_port" == "$to_port" ]]; then
    prod_prod_fail "Caddy cutover from :${from_port} to same port"
  fi

  prod_prod_verify_caddy_upstream_port "$from_port"

  staging="${PROD_PROD_CADDYFILE}.staging"
  backup="$(prod_prod_caddy_backup_path)"
  PROD_PROD_LAST_CADDY_BACKUP="$backup"

  cp "$PROD_PROD_CADDYFILE" "$staging"
  prod_prod_caddy_apply_api_cutover_sed "$from_port" "$to_port" "$staging" >"${staging}.new"
  mv "${staging}.new" "$staging"

  if ! prod_prod_caddy_api_block_text "$staging" | grep -qE "reverse_proxy[[:space:]]+127\.0\.0\.1:${to_port}"; then
    rm -f "$staging"
    prod_prod_fail "staging shopstore.pro block missing API upstream :${to_port}"
  fi
  if prod_prod_caddy_api_block_text "$staging" | grep -qE "reverse_proxy[[:space:]]+127\.0\.0\.1:${from_port}"; then
    rm -f "$staging"
    prod_prod_fail "staging shopstore.pro block still contains API upstream :${from_port}"
  fi

  prod_prod_log "validate staging Caddyfile (:${from_port} -> :${to_port})"
  if ! caddy validate --config "$staging" --adapter caddyfile >/dev/null; then
    rm -f "$staging"
    prod_prod_fail "caddy validate rejected staging config"
  fi

  cp "$PROD_PROD_CADDYFILE" "$backup"
  prod_prod_verify_caddy_backup_port "$backup" "$from_port"
  prod_prod_log "Caddy backup=$backup"

  mv "$staging" "$PROD_PROD_CADDYFILE"

  prod_prod_log "validate active Caddyfile"
  if ! caddy validate --config "$PROD_PROD_CADDYFILE" --adapter caddyfile >/dev/null; then
    cp "$backup" "$PROD_PROD_CADDYFILE"
    caddy validate --config "$PROD_PROD_CADDYFILE" --adapter caddyfile >/dev/null || true
    prod_prod_fail "active Caddy validate failed — restored backup $backup"
  fi

  prod_prod_log "reload caddy"
  if ! systemctl reload caddy; then
    cp "$backup" "$PROD_PROD_CADDYFILE"
    systemctl reload caddy || true
    prod_prod_fail "systemctl reload caddy failed — restored backup $backup"
  fi

  if ! systemctl is-active --quiet caddy; then
    prod_prod_fail "caddy is not active after reload"
  fi

  prod_prod_verify_caddy_upstream_port "$to_port"
  prod_prod_log "Caddy upstream now 127.0.0.1:${to_port}"
}

prod_prod_restore_caddy_backup() {
  local backup_path="${1:-$PROD_PROD_LAST_CADDY_BACKUP}"
  if [[ -z "$backup_path" || ! -f "$backup_path" ]]; then
    prod_prod_fail "no Caddy backup available to restore"
  fi
  cp "$backup_path" "$PROD_PROD_CADDYFILE"
  if ! caddy validate --config "$PROD_PROD_CADDYFILE" --adapter caddyfile >/dev/null; then
    prod_prod_fail "restored Caddy backup failed validate: $backup_path"
  fi
  if ! systemctl reload caddy; then
    prod_prod_fail "restored Caddy backup but systemctl reload failed: $backup_path"
  fi
  prod_prod_log "restored Caddy from $backup_path"
}

prod_prod_public_smoke() {
  local base="$PROD_PROD_DOMAIN"
  local path code
  local paths=(
    "/health"
    "/ready"
    "/catalog/labels"
    "/catalog/taxonomy"
    "/products?limit=1"
  )

  prod_prod_log "public smoke via $base"
  for path in "${paths[@]}"; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 25 "${base}${path}" || echo FAIL)"
    echo "  ${path} -> HTTP ${code}"
    if [[ "$code" != "200" ]]; then
      return 1
    fi
  done
  return 0
}

prod_prod_local_smoke_color() {
  local color="$1"
  local port
  port="$(prod_prod_port_for_color "$color")"
  prod_prod_log "local smoke api-${color} :${port}"
  API_SMOKE_BASE="http://127.0.0.1:${port}" COMPOSE_FILE="$PROD_PROD_COMPOSE_FILE" \
    "${PROD_PROD_ROOT}/scripts/api_smoke.sh"
}

prod_prod_log_lines() {
  local container="$1"
  docker logs "$container" 2>&1 | wc -l | tr -d ' '
}

prod_prod_public_smoke_log_delta_sufficient() {
  local delta="$1"
  (( delta >= 3 ))
}

prod_prod_logs_contain_public_path_hits() {
  local logs="$1"
  grep -qE 'GET /(health|ready|catalog|products)' <<<"$logs"
}

prod_prod_verify_public_hits_container() {
  local container="$1"
  local before after delta recent_logs
  before="$(prod_prod_log_lines "$container")"
  if ! prod_prod_public_smoke; then
    return 1
  fi
  sleep 1
  after="$(prod_prod_log_lines "$container")"
  delta=$((after - before))
  prod_prod_log "${container} log lines +${delta} after public smoke (before=${before} after=${after})"
  if ! prod_prod_public_smoke_log_delta_sufficient "$delta"; then
    echo "FAIL: insufficient evidence public traffic reached ${container} (delta=${delta})" >&2
    return 1
  fi
  recent_logs="$(docker logs --since 2m "$container" 2>&1)" || recent_logs=""
  if ! prod_prod_logs_contain_public_path_hits "$recent_logs"; then
    echo "FAIL: no recent public path hits in ${container} logs" >&2
    return 1
  fi
  return 0
}

prod_prod_api_running() {
  local color="$1"
  local container
  container="$(prod_prod_container_for_color "$color")"
  [[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || echo false)" == "true" ]]
}


prod_prod_skip_drain() {
  [[ "${PROD_PROD_SKIP_DRAIN:-0}" == "1" ]]
}

prod_prod_assert_api_running() {
  local color="$1"
  local container
  container="$(prod_prod_container_for_color "$color")"
  if ! prod_prod_api_running "$color"; then
    prod_prod_fail "expected ${container} to be running"
  fi
}

prod_prod_drain_api_color() {
  local color="$1"
  local container
  container="$(prod_prod_container_for_color "$color")"

  if prod_prod_skip_drain; then
    prod_prod_log "skip drain ${color} (${container}) — PROD_PROD_SKIP_DRAIN=1"
    return 0
  fi

  caddy_active="$(prod_prod_active_color_from_caddy)"
  if [[ "$color" == "$caddy_active" ]]; then
    prod_prod_fail "refusing to drain current Caddy active color: ${color}"
  fi

  if ! prod_prod_api_running "$color"; then
    prod_prod_log "${container} already stopped — nothing to drain"
    return 0
  fi

  prod_prod_log "drain previous active ${color} (${container})"
  if ! docker stop "$container"; then
    prod_prod_fail "failed to stop ${container} — Caddy remains on new active; ${container} still running; manual intervention required"
  fi

  if prod_prod_api_running "$color"; then
    prod_prod_fail "${container} still running after docker stop — Caddy remains on new active; manual intervention required"
  fi

  prod_prod_log "drained ${container}"
}

prod_prod_ensure_api_running() {
  local color="$1"
  local service port container
  service="$(prod_prod_service_for_color "$color")"
  port="$(prod_prod_port_for_color "$color")"
  container="$(prod_prod_container_for_color "$color")"

  if prod_prod_api_running "$color"; then
    prod_prod_log "${container} already running"
    return 0
  fi

  prod_prod_log "starting ${service} (:${port})"
  if [[ "$color" == green ]]; then
    docker compose -f "$PROD_PROD_COMPOSE_FILE" --profile api-standby up -d --no-deps --no-recreate "$service"
  else
    docker compose -f "$PROD_PROD_COMPOSE_FILE" up -d --no-deps --no-recreate "$service"
  fi

  if ! prod_prod_api_running "$color"; then
    if docker ps -aq -f "name=^${container}$" | grep -q .; then
      docker start "$container" >/dev/null
    fi
  fi

  if ! prod_prod_api_running "$color"; then
    prod_prod_fail "could not start ${service} (${container})"
  fi
}

prod_prod_wait_color_ready() {
  local color="$1"
  local port
  port="$(prod_prod_port_for_color "$color")"
  API_WAIT_BASE="http://127.0.0.1:${port}" COMPOSE_FILE="$PROD_PROD_COMPOSE_FILE" \
    "${PROD_PROD_ROOT}/scripts/prod_prod_gate.sh" wait-ready "http://127.0.0.1:${port}"
}

prod_prod_run_gate() {
  local color="$1"
  prod_prod_log "gate inactive color: ${color}"
  case "$color" in
    blue) make -C "$PROD_PROD_ROOT" prod-prod-gate-blue ;;
    green) make -C "$PROD_PROD_ROOT" prod-prod-gate-green ;;
    *) prod_prod_fail "unknown gate color: $color" ;;
  esac
}

prod_prod_print_api_state() {
  local color="$1"
  local container
  container="$(prod_prod_container_for_color "$color")"
  docker inspect "$container" --format \
    'color='"${color}"' status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}} restarts={{.RestartCount}}' \
    2>/dev/null || echo "color=${color} status=missing"
}
