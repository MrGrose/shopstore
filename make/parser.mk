# ============================================================
# Parser & jobs
# ============================================================

##@ Парсер

parser: ## Полный прогон парсера (scraper profile, one-shot)
	$(DC) --profile scraper run --rm scraper

parser-graphql: ## Только GraphQL (без DOM и finalize)
	$(DC) --profile scraper run --rm scraper uv run python -m src.scraper.app --once --graphql-only

login: ## Default session → infrastructure/session/ (availability)
	uv run --extra scraper python -m src.scraper.commands.login

parser-login: ## Логин через контейнер scraper (headless/xvfb/CDP)
	$(DC) --profile scraper run --rm scraper uv run python -m src.scraper.commands.login

LANE ?= 1
login-lane: ## DOM session lane (prod и local): make login-lane LANE=1 или LANE=2
	SCRAPER_STORAGE_STATE_PATH=src/scraper/infrastructure/session-$(LANE)/storage_state.json \
	SCRAPER_LANE_ID=$(LANE) \
	SCRAPER_PROXY_SERVER="$(LANE_$(LANE)_PROXY_SERVER)" \
	SCRAPER_PROXY_USERNAME="$(LANE_$(LANE)_PROXY_USERNAME)" \
	SCRAPER_PROXY_PASSWORD="$(LANE_$(LANE)_PROXY_PASSWORD)" \
		uv run --extra scraper python -m src.scraper.commands.login

push-scraper-sessions: ## session-1 и session-2 на prod (scripts/push_scraper_session.sh)
	./scripts/push_scraper_session.sh

##@ Jobs

dom-rolling: ## DOM scheduler: один тик (INCOMPLETE→FULL, stale→LITE)
	$(DC) run --rm api uv run python -m src.jobs.dom_scheduler

dom-watchdog: ## Проверить зависшие catalog_dom jobs (dry-run)
	$(DC) run --rm api uv run python -m src.jobs.dom_watchdog

dom-watchdog-apply: ## Вернуть зависшие catalog_dom jobs в очередь
	$(DC) run --rm api uv run python -m src.jobs.dom_watchdog --apply

dom-doctor: ## DOM doctor: HOLD → FULL recovery (enqueue-only)
	$(DC) run --rm api uv run python -m src.jobs.dom_doctor

eur-rate-refresh: ## Обновить курс EUR (Rapira)
	$(DC) run --rm api uv run python -m src.jobs.eur_pricing_job --task rate

eur-price-recalc: ## Пересчитать цены по текущему курсу EUR
	$(DC) run --rm api uv run python -m src.jobs.eur_pricing_job --task prices
