#!/usr/bin/env bash
# Production PROD rollback: start previous color if needed, Caddy cutover, public verify.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=prod_prod_lib.sh
source "${ROOT}/scripts/prod_prod_lib.sh"

export COMPOSE_FILE="$PROD_PROD_COMPOSE_FILE"

main() {
  local active rollback active_port rollback_port
  local active_container rollback_container

  prod_prod_acquire_lock

  prod_prod_log "PROD rollback start (root=$ROOT)"
  prod_prod_log "Caddyfile=$PROD_PROD_CADDYFILE domain=$PROD_PROD_DOMAIN"

  active="$(prod_prod_active_color_from_caddy)"
  rollback="$(prod_prod_standby_color "$active")"
  active_port="$(prod_prod_port_for_color "$active")"
  rollback_port="$(prod_prod_port_for_color "$rollback")"
  active_container="$(prod_prod_container_for_color "$active")"
  rollback_container="$(prod_prod_container_for_color "$rollback")"

  prod_prod_log "current=${active} (:${active_port}) rollback_target=${rollback} (:${rollback_port})"

  prod_prod_verify_caddy_upstream_port "$active_port"
  prod_prod_print_api_state "$active"
  prod_prod_print_api_state "$rollback"

  prod_prod_log "phase 1/3: ensure rollback API running"
  prod_prod_ensure_api_running "$rollback"
  prod_prod_wait_color_ready "$rollback"
  prod_prod_local_smoke_color "$rollback"

  prod_prod_log "phase 2/3: Caddy cutover :${active_port} -> :${rollback_port}"
  if ! prod_prod_caddy_cutover_ports "$active_port" "$rollback_port"; then
    prod_prod_fail "Caddy rollback cutover failed"
  fi

  prod_prod_log "phase 3/3: public verification on ${rollback}"
  if ! prod_prod_verify_public_hits_container "$rollback_container"; then
    echo "FAIL: public rollback verification failed — restoring Caddy backup ${PROD_PROD_LAST_CADDY_BACKUP}" >&2
    if ! prod_prod_restore_caddy_backup "$PROD_PROD_LAST_CADDY_BACKUP"; then
      prod_prod_fail "rollback aborted after cutover and Caddy auto-restore failed — manual intervention required"
    fi
    prod_prod_fail "rollback aborted after cutover; Caddy restored to :${active_port}"
  fi

  prod_prod_write_active_color "$rollback"

  echo ""
  echo "OK prod-prod-rollback complete"
  echo "  active_color=${rollback} (Caddy :${rollback_port})"
  echo "  failed color ${active} (${active_container}) left running"
  echo "  Caddy backup=${PROD_PROD_LAST_CADDY_BACKUP}"
  prod_prod_print_api_state "$rollback"
  prod_prod_print_api_state "$active"
}

main "$@"
