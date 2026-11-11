# ============================================================
# Development
# ============================================================

##@ Разработка

DEV_STACK_SERVICES := db redis seaweedfs api bot

up: ## Поднять базовый dev-стек без воркеров (foreground, incl. SeaweedFS S3)
	$(DC) up --build $(DEV_STACK_SERVICES)

up-d: ## Поднять базовый dev-стек без воркеров (фон, incl. SeaweedFS S3)
	$(DC) up -d --build $(DEV_STACK_SERVICES)

dev: up-d ## Алиас для up-d

down: ## Остановить dev-стек (volumes сохраняются)
	$(DC) down

logs: ## Хвост логов всего dev-стека
	$(DC) logs -f

stack-logs: logs

restart: ## Пересоздать dev-стек (подхватить .env)
	$(DC) up -d --force-recreate

env-reload: ## Перезагрузить .env в API (подхватить .env)
	$(DC) up -d --force-recreate api

stack-restart: restart

start: ## Запустить API локально на :8001 (вместе с db-up)
	uv run uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload

##@ Сервисы

db-up: ## Поднять Postgres и применить миграции
	$(DC) up -d db
	sleep 10
	$(MAKE) migrate

db-down: ## Остановить контейнер Postgres
	$(DC) stop db

db-logs: ## Хвост логов Postgres
	$(DC) logs -f db

db-restart: ## Перезапустить Postgres
	$(DC) restart db

redis-up: ## Поднять контейнер Redis
	$(DC) up -d redis

redis-down: ## Остановить контейнер Redis
	$(DC) stop redis

redis-logs: ## Хвост логов Redis
	$(DC) logs -f redis

redis-restart: ## Перезапустить Redis
	$(DC) restart redis

seaweedfs-up: ## Поднять SeaweedFS (S3-compatible storage)
	$(DC) up -d seaweedfs

seaweedfs-down: ## Остановить SeaweedFS
	$(DC) stop seaweedfs

seaweedfs-logs: ## Хвост логов SeaweedFS
	$(DC) logs -f seaweedfs

seaweedfs-restart: ## Перезапустить SeaweedFS
	$(DC) restart seaweedfs

s3-up: seaweedfs-up ## Алиас для seaweedfs-up

libretranslate: ## Поднять контейнер LibreTranslate
	$(DC) up -d libretranslate

api-up: ## Поднять контейнер API
	$(DC) up -d --build api

api-down: ## Остановить контейнер API
	$(DC) stop api

api-logs: ## Хвост логов API
	$(DC) logs -f api

api-restart: ## Перезапустить API
	$(DC) restart api

bot: ## Запустить Telegram-бота локально (не в Docker)
	uv run python -m src.bot.main

bot-up: ## Поднять контейнер бота
	$(DC) up -d --build bot

bot-down: ## Остановить контейнер бота
	$(DC) stop bot

bot-logs: ## Хвост логов бота
	$(DC) logs -f bot

bot-restart: ## Перезапустить бота
	$(DC) restart bot

# ============================================================
##@ Payment

payment-reconciliation: ## Сверка оплат (dev/local)
	uv run python -m src.jobs.payment_reconciliation_job

order-paid: ## Фиктивная оплата заказа: ORDER_ID=123 [CONFIRM=123]
	@test -n "$(ORDER_ID)" || (echo "Укажи ORDER_ID=..." && exit 1)
	PYTHONPATH=. uv run python scripts/mark_order_paid.py --order-id $(ORDER_ID) $(if $(CONFIRM),--confirm-order-id $(CONFIRM),)

unpaid-order-expiration: ## Автоотмена неоплаченных заказов (dev/local)
	uv run python -m src.jobs.unpaid_order_expiration_job

support-attachment-retention: ## Retention фото поддержки (dev/local)
	uv run python -m src.jobs.support_attachment_retention_job

notification-outbox: ## Доставка TG из outbox (dev/local)
	uv run python -m src.jobs.notification_outbox_job

referral-verification-prep: ## BUYER A/B/C/Inactive для ручной проверки referral (APP_ENV=dev)
	ALLOW_REFERRAL_VERIFICATION_SEED=1 REFERRAL_VERIFICATION_ACTION=seed RESET_ATTRIBUTION=$(if $(RESET),1,) \
		PYTHONPATH=. uv run --extra web pytest -s tests/manual/referral_verification_fixture.py -q

referral-verification: ## Автоматическая проверка referral migration
	PYTHONPATH=. uv run --extra web python tests/manual/run_referral_verification.py

storefront-mapping-seed: ## Залить draft release: nodes и rules из UX blueprint JSON
	PYTHONPATH=. uv run python scripts/storefront_mapping/seed_storefront_mapping.py

storefront-catalog-rules-seed: ## Пересидить supplier rules в editable release (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/seed_storefront_catalog_rules.py --release-id $(RELEASE_ID)

storefront-placements-backfill: ## Resolver: placements/resolutions для всех catalogized SKU (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/backfill_storefront_placements.py --release-id $(RELEASE_ID)

storefront-mapping-reconcile: ## Отчёт coverage: unmapped, invalid taxonomy, mapping errors (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/storefront_mapping_reconciler.py --release-id $(RELEASE_ID)

storefront-coverage-verify: ## Gate: exit 1 если release нельзя активировать (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/verify_storefront_coverage.py --release-id $(RELEASE_ID)

storefront-release-verify: ## Пометить release verified после reconcile (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/mark_storefront_release_verified.py --release-id $(RELEASE_ID)

storefront-release-activate: ## Активировать verified release; затем restart API (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/activate_storefront_release.py --release-id $(RELEASE_ID)

storefront-release-rollback: ## Rollback: клон archived release и activate (ARCHIVED_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/rollback_storefront_release.py --from-archived-id $(ARCHIVED_ID)

storefront-mapping-shadow: ## Parity: counts repo vs catalog API, gate перед prod (RELEASE_ID=N)
	PYTHONPATH=. uv run python scripts/storefront_mapping/shadow_compare_storefront_mapping.py --release-id $(RELEASE_ID)
