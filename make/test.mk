# ============================================================
# Pytest, smoke
# ============================================================

##@ Тесты

test: ## Запустить все pytest-тесты
	PYTHONPATH=. uv run --extra web pytest tests/ -q

test-unit: ## Запустить только unit-тесты
	PYTHONPATH=. uv run --extra web pytest tests/unit -q

test-integration: ## Integration-тесты (PostgreSQL)
	PYTHONPATH=. uv run --extra web pytest tests/integration -m integration -q

api-smoke: ## Smoke-тест публичного REST API
	@chmod +x scripts/api_smoke.sh 2>/dev/null || true
	@./scripts/api_smoke.sh

admin-smoke: ## Smoke-тест админских HTMX-маршрутов
	@chmod +x scripts/admin_smoke.sh 2>/dev/null || true
	@./scripts/admin_smoke.sh
