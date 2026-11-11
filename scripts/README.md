# Скрипты обслуживания (Linux, prod-сервер)

Запускать из **корня репозитория** на машине, где поднят Docker Compose (`docker-compose.prod.yml`) и лежит `.env`.

**На prod через Makefile:**

```bash
make prod-backup          # → scripts/backup_postgres.sh
make prod-disk-cleanup    # → scripts/disk_cleanup.sh (если диск ≥ 80%)
make prod-media-cleanup   # → scripts/prune_orphan_media.sh (сироты в media/products)
make prod-remove-duplicate-previews       # dry-run byte-identical _300/_600/_900
make prod-remove-duplicate-previews-apply # DELETE after backup, CONFIRM=1
make prod-cron-help       # готовые строки для crontab -e
```

| Скрипт | Назначение |
|--------|------------|
| `backup_postgres.sh` | Снимок PostgreSQL в `backups/*.sql.gz`; после каждого запуска удаляет бэкапы старше 7 дней |
| `disk_cleanup.sh` | Если диск заполнен ≥ 80%, чистит старые бэкапы, логи; опционально `docker system prune` и journal |
| `prune_orphan_media.sh` | Удаляет файлы в `media/products`, на которые нет ссылок в БД (через `docker compose exec api`) |
| [`media/`](media/README.md) | Product media: дубли превью, S3 migrate, variants, local cleanup. Dry-run. Подробности в README папки |
| `push_scraper_session.sh` | **С локального ПК:** заливает session-1 и session-2 на сервер (`make push-scraper-sessions`), рестарт `worker-dom-1` / `worker-dom-2` |
| `admin_smoke.sh` | Дымовая проверка админки: статика и маршруты `/internal/admin/*` (без логина) |
| `env_doctor.py` | Сверка `.env.local` / `.env.dev` / `.env.prod` с эталоном `.env.example` (`make env-check`) |
| `mark_order_paid.py` | Ручная оплата заказа: `make order-paid ORDER_ID=…` (prod: `CONFIRM=<id>`) |

**Storefront mapping v2 (release lifecycle):** [`storefront_mapping/README.md`](storefront_mapping/README.md) — seed, backfill, reconcile, activate, rollback.

Права на выполнение: `chmod +x scripts/*.sh`

---

## backup_postgres.sh

**Что делает:** `pg_isready` + `pg_dump` из контейнера `db` → gzip в `./backups/shopstore_YYYYMMDD_HHMMSS.sql.gz`. При временной недоступности БД (recovery, рестарт) — повторные попытки (`BACKUP_MAX_RETRIES` + `BACKUP_RETRY_DELAY_SEC`). Старые файлы `shopstore_*.sql.gz` с возрастом больше `BACKUP_RETENTION_DAYS` (по умолчанию 7) удаляются.

**Нужно:** работающий стек `db`, в `.env` заданы `POSTGRES_USER`, `POSTGRES_DB` (скрипт **не** делает `source .env` — значения с пробелами ломают bash; `pg_dump` читает переменные из контейнера).

**Переменные:** `COMPOSE_FILE`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_MAX_RETRIES`, `BACKUP_RETRY_DELAY_SEC`, `BACKUP_LOG_TIMESTAMPS` (по умолчанию `1` — timestamp в каждой строке лога).

**Ручной запуск:**

```bash
cd /opt/shopstore   # путь к проекту на сервере
./scripts/backup_postgres.sh
```

---

## disk_cleanup.sh

**Что делает:** смотрит заполнение точки монтирования (по умолчанию `/`). Пока занято **меньше 80%** — выходит без изменений. При **≥ 80%** удаляет устаревшие бэкапы, `.log` в типичных каталогах; при возможности — `docker system prune -f` и сжатие journal systemd.

**Не трогает:** тома Docker с БД и медиа, данные приложения.

**Переменные:** `DISK_MOUNT`, `DISK_THRESHOLD_PCT`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `DOCKER_PRUNE`, `JOURNAL_VACUUM_TIME`.

**Ручной запуск:**

```bash
cd /opt/shopstore
./scripts/disk_cleanup.sh
```

---

## prune_orphan_media.sh

**Что делает:** сравнивает файлы в `media/products` с URL в `products` и `product_images`, удаляет сироты (оригинал + превью `_300/_600/_900` учитываются по ссылкам в БД).

**Когда:** раз в неделю по cron; вручную после массового re-import. При импорте каталога старые файлы теперь удаляются автоматически (`discard_product_local_media`).

**Ручной запуск (prod):**

```bash
cd /opt/shopstore
./scripts/prune_orphan_media.sh --dry-run
make prod-media-cleanup
```

**Локально** (нужны `DATABASE_URL` / `ALEMBIC_DATABASE_URL` и доступ к `media/products`):

```bash
make media-cleanup
```

---

## Product media

Скрипты product media вынесены в [`media/README.md`](media/README.md).
Там порядок, dry-run/`--apply`, env и предупреждение про production.

---

## admin_smoke.sh

**Что делает:** быстрая проверка после правок UI админки — `curl` по CSS/JS и страницам `/internal/admin/*`. Без Playwright и без сессии.

**Ожидаемые коды:**
- `/internal/admin/login` → **200**
- остальные страницы (dashboard, orders, products, …) → **302/303/307** (редирект на логин)
- статика `admin.css`, `admin.js` → **200**

При ошибке (404, 500) скрипт завершается с ненулевым кодом.

**Переменные:** `ADMIN_SMOKE_BASE` — базовый URL API (по умолчанию `http://localhost:8000`).

**Запуск:**

```bash
./scripts/admin_smoke.sh
# или на другом хосте:
ADMIN_SMOKE_BASE=https://your-host ./scripts/admin_smoke.sh
```

**Когда:** после `docker compose restart api`, миграции шаблонов/CSS админки, перед ручным QA в браузере.

**Не проверяет:** вёрстку, HTMX, авторизованные страницы, POST-формы.

---

## env_doctor.py

**Что делает:** сверяет env-файлы с эталоном `.env.example` — missing, unused, empty, дубликаты, синтаксис.

**По умолчанию проверяет:** `.env.local`, `.env.dev`, `.env.prod` (отсутствующие — предупреждение, не ошибка).

**Запуск:**

```bash
make env-check
# или
uv run python scripts/env_doctor.py
uv run python scripts/env_doctor.py --env .env --env frontend/.env.production --strict
uv run python scripts/env_doctor.py --json
```

**Exit code:** `1` при missing / duplicates / syntax; с `--strict` также при empty и unused.

---

## mark_order_paid.py

**Что делает:** вручную отмечает заказ оплаченным (тот же сценарий, что локальный `make order-paid`). Фиксирует `payment_paid_at`, `paid_supplier_order_count` и ставит клиенту уведомление об оплате. После этого в админке доступен штатный flow «Рекомендовать сборку» → preview → Apply.

Рекомендация по сборке **не применяется автоматически**.

**Dev:**

```bash
make order-paid ORDER_ID=355
```

**Production** — нужен `CONFIRM`, совпадающий с `ORDER_ID`:

```bash
make order-paid ORDER_ID=355 CONFIRM=355
```

Эквивалент:

```bash
cd /opt/shopstore
docker compose -f docker-compose.prod.yml exec -T api \
  uv run python scripts/mark_order_paid.py \
  --order-id 355 --confirm-order-id 355
```

Без `CONFIRM` / при несовпадении на prod заказ не меняется.

**Ограничения:** не для отменённых заказов (late payment — `tests/manual/order_test_fixture.py paid --late`, только `APP_ENV=dev`). Повторный запуск на уже оплаченном заказе — no-op; если не было `paid_supplier_order_count`, только дополняет его.

---

## Cron на сервере (Linux)

Открыть crontab пользователя, под которым крутится Docker (часто `root` или deploy-пользователь):

```bash
crontab -e
```

Подставить реальный путь к проекту вместо `/opt/shopstore`.

```cron
# Бэкап БД — каждый день в 02:55
55 2 * * * cd /opt/shopstore && ./scripts/backup_postgres.sh >> /var/log/shopstore-backup.log 2>&1

# Очистка диска — каждый час (работает только при заполнении ≥ 80%)
0 * * * * cd /opt/shopstore && ./scripts/disk_cleanup.sh >> /var/log/shopstore-disk-cleanup.log 2>&1

# Сироты media — каждое воскресенье в 04:00
0 4 * * 0 cd /opt/shopstore && make -C /opt/shopstore prod-media-cleanup >> /var/log/shopstore-media-cleanup.log 2>&1
```

Полный список строк (EUR, бэкапы, парсинг, outbox): `make prod-cron-help`.

### Курс EUR и цены

```cron
# Курс EUR — каждые 30 минут
*/30 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-eur-rate-refresh >> /var/log/shopstore-eur-rate.log 2>&1

# Пересчёт цен — каждые 6 часов (00:00, 06:00, 12:00, 18:00)
0 */6 * * * cd /opt/shopstore && make -C /opt/shopstore prod-eur-price-recalc >> /var/log/shopstore-eur-price.log 2>&1
```

| Make | Модуль | Что делает |
|------|--------|------------|
| `prod-eur-rate-refresh` | `eur_pricing_job --task rate` | Курс EUR из Rapira API |
| `prod-eur-price-recalc` | `eur_pricing_job --task prices` | Пересчёт продажных цен |

### TG outbox, оплата и заказы (cron в контейнере `api`)

**Не RQ-воркеры** — отдельные контейнеры не нужны. Раз в N минут cron на хосте
вызывает `make prod-*`, внутри — `docker compose exec api uv run python -m src.jobs.*`.

После деплоя outbox **добавить в crontab вручную** (если строки ещё нет):

```cron
# Сверка оплат SBP — каждую минуту
*/1 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-payment-reconciliation >> /var/log/shopstore-payment-reconciliation.log 2>&1

# Автоотмена неоплаченных заказов — каждые 5 минут
*/5 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-unpaid-order-expiration >> /var/log/shopstore-unpaid-order-expiration.log 2>&1

# Доставка TG из notification_outbox — каждую минуту
*/1 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-notification-outbox >> /var/log/shopstore-notification-outbox.log 2>&1

# Трекинг поставщика (ParcelLab/DHL) — каждые 15 минут
*/15 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-supplier-tracking >> /var/log/shopstore-supplier-tracking.log 2>&1

# Повтор TG admin alert «доставлено» — каждые 5 минут
*/5 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-delivered-alert-retry >> /var/log/shopstore-delivered-alert-retry.log 2>&1
```

| Make | Модуль | Что делает |
|------|--------|------------|
| `prod-payment-reconciliation` | `payment_reconciliation_job` | Догоняет статусы оплат у провайдера |
| `prod-unpaid-order-expiration` | `unpaid_order_expiration_job` | Отменяет заказы с истёкшим сроком оплаты |
| `prod-notification-outbox` | `notification_outbox_job` | Claim из `notification_outbox` → Telegram |
| `prod-supplier-tracking` | `supplier_tracking_scheduler` | Ставит due-заказы в очередь `supplier_tracking` |
| `prod-delivered-alert-retry` | `delivered_alert_retry_scheduler` | Повтор неудачных TG alert о доставке |

**Env на prod:** `NOTIFICATION_MODE=outbox` (default). Без cron outbox строки
копятся в Postgres, TG из request path не шлётся.

Проверка после добавления строки:

```bash
make prod-notification-outbox
tail -20 /var/log/shopstore-notification-outbox.log
# локально на сервере в репо:
tail -f logs/notification_outbox.log
```

Подробнее: [`docs/notification-outbox-flow.md`](../docs/notification-outbox-flow.md), [`src/jobs/README.md`](../src/jobs/README.md).

### Парсинг каталога

**Воркеры RQ не в cron** — должны работать постоянно:

```bash
# корневой .env: WORKER_IMPORT_SCALE, WORKER_DOM_LANE_1_SCALE, WORKER_DOM_LANE_2_SCALE
# src/scraper/.env: SCRAPER_* (batch, pacing, proxy, session)
make prod-up
```

Cron только **кладёт задачи в очередь**; жуют `worker-import` / `worker-dom-1`+`worker-dom-2` / `worker-finalize`.

```cron
# Rolling DOM: stale SKU → catalog_dom (рекомендуется */5)
*/5 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-dom-rolling >> /var/log/shopstore-dom-rolling.log 2>&1

# Nightly: GraphQL discovery + finalize (без DOM enqueue, см. SCRAPER_DOM_ENQUEUE_ON_PARSER)
0 3 * * * cd /opt/shopstore && make -C /opt/shopstore prod-parser-nightly >> /var/log/shopstore-parser-nightly.log 2>&1

# Watchdog: вернуть зависшие catalog_dom jobs в очередь
*/10 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-dom-watchdog-apply >> /var/log/shopstore-dom-watchdog.log 2>&1
```

| Make | Модуль | Что делает |
|------|--------|------------|
| `prod-dom-rolling` | `dom_scheduler` | Один тик: INCOMPLETE→FULL, stale COMPLETE→LITE |
| `prod-parser-nightly` | scraper profile | GraphQL discovery + finalize |
| `prod-dom-watchdog-apply` | `dom_watchdog --apply` | Переотправить зависшие `catalog_dom` jobs |

Проверка после настройки:

```bash
make prod-dom-rolling
make prod-dom-watchdog          # dry-run, без изменений
make prod-queue-status
docker compose -f docker-compose.prod.yml logs --tail=30 worker-dom-1 worker-dom-2
```

Логи cron (если нужна диагностика): `grep CRON /var/log/syslog` (Debian/Ubuntu) или `journalctl -u cron` (systemd).

Создать файлы логов один раз (от root):

```bash
touch /var/log/shopstore-backup.log /var/log/shopstore-disk-cleanup.log /var/log/shopstore-media-cleanup.log \
  /var/log/shopstore-eur-rate.log /var/log/shopstore-eur-price.log \
  /var/log/shopstore-dom-rolling.log /var/log/shopstore-parser-nightly.log /var/log/shopstore-dom-watchdog.log \
  /var/log/shopstore-payment-reconciliation.log /var/log/shopstore-unpaid-order-expiration.log \
  /var/log/shopstore-supplier-tracking.log /var/log/shopstore-delivered-alert-retry.log \
  /var/log/shopstore-notification-outbox.log
chmod 644 /var/log/shopstore-*.log
```

Полный набор строк одной командой: `make prod-cron-help`.

Каталог бэкапов лучше держать вне git, на диске с запасом места; при необходимости:

```bash
export BACKUP_DIR=/var/backups/shopstore
```

в cron-строке или в обёртке-скрипте перед вызовом.

---

## push_scraper_session.sh (локальный ПК → сервер)

**Что делает:** копирует `session-1/storage_state.json` и `session-2/storage_state.json` на сервер в те же пути (тома `worker-dom-1` / `worker-dom-2`). Если есть старый `session/storage_state.json`, копирует и его (availability/import). По умолчанию перезапускает `worker-dom-1` и `worker-dom-2`.

**Дашборд (Lanes):** возраст DOM lane session считается в **API** (`stat` по файлам на диске). У `api-blue` / `api-green` нужны bind mount `session-1/` и `session-2/` (`docker-compose.prod.yml`); иначе после push воркеры уже с новым JSON, а карточки lane показывают mtime из образа. После деплоя с этими томами на prod один раз: recreate `api-blue` / `api-green`, не только restart workers.

**Когда:** после `make login-lane LANE=1` и `LANE=2`, чтобы обновить DOM-сессии на prod без ручного `scp`.

**Нужно:** SSH-доступ к серверу, на Mac/Linux установлены `ssh` и `scp`.

**Один раз:**

```bash
cp scripts/deploy.env.example scripts/deploy.env
# отредактировать DEPLOY_SSH и DEPLOY_PROJECT_DIR
chmod +x scripts/push_scraper_session.sh
```

**Запуск с Mac (из корня репозитория):**

```bash
make push-scraper-sessions
# или: ./scripts/push_scraper_session.sh
```

Без `deploy.env`:

```bash
DEPLOY_SSH=user@server DEPLOY_PROJECT_DIR=/opt/shopstore ./scripts/push_scraper_session.sh
```

**Переменные:** `DEPLOY_SSH`, `DEPLOY_PROJECT_DIR`, `RESTART_SCRAPER_WORKERS` (0 — только копирование), `COMPOSE_FILE`.

Файл `scripts/deploy.env` не коммитится (см. `.gitignore`).

---

## Витрина «не собрана» на prod

Сообщение значит: в контейнере `api` нет `frontend/dist/index.html`. `/ready` вернёт **503**, Docker healthcheck не пройдёт — контейнер не станет healthy.

Витрина собирается внутри Docker-образа (стадия `storefront-builder` в Dockerfile). На VPS **не** используйте `make storefront-build` — там нет npm.

**Деплой API на prod (PROD blue/green):**

После `git fetch && git pull --ff-only` на VPS:

```bash
cd /opt/shopstore
export PROD_PROD_REQUIRE_ORIGIN=1
make prod-prod-gate-blue   # first cutover / roll на blue (:8001)
# или
make prod-prod-gate-green  # roll на green (:8002)
```

Gate: preflight → migrate → verify image → start inactive color → wait → smoke. Caddy переключается **вручную** после pass gate.


**Legacy** (без migrate/gate, не для cutover):

```bash
make prod-deploy-api   # git pull + rebuild active color
```

**Только пересборка образа** (код уже на диске):

```bash
make prod-api-build
```

**Только смена `.env`** (без кода и без витрины):

```bash
make prod-api-env
```
