#!/usr/bin/env bash
# Smoke-check публичного REST API и health (без auth).
#
# Dev: localhost:8000; prod PROD: API_SMOKE_BASE=http://127.0.0.1:8001 или :8002
#
# Catalog требует active mapping release в БД (норма на prod).
# Локально без seed — 503 на /catalog/taxonomy; API_SMOKE_SKIP_CATALOG=1 чтобы пропустить.
set -euo pipefail
BASE="${API_SMOKE_BASE:-http://localhost:8000}"
API_SMOKE_SKIP_CATALOG="${API_SMOKE_SKIP_CATALOG:-0}"

API_SMOKE_CURL_MAX_TIME="${API_SMOKE_CURL_MAX_TIME:-25}"

check() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$API_SMOKE_CURL_MAX_TIME" "$1")
  printf "%s %s\n" "$code" "$1"
  [[ "$code" =~ ^(200|204)$ ]]
}

echo "== health =="
check "$BASE/health"
check "$BASE/ready"

if [[ "$API_SMOKE_SKIP_CATALOG" = "1" ]]; then
  echo "== catalog (skipped: API_SMOKE_SKIP_CATALOG=1) =="
else
  echo "== catalog =="
  check "$BASE/catalog/labels"
  check "$BASE/catalog/taxonomy"
  check "$BASE/products?limit=1"
  check "$BASE/products/count"
  check "$BASE/products/subcategories"
fi

echo "== cart (guest) =="
check "$BASE/cart/me"

echo "OK"
