# Витрина — ветка нового дизайна

**Визуал** — только здесь (`src/app/components`, `pages`).
**Логика** — с бэкенда и из `src/static/site/js/*.js`, переписанная в `src/lib/storefront/` (см. [REFERENCE.md](./REFERENCE.md)).

Старые шаблоны Jinja в этой ветке **не трогаем**.

## Ежедневная работа

```bash
docker compose up -d api    # API :8000
cp frontend/.env.development.example frontend/.env.development  # один раз
make storefront-dev         # UI  :5173
```

Открыть **http://localhost:5173** — новый дизайн, прокси на API.
Для вёрстки витрины используйте `make storefront-dev` (`:5173`). На `:8000` — собранный React (`STOREFRONT_UI=react` + `make storefront-build`).

Dev-вход («Войти локально») остаётся на `:5173` через API, без redirect на Jinja.

## Что не делать в этой ветке

- Не верстать в `src/templates/site/`
- Не подгонять React под старые CSS-классы
- Не «встраивать» новый UI в Jinja

## Что делать

1. Страница → `src/app/pages/*.tsx` (новый UI)
2. Запросы / корзина / auth → `src/lib/storefront/`
3. Сверка поведения → старый JS из таблицы в REFERENCE.md

## Маршруты (react-router)

| URL | Статус |
|-----|--------|
| `/catalog` | UI готов, API в компонентах |
| `/cart`, `/checkout`, `/orders`, `/login` | UI-заглушки, логика через `lib/storefront` |

## Перед merge в main (позже)

```bash
make storefront-build
# в .env: STOREFRONT_UI=react — отдача dist с :8000
```

Это для прода, не для ежедневной вёрстки.

Макет: [Figma](https://www.figma.com/design/8D5dA5jkwNGlVQfiUMh00r/Premium-Dark-Sports-Ecommerce)
