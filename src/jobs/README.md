# Jobs (`src/jobs`)

Краткая шпаргалка: что делает каждый модуль, как запустить и cron на prod.

Запускать из **корня репозитория** (на prod обычно `/opt/shopstore`). Все cron-строки — в `crontab -e` пользователя, под которым крутится Docker.

Общая настройка cron (один раз):

```bash
cd /opt/shopstore
make prod-cron-help          # все строки проекта (бэкапы, EUR, media…)
crontab -e
```

---

## `queue.py`

**Не job**, а хелпер для RQ-очередей каталога: `catalog_import`, `catalog_dom`, `catalog_finalize`.

### Функции (Python API)

| Функция | Назначение |
|---------|------------|
| `get_catalog_import_queue()` / `get_catalog_dom_queue()` / `get_catalog_finalize_queue()` | Объекты `rq.Queue` для постановки и чтения задач |
| `get_catalog_queue()` | Алиас на import-очередь (обратная совместимость) |
| `get_catalog_queue_stats()` | Сводные счётчики по всем трём очередям (см. ниже) |
| `clear_failed_jobs(queue)` | Удалить failed jobs одной очереди |
| `clear_all_catalog_failed_jobs()` | Очистить failed во всех трёх catalog-очередях |
| `get_rq_workers_by_queue()` | Живые RQ-воркеры по ролям import / dom / finalize |
| `dom_queue_overloaded()` | True, если DOM-очередь перегружена (rolling pause) |
| `get_scraper_run_status()` | Фаза пайплайна + счётчики для админки парсинга |

#### `get_catalog_queue_stats()`

Возвращает `dict` для дашборда и страниц админки. Считает **чанки** (jobs), не отдельные SKU.

| Ключ | Смысл |
|------|--------|
| `pending_jobs`, `running_jobs`, `failed_jobs`, `deferred_jobs`, `scheduled_jobs` | Очередь `catalog_import` |
| `import_chunk_size` | Из `SCRAPER_IMPORT_CHUNK_SIZE` (по умолчанию 10) |
| `estimated_products_pending` | `pending_jobs × chunk_size` (оценка товаров в очереди импорта) |
| `estimated_products_in_progress` | `running_jobs × chunk_size` |
| `dom_pending_jobs`, `dom_running_jobs`, `dom_failed_jobs` | Очередь `catalog_dom` |
| `finalize_pending_jobs`, `finalize_running_jobs`, `finalize_failed_jobs` | Очередь `catalog_finalize` |

**Где используется:** дашборд (`/internal/admin/dashboard` — карточка «Парсинг каталога»), `/internal/admin/parsing`, API `GET /products/queue-stats`, импорт в админке.

### Makefile

| Команда | Описание |
|---------|----------|
| `make queue-status` | Счётчики очередей (локально) |
| `make prod-queue-status` | То же на prod |
| `make queue-clear-failed` | Очистить failed jobs |
| `make prod-queue-clear-failed` | То же на prod |

**Cron:** не нужен — только ручная диагностика.

---

## `admin_job_snapshots.py`

Redis-снимки последних cron/job тиков для админки парсинга.

| Ключ snapshot | Источник |
|---------------|----------|
| `rolling_refresh` | `dom_scheduler` / `make prod-dom-rolling` |
| `dom_watchdog` | `dom_watchdog --apply` |
| `parser_nightly` | nightly parser |
| `redis_health` | `redis_health_job` |

TTL snapshot в Redis — **90 дней**. Пишут cron/job (`dom_scheduler`, `dom_watchdog`, `redis_health_job`, nightly parser); в админке не отображается — только Redis-диагностика.

---

## `catalog_import_job.py`

**RQ worker jobs** — не запускаются по cron. Парсер и админка кладут задачи в очередь, обрабатывают `worker-import` / `worker-dom-1`+`worker-dom-2` / `worker-finalize`.

| Функция | Что делает |
|---------|------------|
| `run_catalog_import_chunk` | Импорт чанка товаров из GraphQL в БД |
| `run_catalog_dom_enrichment_chunk` | DOM-обогащение (остатки, цены поставщика) через Playwright |
| `run_catalog_deactivate_missing` | Деактивация товаров, не попавших в снимок парсера |

| Команда | Описание |
|---------|----------|
| `make parser` | Полный цикл парсера → очереди |
| `make parser-graphql` | Только GraphQL, без DOM |

**Cron:** не используется. Расписание парсера — отдельно (ручной `make parser` или свой cron на scraper).

### DOM chunk: status vs import (двухфазность)

`run_catalog_dom_enrichment_chunk` для каждого SKU проходит **две независимые фазы**:

1. **Enrich** (`enrich_products_with_dom`) — fetch/parse, `import_source="dom"` только при успешном apply.
2. **`record_dom_status`** — обновляет `dom_last_attempt_at` / `dom_attempts` / `dom_last_error` по success и failed спискам (не пишет `supplier_price_eur`).
3. **`import_products`** — только payload с `import_source=="dom"`; цена в БД меняется только при `has_changes=True` (ветка update writer).

| Поле | Когда меняется |
|------|----------------|
| `dom_last_attempt_at` | success **или** failed в `record_dom_status` |
| `catalog_synced_at` | import: `updated` или `touch_catalog_sync` при `skipped` (цена без изменений) |
| `supplier_price_eur` | только `updated` (enrichment writer) |

**Важно:** RQ/chunk SUCCESS (обогащение прошло) **≠** `supplier_price_eur` изменился — skip с touch sync возможен.

`dom_attempts` — streak неудач DOM status; сбрасывается на success (`0` не значит «никогда не парсили»). См. `record_dom_status` в `dom_status.py`.

**Логи (grep):** `dom_chunk_start`, `dom_product`, `dom_product_db` — JSON в stdout воркера; корреляция по `product_id` + `rq_job_id` + `owner_token`.

---

## `translation_job.py`

Отдельная очередь `translation`. Catalog ingest больше не вызывает Google/LibreTranslate.

| Функция | Что делает |
|---------|------------|
| `dispatch_pending_translations` | Находит SKU через `translation_backfill_skip_reason` и enqueue |
| `run_translate_product` | RQ worker: повторная проверка, перевод, запись `description_ru` |
| `enqueue_translation_product` | Dedup по `translate-{id}-{hash}` в `src/jobs/queue.py` |

Не использует `catalog_dom` claim.

| Команда | Описание |
|---------|----------|
| `make translation-up` | Локальный `worker-translation` (`--scale` через `WORKER_TRANSLATION_SCALE`) |
| `make translation-dispatch LIMIT=20` | Поставить jobs |
| `make translation-dispatch-dry` | Кандидаты без enqueue |
| `uv run python -m src.jobs.translation_job --dispatch --dry-run` | То же без compose exec |
| `uv run python -m src.utils.translate_descriptions --dry-run` | Тот же dispatcher |
| `make prod-translation-dispatch` | Prod enqueue |
| `make prod-translation-dispatch-dry` | Prod кандидаты |

**Cron prod:** `make prod-cron-help` — `*/10 * * * * prod-translation-dispatch`.

---

## `dom_scheduler.py`

Один **cron-тик** DOM: imprint recovery (`dom_full_at`+imprint+image) → INCOMPLETE → FULL, stale COMPLETE → LITE; приоритет `stock=0`. Recovery не занимает весь batch: `min(SCRAPER_DOM_PRIORITY_RECOVERY_LIMIT=20, batch_size // 2)`. Exhausted `invalid_*` (HOLD) сюда не попадают: `_base_dom_filters` требует `attempts < max`.

| Команда | Описание |
|---------|----------|
| `make dom-rolling` | Один тик (локально) |
| `make prod-dom-rolling` | Один тик (prod) |
| `uv run python -m src.jobs.dom_scheduler` | Напрямую |
| `uv run python -m src.jobs.dom_scheduler --limit 50` | Не больше 50 SKU за тик |

**Cron (prod, обязательно для DOM stock/price):** см. `make prod-cron-help` — `*/5 * * * * prod-dom-rolling`.

Parser **не ставит** DOM в очередь; только scheduler + Doctor + `worker-dom-1`/`worker-dom-2` на общую `catalog_dom`.

---

## `dom_doctor.py`

Один **cron-тик** раз в ~6 ч: exhausted FULL HOLD (`invalid_description|invalid_gallery|invalid_pdp` и `attempts >= max`) → claim → `dom_attempts=0` → enqueue FULL в существующую `catalog_dom`. Не парсит, не трогает `is_active` / `deactivated_at`, не создаёт вторую очередь.

HOLD с витрины (Phase 3) сюда возвращаются в новый recovery cycle. Scheduler/priority этих SKU не берут, пока `attempts >= max`.

| Команда | Описание |
|---------|----------|
| `make dom-doctor` | Один тик (локально) |
| `make prod-dom-doctor` | Один тик (prod) |
| `uv run python -m src.jobs.dom_doctor` | Напрямую |
| `uv run python -m src.jobs.dom_doctor --limit 20` | Не больше 20 SKU за тик |

**Cron (prod):** см. `make prod-cron-help` — `0 */6 * * * prod-dom-doctor`.

Snapshot: `dom_doctor` (`eligible`, `claimed`, `enqueued`, `enqueued_products`, `skipped`, `errors`, `reason`).

---

## `dom_watchdog.py`

Проверяет jobs в `catalog_dom` с **мёртвым** RQ worker (job висит в `started`). Живой worker не requeue по возрасту: runaway режет `job_timeout`. С `--apply` — возвращает их в очередь.

| Команда | Описание |
|---------|----------|
| `make dom-watchdog` | Только проверка (dry-run) |
| `make dom-watchdog-apply` | Переотправить зависшие |
| `uv run python -m src.jobs.dom_watchdog` | Проверка |
| `uv run python -m src.jobs.dom_watchdog --apply` | Переотправить |
| `uv run python -m src.jobs.dom_watchdog --stale-seconds 3600` | Игнорируется (оставлен для совместимости) |

**Cron (prod):** см. `make prod-cron-help` — `*/10 * * * * prod-dom-watchdog-apply`.

---

## `redis_health_job.py`

Пингует sync/async Redis; пишет snapshot и **error-alert в лог**, если outage дольше `REDIS_HEALTH_ALERT_SECONDS`.

| Команда | Описание |
|---------|----------|
| `uv run python -m src.jobs.redis_health_job` | Один тик health-check |

**Cron (prod, рекомендуется):** `*/1 * * * * cd /path/to/app && uv run python -m src.jobs.redis_health_job` (или через systemd timer / monitoring agent).

Snapshot: `redis_health` в `admin_job_snapshots` (поля `ok`, `sync_ok`, `async_ok`, `outage_seconds`).

---

## Смена taxonomy (category_*)

Отдельного job нет. После деплоя новых правил категорий в prod (DBeaver):

```sql
UPDATE products
SET supplier_snapshot_hash = NULL
WHERE supplier_snapshot_json IS NOT NULL;
```

Дальше — nightly parser или `make prod-parser-nightly`: GraphQL import пересчитает category_* из snapshot.

---

## `eur_pricing_job.py`

Курс EUR (Rapira API) и пересчёт продажных цен.

| Задача | Что делает |
|--------|------------|
| `rate` | Обновить курс EUR в `pricing_settings` |
| `prices` | Пересчитать цены всех товаров |

| Команда | Описание |
|---------|----------|
| `make eur-rate-refresh` | Курс (локально) |
| `make eur-price-recalc` | Цены (локально) |
| `make prod-eur-rate-refresh` | Курс (prod) |
| `make prod-eur-price-recalc` | Цены (prod) |
| `uv run python -m src.jobs.eur_pricing_job --task rate` | Курс напрямую |
| `uv run python -m src.jobs.eur_pricing_job --task prices` | Цены напрямую |

**Cron (prod, обязательно для автообновления):**

```bash
sudo touch /var/log/shopstore-eur-rate.log /var/log/shopstore-eur-price.log
sudo chmod 644 /var/log/shopstore-eur-rate.log /var/log/shopstore-eur-price.log
crontab -e
```

```cron
# Курс EUR — каждые 30 минут
*/30 * * * * cd /opt/shopstore && make -C /opt/shopstore prod-eur-rate-refresh >> /var/log/shopstore-eur-rate.log 2>&1

# Пересчёт цен — каждые 6 часов (00:00, 06:00, 12:00, 18:00)
0 */6 * * * cd /opt/shopstore && make -C /opt/shopstore prod-eur-price-recalc >> /var/log/shopstore-eur-price.log 2>&1
```

Проверка:

```bash
make prod-eur-rate-refresh
make prod-eur-price-recalc
tail -f /var/log/shopstore-eur-rate.log
```

В админке `/internal/admin/prices` после `--task rate` обновится время (МСК), source `rapira:USDT/RUB*1.2` и строка в `eur_rate_history`.

---

## `pricing_recalculation_job.py`

Асинхронно пересчитывает одну storefront-группу после изменения наценки в админке.

| Параметр | Значение |
|----------|----------|
| Очередь | `pricing` |
| Worker | `worker-pricing`, один процесс |
| Batch | `PRICING_BATCH_SIZE`, по умолчанию 1000 |
| Retry | до 3 запусков; продолжение с сохранённого cursor |
| Статусы | `queued`, `running`, `succeeded`, `failed`, `superseded` |

| Команда | Описание |
|---------|----------|
| `make pricing-up` | Поднять один pricing worker |
| `make pricing-logs` | Смотреть progress и ошибки |
| `make pricing-down` | Остановить pricing worker |

Job создаётся страницей `/internal/admin/margins`. Отдельного cron нет.
Если Redis не принял задачу, DB job сразу получает статус `failed`, время
завершения и текст ошибки. В `queued` такая запись не остаётся.

Общие наборы воркеров:

| Команда | Описание |
|---------|----------|
| `make up` / `make up-d` | Базовый стек без воркеров |
| `make catalog-workers-up` | Только import, DOM и finalize |
| `make workers-up-all` | Все RQ-воркеры |
| `make workers-down-all` | Остановить все RQ-воркеры |

---

## `support_attachment_retention_job.py`

Удаляет **фото поддержки** через `SUPPORT_ATTACHMENT_RETENTION_DAYS` (180) после `closed_at`. Сообщения и тикеты остаются. 365-day anonymization **не** входит.

| Что делает | Детали |
|------------|--------|
| Кандидаты | `status=closed`, `closed_at <= now-180d`, есть `support_message_attachments` |
| Удаление | `Storage.delete` (нет объекта = успех) → delete row |
| Orphans | ключи `support/` не в БД и старше 1 часа (mtime/LastModified) |
| Snapshot | Redis `support_attachment_retention`: `candidates`, `purged`, `orphans` |

| Команда | Описание |
|---------|----------|
| `make support-attachment-retention` | Один тик (dev/local) |
| `make prod-support-attachment-retention` | Один тик (prod, в контейнере `api`) |
| `uv run python -m src.jobs.support_attachment_retention_job` | Напрямую |
| `uv run python -m src.jobs.support_attachment_retention_job --limit 50` | Не больше 50 вложений за тик |

Лог по умолчанию: `logs/support_attachment_retention.log`.

**Cron (prod):** см. `make prod-cron-help` — `20 4 * * * prod-support-attachment-retention`.

## `unpaid_order_expiration_job.py`

Автоотмена **неоплаченных** заказов по истечению `payment_due_at` (`ORDER_PAYMENT_DEADLINE_HOURS`, по умолчанию 24 ч).

| Что делает | Детали |
|------------|--------|
| Кандидаты | `payment_due_at <= now`, не оплачен, статус `created`/`processing` |
| Пропуск | Уже оплачен; **resumable** попытка (живой QR или `init_state=creating` без provider) |
| Отмена | `status=cancelled`, `cancellation_reason=payment_timeout`, событие в timeline |
| Snapshot | Redis `unpaid_order_expiration`: `candidates`, `cancelled`, `skipped` |


| Команда | Описание |
|---------|----------|
| `make unpaid-order-expiration` | Один тик (dev/local) |
| `make prod-unpaid-order-expiration` | Один тик (prod, в контейнере `api`) |
| `uv run python -m src.jobs.unpaid_order_expiration_job` | Напрямую |
| `uv run python -m src.jobs.unpaid_order_expiration_job --limit 20` | Не больше 20 заказов за тик |

Лог по умолчанию: `logs/unpaid_order_expiration.log`.

**Cron (prod):** см. `make prod-cron-help` — `*/5 * * * * prod-unpaid-order-expiration`.

```bash
make prod-unpaid-order-expiration
tail -f /var/log/shopstore-unpaid-order-expiration.log
```

Не путать с [`payment_reconciliation_job.py`](payment_reconciliation_job.py) — тот опрашивает SBP по истёкшим QR-попыткам (`make payment-reconciliation` / `*/1` на prod).

---

## `notification_outbox_job.py`

Доставка TG-уведомлений из Postgres outbox (transactional outbox pattern).

| Что делает | Детали |
|------------|--------|
| Stuck recovery | `processing` старше 5 мин → `pending` |
| Claim | `SELECT … FOR UPDATE SKIP LOCKED`, batch до `--limit` |
| Deliver | `compose` + `telegram_client` + `order_event` (как inline) |
| Retry | до 5 попыток с exponential backoff через `locked_at` |


| Команда | Описание |
|---------|----------|
| `make notification-outbox` | Один тик (dev/local) |
| `make prod-notification-outbox` | Один тик (prod, в контейнере `api`) |
| `uv run python -m src.jobs.notification_outbox_job` | Напрямую |
| `uv run python -m src.jobs.notification_outbox_job --limit 20` | Не больше 20 строк за тик |

Лог по умолчанию: `logs/notification_outbox.log`. Snapshot Redis: `notification_outbox`.

**Cron (prod):** см. `make prod-cron-help` — `*/1 * * * * prod-notification-outbox`.

```bash
make prod-notification-outbox
tail -f /var/log/shopstore-notification-outbox.log
```

**Env:** `NOTIFICATION_MODE=outbox` (default prod). `NOTIFICATION_INLINE=1` — только local debug (inline deliver без outbox).

Опционально stage 2: RQ-очередь `notifications` (`get_notification_queue()` в `queue.py`) — per-row enqueue, не обязательно в v1.

---

## `supplier_tracking_scheduler.py` / `supplier_tracking_job.py`

Двухфазный трекинг заказов поставщика (Supplier-Demo):

| Фаза | Условие | Источник | Что пишем |
|------|---------|----------|-----------|
| A | есть `TP-...` | ParcelLab API | `supplier_events` (нормализованный body), CJ и метаданные перевозчика |
| B | есть `supplier_tracking_id` (CJ…) | DHL `int-verfolgen` | `carrier_events` (source: `dhl`, raw для админки) |

ЛК показывает order milestones + `supplier_events`. DHL в ЛК — только fallback, если supplier пустой/устарел. Админка: вкладки в карточке «Доставка» — ParcelLab · DHL raw · Ручной этап · превью ЛК. Кнопка «Сверить с Supplier-Demo» — тот же ParcelLab sync.

| Команда | Описание |
|---------|----------|
| `make prod-supplier-tracking` | Scheduler: поставить в очередь due-заказы (prod) |
| `uv run python -m src.jobs.supplier_tracking_scheduler` | Scheduler напрямую |
| `uv run python -m src.jobs.supplier_tracking_scheduler --limit 50` | Не больше 50 заказов за тик |

RQ worker: `worker-supplier-tracking`, очередь `supplier_tracking`. Job: `run_supplier_tracking_job(order_id)`.

**Cron (prod):** см. `make prod-cron-help` — `*/15 * * * * prod-supplier-tracking`.

```bash
make prod-supplier-tracking
tail -f /var/log/shopstore-supplier-tracking.log
```

Ручной sync одного заказа: кнопка «Проверить сейчас» в админке заказа или enqueue через `enqueue_supplier_tracking(order_id)`.

DHL spike: `uv run python -m src.services.orders.dhl_tracking CJ686803119DE`

---

## `dhl_browser_tracking_job.py`

Playwright fallback для DHL, если HTTP (direct/proxy) вернул `blocked`. `supplier_tracking_job` инжектит `fetch_dhl_tracking_via_browser_queue` в `SupplierTrackingService(dhl_browser_fetch=...)` — service не импортирует `jobs/`. `worker-tracking` ставит job в очередь и ждёт результат (`DHL_BROWSER_FETCH_TIMEOUT_SECONDS`, default 75s).

| Команда / компонент | Описание |
|---------------------|----------|
| `worker-dhl` | `rq worker dhl_browser_tracking` (отдельный scraper-воркер, не `worker-dom-1/2`) |
| `run_dhl_browser_fetch_job(piececode, language)` | RQ entrypoint |
| `fetch_dhl_tracking_payload_via_browser` | service: Chromium + `context.request.get` к `int-verfolgen/data/search` |

Отключить browser path: `DHL_TRACKING_USE_BROWSER=false` в `.env`.

---

## `orders/delivered_alert_retry_scheduler.py` / `orders/delivered_alert_retry_job.py`

Retry TG admin alert A о доставке. Legacy order-level — только заказы без Shipment в `status=delivery`. Per-shipment A ретраится отдельно (включая заказ уже в `completed`). C этим job не шлётся.

| Trigger | Legacy: `pending_retry` в `Order.supplier_tracking_json.admin_delivered_alert` (только заказы без Shipment, `status=delivery`). PLACED: то же в `Shipment.delivered_alert` |
| Scheduler | `enqueue_due_delivered_alert_retries()` — cron, без `enqueue_in` / rq-scheduler |
| Job | `run_delivered_alert_retry_job(order_id)` — legacy A, не C. `run_shipment_delivered_alert_retry_job(shipment_id)` — PLACED per shipment |

| Env | Default | Смысл |
|-----|---------|--------|
| `DELIVERED_ALERT_RETRY_QUEUE` | `delivered_alert_retry` | RQ-очередь retry |
| `DELIVERED_ALERT_RETRY_MINUTES` | `30` | Пауза до следующей попытки TG |

| Команда | Описание |
|---------|----------|
| `make prod-delivered-alert-retry` | Scheduler: due retry → очередь (prod) |
| `uv run python -m src.jobs.orders.delivered_alert_retry_scheduler` | Scheduler напрямую |
| `uv run python -m src.jobs.orders.delivered_alert_retry_scheduler --order-id 123` | Enqueue legacy retry сразу |
| `uv run python -m src.jobs.orders.delivered_alert_retry_scheduler --shipment-id 160` | Enqueue PLACED shipment retry сразу |

RQ worker: `worker-supplier-tracking`, очередь `delivered_alert_retry`.

**Cron (prod):** `*/5 * * * * prod-delivered-alert-retry`.

---

## `orders/supplier_availability_scheduler.py` / `orders/supplier_availability_job.py`

Автопроверка наличия у Supplier-Demo после checkout с `availability_confirmation_status=pending`.

| Шаг | Что делает |
|-----|------------|
| Trigger | `enqueue_supplier_availability(order_id)` после commit checkout |
| Job | HTTP PDP fetch (stealth + `storage_state`), snapshot в `orders.supplier_availability_json` |
| TTL | 5 мин (`SUPPLIER_AVAILABILITY_SNAPSHOT_TTL_MINUTES`) |
| Admin | карточка заказа в админке |

| Env | Default | Смысл |
|-----|---------|--------|
| `SUPPLIER_AVAILABILITY_ENABLED` | `false` | Kill switch: enqueue и job no-op |
| `SUPPLIER_AVAILABILITY_QUEUE` | `supplier_availability` | RQ-очередь |
| `SUPPLIER_AVAILABILITY_SNAPSHOT_TTL_MINUTES` | `5` | Свежесть snapshot для confirm/reject |
| `SUPPLIER_AVAILABILITY_MAX_RETRIES` | `2` | Повторы HTTP на позицию при challenge/error |
| `SUPPLIER_AVAILABILITY_ITEM_PAUSE_SECONDS` | `2.5` | Пауза между позициями в заказе |
| `SUPPLIER_AVAILABILITY_RETRY_PAUSE_SECONDS` | `1.5` | Пауза между retry одной позиции |
| `SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE` | `true` | Prod: без `storage_state` → manual_review; `false` — HTTP без cookies (dev load test) |

| Команда | Описание |
|---------|----------|
| `make availability-up` | Поднять один availability worker |
| `make availability-check ORDER_ID=123` | Поставить ручную проверку заказа в очередь |
| `make availability-logs` | Смотреть результат проверки |
| `make availability-down` | Остановить availability worker |
| `uv run python -m src.jobs.orders.supplier_availability_scheduler --order-id 123` | Enqueue одного заказа |

RQ worker: `worker-availability`, очередь `supplier_availability`. Job: `run_supplier_availability_job(order_id)`. Worker простаивает, если очередь пустая.

Volume: `src/scraper/infrastructure/session` (read-only) для `storage_state.json` при `SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE=true`.

**Kill switch:** `SUPPLIER_AVAILABILITY_ENABLED=false` (default) — enqueue и job no-op.

**Доступ к Supplier-Demo:** topology **1+1 A** — `worker-dom-1` и `worker-dom-2`, по одному RQ worker. Local: `make catalog-workers-up`. Prod: `make prod-up`. Login: `make login-lane LANE=1` и `LANE=2` (prod alias `prod-login-lane`). `make login` только для availability (`infrastructure/session/`). Lane делит session-N и `LANE_N_PROXY_*` (пусто = direct). HTTP-first и Playwright берут тот же `SCRAPER_PROXY_*`.

SKU по lanes не режут; scheduler/watchdog/doctor глобальные. 1+1 A+B — fallback (два TP-аккаунта).

Spike (local): `uv run python local_scripts/other/task_04_supplier_availability_spike/supplier_availability_spike.py`

---

## Связанные workers (не в этой папке)

| Сервис | Очередь |
|--------|---------|
| `worker-import` | `catalog_import` |
| `worker-dom-1` | `catalog_dom` |
| `worker-dom-2` | `catalog_dom` |
| `worker-finalize` | `catalog_finalize` |
| `worker-translation` | `translation` |
| `worker-pricing` | `pricing` |

Логи: `make worker-import-logs`, `make worker-dom-logs`, `make translation-logs`, `make pricing-logs`.

**Cron:** workers работают постоянно (`docker compose up -d`), отдельный cron не нужен.
