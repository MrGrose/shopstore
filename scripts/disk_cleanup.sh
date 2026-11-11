#!/usr/bin/env bash
# Очистка логов и временных файлов, если диск заполнен >= порога (по умолчанию 80%).
# Ничего не делает, пока использование ниже порога.
#
# Запуск:
#   ./scripts/disk_cleanup.sh
#
# Cron (каждый час — скрипт сам выйдет, если диск не переполнен):
#   0 * * * * cd /path/to/Shopstore && ./scripts/disk_cleanup.sh >> /var/log/shopstore-disk-cleanup.log 2>&1
#
# Переменные:
#   DISK_MOUNT              — точка монтирования для проверки (по умолчанию /)
#   DISK_THRESHOLD_PCT      — порог в процентах (по умолчанию 80)
#   BACKUP_DIR              — каталог бэкапов (как в backup_postgres.sh)
#   BACKUP_RETENTION_DAYS   — удалить бэкапы старше N дней (по умолчанию 7)
#   DOCKER_PRUNE            — 1 = docker system prune -f (по умолчанию 1)
#   JOURNAL_VACUUM_TIME     — journalctl --vacuum-time=… (по умолчанию 3d; пусто = пропустить)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DISK_MOUNT="${DISK_MOUNT:-/}"
DISK_THRESHOLD_PCT="${DISK_THRESHOLD_PCT:-80}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DOCKER_PRUNE="${DOCKER_PRUNE:-1}"
JOURNAL_VACUUM_TIME="${JOURNAL_VACUUM_TIME:-3d}"

usage_pct() {
  df -P "$DISK_MOUNT" | awk 'NR==2 {gsub(/%/,"",$5); print $5}'
}

USED="$(usage_pct)"
if [[ -z "$USED" ]] || ! [[ "$USED" =~ ^[0-9]+$ ]]; then
  echo "ERROR: cannot read disk usage for $DISK_MOUNT" >&2
  exit 1
fi

echo "Disk $DISK_MOUNT: ${USED}% used (threshold ${DISK_THRESHOLD_PCT}%)"

if [[ "$USED" -lt "$DISK_THRESHOLD_PCT" ]]; then
  echo "OK: below threshold, nothing to clean"
  exit 0
fi

echo "WARN: disk at or above ${DISK_THRESHOLD_PCT}%, starting cleanup"

prune_dir_by_age() {
  local dir="$1" pattern="$2" days="$3" label="$4"
  [[ -d "$dir" ]] || return 0
  local n=0
  while IFS= read -r -d '' f; do
    rm -f "$f"
    n=$((n + 1))
  done < <(find "$dir" -type f -name "$pattern" -mtime +"$days" -print0 2>/dev/null || true)
  echo "  $label: removed $n file(s) in $dir"
}

# Бэкапы (дублирует backup_postgres, на случай если cron бэкапа не сработал)
prune_dir_by_age "$BACKUP_DIR" 'shopstore_*.sql.gz' "$BACKUP_RETENTION_DAYS" "old DB backups"

# Логи в репозитории и рядом
for log_dir in "$ROOT/logs" "$ROOT/.backup" /var/log; do
  [[ -d "$log_dir" ]] || continue
  prune_dir_by_age "$log_dir" '*.log' 7 "log files"
  prune_dir_by_age "$log_dir" '*.log.*' 7 "rotated logs"
done

# Docker: кэш сборки + dangling-образы (не трогает тома db/media)
if [[ "$DOCKER_PRUNE" == "1" ]] && command -v docker >/dev/null 2>&1; then
  echo "  docker builder prune -af"
  docker builder prune -af 2>/dev/null || echo "  docker builder prune skipped"
  echo "  docker system prune -f"
  docker system prune -f 2>/dev/null || echo "  docker system prune skipped"
fi

# systemd journal (нужны права root)
if [[ -n "$JOURNAL_VACUUM_TIME" ]] && command -v journalctl >/dev/null 2>&1; then
  if journalctl --vacuum-time="$JOURNAL_VACUUM_TIME" 2>/dev/null; then
    echo "  journal vacuum: $JOURNAL_VACUUM_TIME"
  else
    echo "  journal vacuum skipped (no permission or not systemd)"
  fi
fi

AFTER="$(usage_pct)"
echo "Done: disk ${DISK_MOUNT} now ${AFTER}% used (was ${USED}%)"

if [[ "$AFTER" -ge "$DISK_THRESHOLD_PCT" ]]; then
  echo "WARN: still at or above threshold — check Docker volumes or enlarge disk" >&2
  exit 2
fi

exit 0
