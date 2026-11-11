.DEFAULT_GOAL := help

.PHONY: \
	help \
	migrate migrate-create lint check fmt format mypy test test-unit test-integration media-cleanup media-remove-duplicate-previews media-backfill-image-variants media-verify-local-vs-s3 media-remove-local-product-media env-check \
	referral-verification-prep \
	referral-verification \
	up up-d down dev logs stack-logs restart env-reload stack-restart start \
	db-up db-down db-logs db-restart \
	redis-up redis-down redis-logs redis-restart \
	s3-up seaweedfs-up seaweedfs-down seaweedfs-logs seaweedfs-restart \
	libretranslate \
	api-up api-down api-logs api-restart \
	storefront-dev storefront-build storefront-budget storefront-install storefront-build-docker \
	bot bot-up bot-down bot-logs bot-restart \
	worker-up worker-down worker-logs worker-import-logs worker-dom-logs worker-finalize-logs worker-restart \
	catalog-workers-up catalog-workers-down catalog-workers-logs workers-up-all workers-down-all workers-logs-all \
	translation-up translation-down translation-logs translation-dispatch translation-dispatch-dry \
	pricing-up pricing-down pricing-logs tracking-up tracking-down tracking-logs availability-up availability-down availability-logs availability-check \
	queue-clear-failed queue-status facets-cache-clear subcategories-cache-clear catalog-stock-refresh order-paid \
	parser parser-graphql parser-login login login-lane push-scraper-sessions \
	dom-rolling dom-watchdog dom-watchdog-apply \
	eur-rate-refresh eur-price-recalc \
	prod-up prod-infra-up prod-down prod-logs prod-restart \
	prod-deploy-api prod-migrate prod-roll-api-blue prod-roll-api-green \
	prod-prod-preflight prod-prod-gate-blue prod-prod-gate-green prod-api-wait-blue prod-api-wait-green \
	prod-api-build prod-api-up-blue prod-api-up-green \
	prod-api-smoke-blue prod-api-smoke-green prod-api-env prod-api-restart \
	prod-bot-restart prod-worker-restart prod-worker-logs \
	prod-worker-import-logs prod-worker-dom-logs prod-worker-finalize-logs \
	prod-translation-logs prod-translation-dispatch prod-translation-dispatch-dry prod-login-lane \
	prod-backup prod-disk-cleanup prod-media-cleanup prod-remove-duplicate-previews prod-remove-duplicate-previews-apply prod-cron-help \
	prod-queue-clear-failed prod-queue-status \
	prod-redis-logs prod-facets-cache-clear prod-subcategories-cache-clear prod-catalog-stock-refresh \
	prod-eur-rate-refresh prod-eur-price-recalc \
	prod-dom-rolling prod-dom-watchdog prod-dom-watchdog-apply prod-dom-doctor prod-parser-nightly \
	prod-libretranslate prod-libretranslate-health \
	api-smoke admin-smoke

ifneq (,$(wildcard .env))
include .env
export
endif

ALEMBIC_DATABASE_URL ?= postgresql+psycopg2://shopstore:shopstore@localhost:5437/shopstore_db
MSG ?= new_migration

DC := docker compose
DC_PROD := docker compose -f docker-compose.prod.yml
COMPOSE_FILE_PROD := docker-compose.prod.yml
PROD_BACKUP_DIR ?= /var/backups/shopstore
WORKER_IMPORT_SCALE ?= 1
WORKER_TRANSLATION_SCALE ?= 1
WORKER_DOM_LANE_1_SCALE ?= 1
WORKER_DOM_LANE_2_SCALE ?= 1

STOREFRONT_DIR := frontend
NODE_IMAGE ?= node:22-bookworm-slim

include make/dev.mk
include make/storefront.mk
include make/workers.mk
include make/parser.mk
include make/prod.mk
include make/quality.mk
include make/test.mk

help: ## Показать справку по командам
	@printf '\nShopstore — команды\n'
	@awk 'BEGIN {FS = ":.*##"; printf "\nИспользование:\n  make \033[36m<target>\033[0m\n"} \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }; \
	  /^[a-zA-Z0-9][a-zA-Z0-9._-]*:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' \
	  $(MAKEFILE_LIST)
