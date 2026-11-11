#!/usr/bin/env bash
# Ежедневный снимок PostgreSQL (gzip). Старые файлы удаляются (по умолчанию старше 7 дней).
#
# Запуск из корня репозитория:
#   ./scripts/backup_postgres.sh
#
# Cron (ежедневно в 02:55):
#   55 2 * * * cd /path/to/Shopstore && ./scripts/backup_postgres.sh >> /var/log/shopstore-backup.log 2>&1
#
# Переменные:
#   COMPOSE_FILE            — docker-compose файл (по умолчанию docker-compose.prod.yml)
#   BACKUP_DIR              — каталог бэкапов (по умолчанию ./backups)
#   BACKUP_RETENTION_DAYS   — сколько дней хранить (по умолчанию 7)
#   BACKUP_MAX_RETRIES      — попыток pg_dump при сбое (по умолчанию 6)
#   BACKUP_RETRY_DELAY_SEC  — пауза между попытками, сек (по умолчанию 10)
#   BACKUP_LOG_TIMESTAMPS   — префикс даты/времени в stdout (1 — да, 0 — нет; по умолчанию 1)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
MAX_RETRIES="${BACKUP_MAX_RETRIES:-6}"
RETRY_DELAY_SEC="${BACKUP_RETRY_DELAY_SEC:-10}"
LOG_TIMESTAMPS="${BACKUP_LOG_TIMESTAMPS:-1}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/shopstore_${STAMP}.sql.gz"

if ! [[ "$MAX_RETRIES" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: BACKUP_MAX_RETRIES must be a positive integer, got: $MAX_RETRIES" >&2
  exit 1
fi
if ! [[ "$RETRY_DELAY_SEC" =~ ^[0-9]+$ ]]; then
  echo "ERROR: BACKUP_RETRY_DELAY_SEC must be a non-negative integer, got: $RETRY_DELAY_SEC" >&2
  exit 1
fi

if [[ "$LOG_TIMESTAMPS" == "1" ]]; then
  exec > >(awk '{ print strftime("%Y-%m-%dT%H:%M:%S%z"), $0; fflush(); }') 2>&1
fi

run_backup_once() {
  docker compose -f "$COMPOSE_FILE" exec -T db \
    sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 || return 1
  # Не source .env — значения с пробелами (SHIPPING_ESTIMATE_FALLBACK=до 14 дней) ломают bash.
  docker compose -f "$COMPOSE_FILE" exec -T db \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip >"$OUT"
}

echo "Starting PostgreSQL backup to $OUT"

attempt=1
while true; do
  if run_backup_once; then
    echo "OK: $OUT"
    break
  fi
  rm -f "$OUT"
  if [[ "$attempt" -ge "$MAX_RETRIES" ]]; then
    echo "ERROR: backup failed after ${MAX_RETRIES} attempt(s)" >&2
    exit 1
  fi
  echo "WARN: backup attempt ${attempt}/${MAX_RETRIES} failed, retrying in ${RETRY_DELAY_SEC}s"
  sleep "$RETRY_DELAY_SEC"
  attempt=$((attempt + 1))
done

deleted=0
while IFS= read -r -d '' old; do
  rm -f "$old"
  deleted=$((deleted + 1))
done < <(find "$OUT_DIR" -maxdepth 1 -type f -name 'shopstore_*.sql.gz' -mtime +"${RETENTION_DAYS}" -print0 2>/dev/null || true)

if [[ "$deleted" -gt 0 ]]; then
  echo "Pruned $deleted backup(s) older than ${RETENTION_DAYS} day(s) in $OUT_DIR"
fi
