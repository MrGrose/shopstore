# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

FROM base AS builder-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# React-витрина (npm run build) — в образ API, без make storefront-build на VPS.
FROM node:22-bookworm-slim AS storefront-builder
ARG VITE_TG_BOT_USERNAME=""
ENV VITE_TG_BOT_USERNAME=${VITE_TG_BOT_USERNAME}
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM builder-base AS builder-web
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev --extra web
COPY . /app
COPY --from=storefront-builder /frontend/dist /app/frontend/dist
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web

FROM builder-base AS builder-scraper
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev --extra web --extra scraper
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --extra scraper

FROM base AS runtime
ENV UV_NO_SYNC=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=builder-web /app /app
EXPOSE 8000

FROM base AS scraper
ARG TARGETARCH
ENV UV_NO_SYNC=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=builder-scraper /app /app
# arm64 (Mac Docker): Playwright не ставит Google Chrome. amd64 (VPS): chrome для SRC3_PLAYWRIGHT_CHANNEL.
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      /app/.venv/bin/playwright install --with-deps chromium chromium-headless-shell; \
    else \
      /app/.venv/bin/playwright install --with-deps chrome chromium-headless-shell; \
    fi \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
