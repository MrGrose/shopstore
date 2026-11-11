# ============================================================
# Workers, queues, cache
# ============================================================

##@ Сервисы

catalog-workers-up: ## Поднять каталог 1+1: import + DOM lanes + finalize
	$(DC) --profile dom-lane-2 up -d --build \
		--scale worker-import=$(WORKER_IMPORT_SCALE) \
		--scale worker-dom-1=$(WORKER_DOM_LANE_1_SCALE) \
		--scale worker-dom-2=$(WORKER_DOM_LANE_2_SCALE) \
		worker-import worker-dom-1 worker-dom-2 worker-finalize redis

catalog-workers-down: ## Остановить каталог: import + DOM lanes + finalize
	$(DC) --profile dom-lane-2 stop worker-import worker-dom-1 worker-dom-2 worker-finalize

catalog-workers-logs: ## Хвост логов каталожных воркеров
	$(DC) --profile dom-lane-2 logs -f worker-import worker-dom-1 worker-dom-2 worker-finalize

workers-up-all: ## Поднять все RQ-воркеры и Redis
	$(DC) --profile dom-lane-2 up -d --build \
		--scale worker-import=$(WORKER_IMPORT_SCALE) \
		--scale worker-dom-1=$(WORKER_DOM_LANE_1_SCALE) \
		--scale worker-dom-2=$(WORKER_DOM_LANE_2_SCALE) \
		--scale worker-pricing=1 \
		--scale worker-tracking=1 \
		--scale worker-availability=1 \
		worker-import worker-dom-1 worker-dom-2 worker-finalize worker-pricing worker-tracking worker-availability redis

workers-down-all: ## Остановить все RQ-воркеры
	$(DC) --profile dom-lane-2 stop worker-import worker-dom-1 worker-dom-2 worker-finalize worker-pricing worker-tracking worker-availability

workers-logs-all: ## Хвост логов всех RQ-воркеров
	$(DC) --profile dom-lane-2 logs -f worker-import worker-dom-1 worker-dom-2 worker-finalize worker-pricing worker-tracking worker-availability

worker-up: workers-up-all ## Алиас для workers-up-all

worker-down: workers-down-all ## Алиас для workers-down-all

worker-logs: workers-logs-all ## Алиас для workers-logs-all

worker-import-logs: ## Хвост логов worker-import
	$(DC) logs -f worker-import

worker-dom-logs: ## Хвост логов worker-dom-1 и worker-dom-2
	$(DC) --profile dom-lane-2 logs -f worker-dom-1 worker-dom-2

worker-finalize-logs: ## Хвост логов worker-finalize
	$(DC) logs -f worker-finalize

translation-up: ## Поднять translation worker (не catalog_dom)
	$(DC) up -d --build --scale worker-translation=$(WORKER_TRANSLATION_SCALE) worker-translation redis

translation-down: ## Остановить worker-translation
	$(DC) stop worker-translation

translation-logs: ## Хвост логов worker-translation
	$(DC) logs -f worker-translation

translation-dispatch: ## Поставить translation jobs: make translation-dispatch LIMIT=20
	$(DC) exec -T api uv run python -m src.jobs.translation_job --dispatch $(if $(LIMIT),--limit $(LIMIT),)

translation-dispatch-dry: ## Кандидаты translation без enqueue
	$(DC) exec -T api uv run python -m src.jobs.translation_job --dispatch --dry-run $(if $(LIMIT),--limit $(LIMIT),)

pricing-up: ## Поднять один worker-pricing
	$(DC) up -d --build --scale worker-pricing=1 worker-pricing

pricing-down: ## Остановить worker-pricing
	$(DC) stop worker-pricing

pricing-logs: ## Хвост логов worker-pricing
	$(DC) logs -f worker-pricing

tracking-logs: ## Хвост логов worker-tracking
	$(DC) logs -f worker-tracking

tracking-up: ## Поднять один worker-tracking
	$(DC) up -d --build --scale worker-tracking=1 worker-tracking

tracking-down: ## Остановить worker-tracking
	$(DC) stop worker-tracking

availability-up: ## Поднять один worker-availability
	$(DC) up -d --build --scale worker-availability=1 worker-availability

availability-down: ## Остановить worker-availability
	$(DC) stop worker-availability

availability-logs: ## Хвост логов worker-availability
	$(DC) logs -f worker-availability

availability-check: ## Поставить проверку заказа в очередь: make availability-check ORDER_ID=123
	@test -n "$(ORDER_ID)" || (echo "Укажите ORDER_ID: make availability-check ORDER_ID=123"; exit 2)
	$(DC) exec -T worker-availability uv run python -m src.jobs.orders.supplier_availability_scheduler --order-id $(ORDER_ID)

worker-restart: ## Пересоздать все RQ-воркеры
	$(DC) --profile dom-lane-2 up -d --force-recreate \
		--scale worker-import=$(WORKER_IMPORT_SCALE) \
		--scale worker-dom-1=$(WORKER_DOM_LANE_1_SCALE) \
		--scale worker-dom-2=$(WORKER_DOM_LANE_2_SCALE) \
		--scale worker-pricing=1 \
		--scale worker-tracking=1 \
		--scale worker-availability=1 \
		worker-import worker-dom-1 worker-dom-2 worker-finalize worker-pricing worker-tracking worker-availability

##@ Кэш и очереди

queue-clear-failed: ## Сбросить failed RQ jobs (import + dom + finalize)
	$(DC) exec -T api uv run python -m src.jobs.clear_failed_rq_jobs

queue-status: ## Счётчики очередей RQ
	$(DC) exec -T api uv run python -c '\
import json; from src.jobs.queue import get_catalog_queue_stats; \
print(json.dumps(get_catalog_queue_stats(), indent=2, ensure_ascii=False))'

facets-cache-clear: ## Сбросить кэш фасетов (catalog:facets:*)
	$(DC) exec -T api uv run python -c '\
from src.services.catalog.read.caches import invalidate_catalog_facets_cache; \
print(f"Сброшено ключей: {invalidate_catalog_facets_cache()}")'

subcategories-cache-clear: ## Сбросить кэш подкатегорий (catalog:subcategories:*)
	$(DC) exec -T api uv run python -c '\
from src.services.catalog.read.caches import invalidate_catalog_subcategories_cache; \
print(f"Сброшено ключей: {invalidate_catalog_subcategories_cache()}")'

catalog-stock-refresh: ## Пересчитать catalog_in_stock и available_qty
	$(DC) exec -T -e PYTHONPATH=/app api uv run python scripts/refresh_catalog_stock.py
