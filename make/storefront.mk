# ============================================================
# Storefront
# ============================================================

##@ Витрина

storefront-install:
	cd "$(STOREFRONT_DIR)" && npm install

storefront-build: storefront-install ## Локально: собрать витрину → frontend/dist (не prod)
	cd "$(STOREFRONT_DIR)" && npm run build

storefront-budget: storefront-build ## Проверить размер сборки витрины
	cd "$(STOREFRONT_DIR)" && npm run budget

storefront-dev: storefront-install ## Локально: Vite dev server (hot reload)
	cd "$(STOREFRONT_DIR)" && npm run dev

storefront-build-docker: ## Локально: сборка через Docker (без npm на хосте)
	docker run --rm \
		-v "$(CURDIR)/$(STOREFRONT_DIR):/app" \
		-w /app \
		$(NODE_IMAGE) \
		sh -c "echo '>>> npm ci' && npm ci && echo '>>> vite build' && npm run build && echo '>>> done'"
