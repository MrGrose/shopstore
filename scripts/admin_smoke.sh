#!/usr/bin/env bash
# Smoke-check admin routes and static assets (no auth required).
set -euo pipefail
BASE="${ADMIN_SMOKE_BASE:-http://localhost:8000}"

check() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$1")
  printf "%s %s\n" "$code" "$1"
  [[ "$code" =~ ^(200|302|303|307)$ ]]
}

echo "== static =="
check "$BASE/static/site/css/admin.css?v=admin-design-5"
check "$BASE/static/site/js/admin.js?v=admin-design-3"

echo "== pages (expect 200 login, 302 others without session) =="
check "$BASE/internal/admin/login"
for p in dashboard orders products customers prices margins promos parsing; do
  check "$BASE/internal/admin/$p"
done

echo "OK"
