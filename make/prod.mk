# ============================================================
# Production
# ============================================================

##@ Production

# DEPLOY: exec/cron → active API; explicit PROD_API_COLOR override имеет приоритет
PROD_DEPLOY_ACTIVE_COLOR_FILE := $(CURDIR)/.deploy/active_color
PROD_API_COLOR ?= $(shell \
  _c=$$(tr -d '[:space:]' < '$(PROD_DEPLOY_ACTIVE_COLOR_FILE)' 2>/dev/null || true); \
  if [ "$$_c" = blue ] || [ "$$_c" = green ]; then echo "$$_c"; else echo blue; fi)
PROD_API_SERVICE := api-$(PROD_API_COLOR)

PROD_INFRA_SERVICES := db redis libretranslate seaweedfs bot \
	worker-import worker-dom-1 worker-dom-2 worker-translation worker-finalize \
	worker-pricing worker-tracking worker-dhl worker-availability


# Низкоуровневые цели — WARN в stderr; на prod: prod-deploy-gate-blue|green
define prod_deploy_low_level_warn
	@echo "WARN: $(1) is not a complete deployment gate — use: PROD_DEPLOY_REQUIRE_ORIGIN=1 make prod-deploy-gate-blue|green" >&2
endef

PROD_WORKER_SCALE_FLAGS := \
	--scale worker-import=$(WORKER_IMPORT_SCALE) \
	--scale worker-dom-1=$(WORKER_DOM_LANE_1_SCALE) \
	--scale worker-dom-2=$(WORKER_DOM_LANE_2_SCALE) \
	--scale worker-translation=$(WORKER_TRANSLATION_SCALE)

# db/redis: start или up без пересоздания (DEPLOY 3D.1)
define prod_compose_ensure
	@svc="$(1)"; \
	cid=$$($(DC_PROD) ps -aq "$$svc" 2>/dev/null | head -n1); \
	if [ -n "$$cid" ]; then \
	 running=$$(docker inspect -f '{{if .State.Running}}yes{{end}}' "$$cid" 2>/dev/null || echo no); \
	 if [ "$$running" != "yes" ]; then \
	  echo "==> starting $$svc"; \
	  $(DC_PROD) start "$$svc"; \
	 else \
	  echo "==> $$svc already running ($$cid)"; \
	 fi; \
	else \
	 echo "==> creating $$svc"; \
	 $(DC_PROD) up -d --no-recreate "$$svc"; \
	fi
endef

prod-ensure-shared: ## Ensure db+redis without recreating running containers
	$(call prod_compose_ensure,redis)
	$(call prod_compose_ensure,db)

prod-infra-up: ## Shared prod infrastructure (no API blue/green slots)
	$(DC_PROD) up -d --build $(PROD_INFRA_SERVICES) $(PROD_WORKER_SCALE_FLAGS)

prod-up: ## [legacy] infra + api-blue; без migrate/gate — не для cutover
	$(MAKE) prod-infra-up
	$(MAKE) prod-api-up-blue

prod-down: ## Остановить prod-стек (volumes сохраняются)
	$(DC_PROD) down

prod-logs: ## Хвост логов prod-стека
	$(DC_PROD) logs -f

prod-deploy-api: ## [legacy] git pull + rebuild; не DEPLOY gate (см. prod-deploy-gate-*)
	git pull --ff-only
	$(MAKE) prod-api-build

prod-migrate: ## [internal] build shopstore-api + alembic; шаг prod-deploy-gate-*
	$(call prod_compose_ensure,redis)
	$(call prod_compose_ensure,db)
	$(DC_PROD) build api-blue
	$(DC_PROD) --profile migrate run --rm api-migrate

prod-roll-api-blue: ## [internal] migrate+start blue :8001 — не полный gate
	$(call prod_deploy_low_level_warn,prod-roll-api-blue)
	$(MAKE) prod-migrate
	$(DC_PROD) up -d --no-deps api-blue

prod-roll-api-green: ## [internal] migrate+start green :8002 — не полный gate
	$(call prod_deploy_low_level_warn,prod-roll-api-green)
	$(MAKE) prod-migrate
	$(DC_PROD) --profile api-standby up -d --no-deps api-green

prod-deploy-preflight: ## [public] проверка git (без pull; локально PROD_DEPLOY_ALLOW_DIRTY=1)
	@chmod +x scripts/prod_deploy_gate.sh 2>/dev/null || true
	@./scripts/prod_deploy_gate.sh preflight

prod-api-wait-blue: ## [internal] ждать :8001 /health+/ready (PROD_API_WAIT_TIMEOUT, по умолч. 210с)
	@chmod +x scripts/prod_deploy_gate.sh 2>/dev/null || true
	@API_WAIT_BASE=http://127.0.0.1:8001 ./scripts/prod_deploy_gate.sh wait-ready

prod-api-wait-green: ## [internal] ждать :8002 /health+/ready (PROD_API_WAIT_TIMEOUT, по умолч. 210с)
	@chmod +x scripts/prod_deploy_gate.sh 2>/dev/null || true
	@API_WAIT_BASE=http://127.0.0.1:8002 ./scripts/prod_deploy_gate.sh wait-ready

prod-deploy-gate-blue: ## [public] prod gate api-blue (до переключения Caddy)
	$(MAKE) prod-deploy-preflight
	$(MAKE) prod-migrate
	@chmod +x scripts/prod_deploy_gate.sh 2>/dev/null || true
	@./scripts/prod_deploy_gate.sh verify-image-built
	$(DC_PROD) up -d --no-deps api-blue
	@./scripts/prod_deploy_gate.sh verify-image-running api-blue
	$(MAKE) prod-api-wait-blue
	$(MAKE) prod-api-smoke-blue

prod-deploy-gate-green: ## [public] prod gate api-green (до переключения Caddy)
	$(MAKE) prod-deploy-preflight
	$(MAKE) prod-migrate
	@chmod +x scripts/prod_deploy_gate.sh 2>/dev/null || true
	@./scripts/prod_deploy_gate.sh verify-image-built
	$(DC_PROD) --profile api-standby up -d --no-deps api-green
	@./scripts/prod_deploy_gate.sh verify-image-running api-green
	$(MAKE) prod-api-wait-green
	$(MAKE) prod-api-smoke-green

prod-deploy-deploy: ## [public] gate inactive + Caddy cutover + public smoke + drain previous
	@chmod +x scripts/prod_deploy_lib.sh scripts/prod_deploy_deploy.sh scripts/prod_deploy_gate.sh scripts/api_smoke.sh 2>/dev/null || true
	@PROD_DEPLOY_REQUIRE_ORIGIN=1 ./scripts/prod_deploy_deploy.sh

prod-deploy-rollback: ## [public] Caddy rollback to previous color + public smoke
	@chmod +x scripts/prod_deploy_lib.sh scripts/prod_deploy_rollback.sh scripts/prod_deploy_gate.sh scripts/api_smoke.sh 2>/dev/null || true
	@./scripts/prod_deploy_rollback.sh



prod-api-build: ## [internal] rebuild+start PROD_API_COLOR без migrate
	$(call prod_compose_ensure,redis)
	$(call prod_compose_ensure,db)
	$(DC_PROD) build $(PROD_API_SERVICE)
	$(DC_PROD) up -d --no-deps $(PROD_API_SERVICE)

prod-api-up-blue: ## [internal] build+start blue :8001 — не полный gate
	$(call prod_deploy_low_level_warn,prod-api-up-blue)
	$(call prod_compose_ensure,redis)
	$(call prod_compose_ensure,db)
	$(DC_PROD) build api-blue
	$(DC_PROD) up -d --no-deps api-blue

prod-api-up-green: ## [internal] build+start green :8002 — не полный gate
	$(call prod_deploy_low_level_warn,prod-api-up-green)
	$(call prod_compose_ensure,redis)
	$(call prod_compose_ensure,db)
	$(DC_PROD) --profile api-standby build api-green
	$(DC_PROD) --profile api-standby up -d --no-deps api-green

prod-api-smoke-blue: ## [internal] HTTP smoke :8001
	API_SMOKE_BASE=http://127.0.0.1:8001 ./scripts/api_smoke.sh

prod-api-smoke-green: ## [internal] HTTP smoke :8002
	API_SMOKE_BASE=http://127.0.0.1:8002 ./scripts/api_smoke.sh

prod-api-env: ## Применить .env для API color без rebuild (PROD_API_COLOR)
	$(DC_PROD) up -d --force-recreate $(PROD_API_SERVICE)

prod-restart: ## Перезапустить все prod-контейнеры
	$(DC_PROD) restart

prod-api-restart: ## Простой перезапуск API color без обновления кода и rebuild
	$(DC_PROD) restart $(PROD_API_SERVICE)

prod-bot-restart: ## Перезапустить prod-бота
	$(DC_PROD) restart bot

prod-worker-down: ## Остановить prod RQ-воркеры
	$(DC_PROD) stop worker-import worker-dom-1 worker-dom-2 worker-finalize worker-translation

prod-worker-restart: ## Перезапустить prod RQ-воркеры
	$(DC_PROD) up -d \
		--scale worker-import=$(WORKER_IMPORT_SCALE) \
		--scale worker-dom-1=$(WORKER_DOM_LANE_1_SCALE) \
		--scale worker-dom-2=$(WORKER_DOM_LANE_2_SCALE) \
		--scale worker-translation=$(WORKER_TRANSLATION_SCALE) \
		worker-import worker-dom-1 worker-dom-2 worker-finalize worker-translation

prod-worker-logs: ## Хвост логов всех prod-воркеров
	$(DC_PROD) logs -f worker-import worker-dom-1 worker-dom-2 worker-finalize worker-translation

prod-worker-import-logs: ## Хвост логов prod worker-import
	$(DC_PROD) logs -f worker-import

prod-worker-dom-logs: ## Хвост логов prod worker-dom-1 и worker-dom-2
	$(DC_PROD) logs -f worker-dom-1 worker-dom-2

prod-worker-finalize-logs: ## Хвост логов prod worker-finalize
	$(DC_PROD) logs -f worker-finalize

prod-translation-logs: ## Хвост логов prod worker-translation
	$(DC_PROD) logs -f worker-translation

prod-translation-dispatch: ## Поставить translation jobs на prod: make prod-translation-dispatch LIMIT=40
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.translation_job --dispatch $(if $(LIMIT),--limit $(LIMIT),)

prod-translation-dispatch-dry: ## Кандидаты translation на prod без enqueue
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.translation_job --dispatch --dry-run $(if $(LIMIT),--limit $(LIMIT),)

prod-login-lane: ## Prod DOM session на хосте: make prod-login-lane LANE=1 (или LANE=2)
	@$(MAKE) login-lane LANE=$(LANE)

prod-tracking-logs: ## Хвост логов prod worker-tracking
	$(DC_PROD) logs -f worker-tracking

prod-availability-logs: ## Хвост логов prod worker-availability
	$(DC_PROD) logs -f worker-availability

prod-queue-clear-failed: ## Сбросить failed RQ jobs на prod
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.clear_failed_rq_jobs

prod-queue-status: ## Счётчики очередей RQ на prod
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -c '\
import json; from src.jobs.queue import get_catalog_queue_stats; \
print(json.dumps(get_catalog_queue_stats(), indent=2, ensure_ascii=False))'

prod-redis-logs: ## Хвост логов prod Redis
	$(DC_PROD) logs -f redis

prod-facets-cache-clear: ## Сбросить кэш фасетов на prod
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -c '\
from src.services.catalog.read.caches import invalidate_catalog_facets_cache; \
print(f"Сброшено ключей: {invalidate_catalog_facets_cache()}")'

prod-subcategories-cache-clear: ## Сбросить кэш подкатегорий на prod
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -c '\
from src.services.catalog.read.caches import invalidate_catalog_subcategories_cache; \
print(f"Сброшено ключей: {invalidate_catalog_subcategories_cache()}")'

prod-catalog-stock-refresh: ## Пересчитать остатки каталога на prod
	$(DC_PROD) exec -T -e PYTHONPATH=/app $(PROD_API_SERVICE) uv run python scripts/refresh_catalog_stock.py

prod-eur-rate-refresh: ## Обновить курс EUR на prod (cron */30 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.eur_pricing_job --task rate

prod-eur-price-recalc: ## Пересчитать цены EUR на prod (cron раз в 6 ч)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.eur_pricing_job --task prices

prod-dom-rolling: ## DOM scheduler на prod (cron */5 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.dom_scheduler

prod-dom-doctor: ## DOM doctor на prod (cron каждые 6 ч): HOLD → FULL enqueue
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.dom_doctor

prod-libretranslate: ## Поднять/пересоздать LibreTranslate на prod
	$(DC_PROD) up -d --force-recreate --no-deps libretranslate

prod-libretranslate-health: ## GET /health LibreTranslate из worker-import
	$(DC_PROD) exec -T worker-import uv run python -c '\
import sys, urllib.request; \
r = urllib.request.urlopen("http://libretranslate:5000/health", timeout=15); \
body = r.read().decode(); \
print(r.status, body); \
sys.exit(0 if r.status == 200 and "ok" in body else 1)'

prod-payment-reconciliation: ## Сверка оплат на prod (cron раз в минуту)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.payment_reconciliation_job

prod-unpaid-order-expiration: ## Автоотмена неоплаченных заказов на prod (cron */5 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.unpaid_order_expiration_job

prod-support-attachment-retention: ## Retention фото поддержки на prod (cron daily)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.support_attachment_retention_job

prod-supplier-tracking: ## Поставить в очередь проверки трекинга (cron */15 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.supplier_tracking_scheduler

prod-delivered-alert-retry: ## Повторная отправка оповещений о доставке заказа (cron */5 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.orders.delivered_alert_retry_scheduler

prod-notification-outbox: ## Доставка TG из outbox на prod (cron */1 мин)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.notification_outbox_job

prod-parser-nightly: ## Ночной GraphQL discovery + finalize на prod
	$(DC_PROD) --profile scraper run --rm scraper

prod-dom-watchdog: ## Проверить зависшие catalog_dom jobs на prod (dry-run)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.dom_watchdog

prod-dom-watchdog-apply: ## Вернуть зависшие catalog_dom jobs в очередь на prod
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python -m src.jobs.dom_watchdog --apply

prod-backup: ## Бэкап Postgres в PROD_BACKUP_DIR
	@chmod +x scripts/backup_postgres.sh scripts/disk_cleanup.sh 2>/dev/null || true
	@mkdir -p "$(PROD_BACKUP_DIR)"
	BACKUP_DIR="$(PROD_BACKUP_DIR)" COMPOSE_FILE=$(COMPOSE_FILE_PROD) ./scripts/backup_postgres.sh

prod-disk-cleanup: ## Очистка диска при заполнении >= 80%
	@chmod +x scripts/disk_cleanup.sh 2>/dev/null || true
	BACKUP_DIR="$(PROD_BACKUP_DIR)" ./scripts/disk_cleanup.sh

prod-media-cleanup: ## Удалить сироты media на prod
	@chmod +x scripts/prune_orphan_media.sh 2>/dev/null || true
	COMPOSE_FILE=$(COMPOSE_FILE_PROD) API_SERVICE=$(PROD_API_SERVICE) ./scripts/prune_orphan_media.sh

prod-remove-duplicate-previews: ## Запустить скрипт удаления дубликатов превью _300/_600/_900 копий
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_remove_duplicate_previews.py

prod-remove-duplicate-previews-apply: ## Удалить дубликаты превью _300/_600/_900 копий (CONFIRM=1)
	@test "$(CONFIRM)" = "1" || (echo "Сначала пробный запуск: make prod-remove-duplicate-previews" && echo "Потом: make prod-backup && make prod-remove-duplicate-previews-apply CONFIRM=1" && exit 1)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_remove_duplicate_previews.py --apply

prod-backfill-image-variants: ## Сгенерировать missing _300/_600/_900 (dry-run)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/backfill_product_image_variants.py

prod-backfill-image-variants-apply: ## Сгенерировать missing _300/_600/_900 (CONFIRM=1)
	@test "$(CONFIRM)" = "1" || (echo "Сначала: make prod-backfill-image-variants" && echo "Потом: make prod-backup && make prod-backfill-image-variants-apply CONFIRM=1" && exit 1)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/backfill_product_image_variants.py --apply

prod-migrate-media-to-s3: ## I5 dry-run: originals local → S3 (не пишет)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_product_media_to_s3.py

prod-migrate-media-to-s3-apply: ## I5 apply originals local → S3 (CONFIRM=1; не удаляет local)
	@test "$(CONFIRM)" = "1" || (echo "Сначала: make prod-migrate-media-to-s3" && echo "Потом: make prod-migrate-media-to-s3-apply CONFIRM=1" && exit 1)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_product_media_to_s3.py --apply

prod-migrate-media-variants-to-s3: ## I5 dry-run: variants local → S3 (не пишет)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_product_media_to_s3.py --variants-only

prod-migrate-media-variants-to-s3-apply: ## I5 apply variants local → S3 (CONFIRM=1; не удаляет local)
	@test "$(CONFIRM)" = "1" || (echo "Сначала: make prod-migrate-media-variants-to-s3" && echo "Потом: make prod-backup && make prod-migrate-media-variants-to-s3-apply CONFIRM=1" && exit 1)
	$(DC_PROD) exec -T $(PROD_API_SERVICE) uv run python scripts/media/migrate_product_media_to_s3.py --variants-only --apply

prod-cron-help: ## Строки для crontab -e (prod-обслуживание)
	@echo "=== Cron (подставьте путь, если не /opt/shopstore) ==="
	@echo "55 2 * * * cd $(CURDIR) && BACKUP_DIR=$(PROD_BACKUP_DIR) $(MAKE) -C $(CURDIR) prod-backup >> /var/log/shopstore-backup.log 2>&1"
	@echo "0 * * * * cd $(CURDIR) && BACKUP_DIR=$(PROD_BACKUP_DIR) $(MAKE) -C $(CURDIR) prod-disk-cleanup >> /var/log/shopstore-disk-cleanup.log 2>&1"
	@echo "0 4 * * 0 cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-media-cleanup >> /var/log/shopstore-media-cleanup.log 2>&1"
	@echo "*/30 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-eur-rate-refresh >> /var/log/shopstore-eur-rate.log 2>&1"
	@echo "0 */6 * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-eur-price-recalc >> /var/log/shopstore-eur-price.log 2>&1"
	@echo "*/5 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-dom-rolling >> /var/log/shopstore-dom-rolling.log 2>&1"
	@echo "0 */6 * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-dom-doctor >> /var/log/shopstore-dom-doctor.log 2>&1"
	@echo "0 3 * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-parser-nightly >> /var/log/shopstore-parser-nightly.log 2>&1"
	@echo "*/10 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-dom-watchdog-apply >> /var/log/shopstore-dom-watchdog.log 2>&1"
	@echo "*/10 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-translation-dispatch >> /var/log/shopstore-translation-dispatch.log 2>&1"
	@echo "*/1 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-payment-reconciliation >> /var/log/shopstore-payment-reconciliation.log 2>&1"
	@echo "*/5 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-unpaid-order-expiration >> /var/log/shopstore-unpaid-order-expiration.log 2>&1"
	@echo "20 4 * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-support-attachment-retention >> /var/log/shopstore-support-attachment-retention.log 2>&1"
	@echo "*/15 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-supplier-tracking >> /var/log/shopstore-supplier-tracking.log 2>&1"
	@echo "*/5 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-delivered-alert-retry >> /var/log/shopstore-delivered-alert-retry.log 2>&1"
	@echo "*/1 * * * * cd $(CURDIR) && $(MAKE) -C $(CURDIR) prod-notification-outbox >> /var/log/shopstore-notification-outbox.log 2>&1"
	@echo ""
	@echo "Один раз: touch /var/log/shopstore-backup.log /var/log/shopstore-disk-cleanup.log /var/log/shopstore-media-cleanup.log /var/log/shopstore-eur-rate.log /var/log/shopstore-eur-price.log /var/log/shopstore-dom-rolling.log /var/log/shopstore-dom-doctor.log /var/log/shopstore-parser-nightly.log /var/log/shopstore-dom-watchdog.log /var/log/shopstore-translation-dispatch.log /var/log/shopstore-payment-reconciliation.log /var/log/shopstore-unpaid-order-expiration.log /var/log/shopstore-support-attachment-retention.log /var/log/shopstore-supplier-tracking.log /var/log/shopstore-delivered-alert-retry.log /var/log/shopstore-notification-outbox.log"
