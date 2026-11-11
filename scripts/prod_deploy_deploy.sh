#!/usr/bin/env bash
# Full production PROD deploy: gate inactive color + Caddy cutover + public verify.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=prod_prod_lib.sh
source "${ROOT}/scripts/prod_prod_lib.sh"

export PROD_PROD_REQUIRE_ORIGIN="${PROD_PROD_REQUIRE_ORIGIN:-1}"
export COMPOSE_FILE="$PROD_PROD_COMPOSE_FILE"

main() {
  local active standby active_port standby_port file_color
  local active_container standby_container

  prod_prod_acquire_lock

  prod_prod_log "PROD deploy start (root=$ROOT)"
  prod_prod_log "Caddyfile=$PROD_PROD_CADDYFILE domain=$PROD_PROD_DOMAIN"

  active="$(prod_prod_active_color_from_caddy)"
  standby="$(prod_prod_standby_color "$active")"
  active_port="$(prod_prod_port_for_color "$active")"
  standby_port="$(prod_prod_port_for_color "$standby")"
  active_container="$(prod_prod_container_for_color "$active")"
  standby_container="$(prod_prod_container_for_color "$standby")"

  prod_prod_log "active=${active} (:${active_port}) standby=${standby} (:${standby_port})"

  if file_color="$(prod_prod_read_active_color_file 2>/dev/null || true)" && [[ -n "$file_color" ]]; then
    if [[ "$file_color" != "$active" ]]; then
      echo "WARN: .deploy/active_color=${file_color} != Caddy active=${active} (Caddy wins)" >&2
    fi
  fi

  prod_prod_verify_caddy_upstream_port "$active_port"
  prod_prod_print_api_state "$active"
  prod_prod_print_api_state "$standby"

  prod_prod_log "phase 1/4: gate standby (${standby})"
  prod_prod_run_gate "$standby"

  prod_prod_log "phase 2/4: Caddy cutover :${active_port} -> :${standby_port}"
  prod_prod_caddy_cutover_ports "$active_port" "$standby_port"

  prod_prod_log "phase 3/4: public verification on ${standby}"
  if ! prod_prod_verify_public_hits_container "$standby_container"; then
    echo "FAIL: public verification failed — restoring Caddy backup ${PROD_PROD_LAST_CADDY_BACKUP}" >&2
    if ! prod_prod_restore_caddy_backup "$PROD_PROD_LAST_CADDY_BACKUP"; then
      prod_prod_fail "deploy aborted after cutover and Caddy auto-restore failed — manual intervention required"
    fi
    prod_prod_fail "deploy aborted after cutover; Caddy restored to :${active_port}"
  fi

  prod_prod_log "phase 4/4: drain previous active ${active}"
  prod_prod_drain_api_color "$active"

  if prod_prod_skip_drain; then
    prod_prod_log "PROD_PROD_SKIP_DRAIN=1 — both APIs may remain running (${active_container}, ${standby_container})"
  fi

  prod_prod_log "post-drain check: new active ${standby}"
  prod_prod_assert_api_running "$standby"

  prod_prod_write_active_color "$standby"

  echo ""
  echo "OK prod-prod-deploy complete"
  echo "  active_color=${standby} (Caddy :${standby_port})"
  if prod_prod_skip_drain; then
    echo "  previous ${active} (${active_container}) left running — PROD_PROD_SKIP_DRAIN=1"
  else
    echo "  previous ${active} (${active_container}) drained (container preserved for rollback)"
  fi
  echo "  Caddy backup=${PROD_PROD_LAST_CADDY_BACKUP}"
  prod_prod_print_api_state "$standby"
  prod_prod_print_api_state "$active"
}

main "$@"
