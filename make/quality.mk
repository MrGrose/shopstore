# ============================================================
# Database, quality, tests, agent index
# ============================================================

##@ База данных

migrate: ## Применить все миграции Alembic (локальная БД :5433)
	DATABASE_URL=$(ALEMBIC_DATABASE_URL) uv run alembic upgrade head

migrate-create: ## Создать миграцию: make migrate-create MSG="название"
	DATABASE_URL=$(ALEMBIC_DATABASE_URL) uv run alembic revision --autogenerate -m "$(MSG)"

##@ Качество

lint: ## Ruff check --fix
	uv run ruff check --fix .

check: lint

env-check: ## Проверить .env.* против .env.example
	uv run python scripts/env_doctor.py

fmt: ## Ruff format
	uv run ruff format .

format: fmt

mypy: ## Format + lint + pre-commit mypy
	$(MAKE) format
	$(MAKE) check
	pre-commit run mypy --all-files

media-cleanup: ## Удалить сироты media локально (без Docker)
	uv run python scripts/prune_orphan_media.py

media-remove-duplicate-previews: ## Запустить скрипт удаления дубликатов превью _300/_600/_900 копий (APPLY=1)
	uv run python scripts/media/migrate_remove_duplicate_previews.py $(if $(filter 1,$(APPLY)),--apply,)

media-backfill-image-variants: ## Заполнить missing _300/_600/_900 via Storage (APPLY=1). Не для production.
	uv run python scripts/media/backfill_product_image_variants.py $(if $(filter 1,$(APPLY)),--apply,)

media-verify-local-vs-s3: ## Сравнить локальные и S3 медиа файлы
	uv run python scripts/media/verify_local_vs_s3_product_media.py

media-remove-local-product-media: ## Удалить локальные медиа файлы (APPLY=1). Не для production.
	uv run python scripts/media/remove_local_product_media.py $(if $(filter 1,$(APPLY)),--apply,)
