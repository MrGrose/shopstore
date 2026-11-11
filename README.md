# Shopstore

![Каталог Shopstore](docs/assets/shopstore-catalog.webp)

## Локальная демонстрация

```bash
docker compose up -d --build db redis api
```

API и витрина: `http://localhost:8010`. Парсеры, воркеры, Telegram-бот и
LibreTranslate в этом режиме не запускаются. Для чистой базы выполните
`make storefront-mapping-seed`, затем активируйте release скриптами из
`scripts/storefront_mapping/README.md`.

В локальной базе загружены демонстрационные товары, чтобы каталог и карточка были не пустыми.

Бэкенд и веб-витрина магазина спортивных товаров с интеграцией Telegram-бота.

## Стек

- Python 3.12
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- Aiogram (Telegram-бот)
- Uvicorn
- Docker Compose

## Структура проекта

```text
src/
  api/            # REST-роутеры и зависимости
  core/           # конфигурация приложения и безопасность
  integrations/   # внешние интеграции (Telegram, платежи)
  models/         # ORM-модели SQLAlchemy
  repositories/   # слой доступа к данным
  schemas/        # Pydantic-схемы
  services/       # бизнес-логика
  web/            # веб-роуты для страниц
  templates/      # Jinja-шаблоны
  static/         # css/js-ассеты
  bot/            # точка входа Telegram-бота
  main.py         # точка входа FastAPI

alembic/          # миграции БД
Dockerfile
docker-compose.yml
pyproject.toml
```

## Переменные окружения

Создайте `.env` в корне проекта:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5437
POSTGRES_USER=shopstore
POSTGRES_PASSWORD=shopstore
POSTGRES_DB=shopstore_db

AUTH_SECRET=change-me
APP_ENV=prod
DEV_AUTH_BYPASS=false
# Локально: APP_ENV=dev — вход по email на /login (OTP в логах API, если SMTP не настроен).
# Web-вход по телефону: Zvonok; старые Telegram Gateway endpoints сохранены.

TG_BOT_SHOP=
TG_MINI_APP_URL=
TG_ADMIN_ID=0
```

Опционально:

- `DATABASE_URL` - полный DSN для переопределения подключения к БД
- `STORAGE_BACKEND` — `local` (файлы в `MEDIA_ROOT`), `dual` (запись local+S3, чтение S3 затем local) или `s3` (SeaweedFS S3). Production target после миграции — `s3`; до cutover остаётся `local`. Скрипты: [`scripts/media/README.md`](scripts/media/README.md)
- `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` — S3-compatible SeaweedFS. Браузер не ходит на `:8333`; картинки только через `/media/products/...`.
- `TELEGRAM_GATEWAY_ACCESS_TOKEN` — [Telegram Gateway](https://gateway.telegram.org/) Verification Codes для входа и привязки телефона (см. ниже)

### Авторизация на витрине

На `/login` (React-витрина) доступны способы входа:

| Способ | Где | Настройка |
|--------|-----|-----------|
| Telegram | виджет / Mini App | `TG_BOT_USERNAME`, `TG_BOT_SHOP` |
| Email | код на почту | SMTP или `APP_ENV=dev` (код в логах API) |
| Телефон | каскад звонков Zvonok | `PHONE_AUTH_ENABLED`, `ZVONOK_PUBLIC_KEY` |

**Web-вход по телефону** использует ручной каскад: Flash Call → диктовка кода → звонок на проверочный номер. На каждый способ доступно не больше двух звонков с паузой 30 секунд. При первом входе создаётся пользователь с phone-identity; повторный вход открывает тот же аккаунт.

API:

- `POST /auth/phone/start` — создать flow и запустить первый звонок
- `GET /auth/phone/{flow_id}` — получить состояние flow
- `POST /auth/phone/{flow_id}/retry` — вручную повторить текущий способ
- `POST /auth/phone/{flow_id}/switch` — вручную перейти к следующему способу
- `POST /auth/phone/{flow_id}/verify` — проверить четырёхзначный код
- `POST /auth/phone/{flow_id}/complete` — завершить вход после проверочного звонка

Старые `/auth/phone/send-code` и `/auth/phone/verify` через Telegram Gateway оставлены для совместимости и привязки identities.

**Привязка телефона в ЛК** (уже залогиненный пользователь, например через Telegram): раздел «Способы входа» → телефон → код. Если на номере был отдельный phone-only аккаунт, данные сливаются в текущий.

- `POST /users/me/identities/phone/send-code` — Bearer, тело как у login
- `POST /users/me/identities/phone/verify` — Bearer, подтверждение и merge

Переменные в `.env` (пример в `.env.example`):

```env
TELEGRAM_GATEWAY_ACCESS_TOKEN=   # токен с gateway.telegram.org
# PHONE_LOGIN_CODE_TTL_SECONDS=600
# PHONE_LOGIN_SEND_COOLDOWN_SECONDS=60
# PHONE_LOGIN_RATE_LIMIT_PHONE=3
# PHONE_LOGIN_RATE_LIMIT_IP=10
# PHONE_LOGIN_VERIFY_MAX_ATTEMPTS=5
PHONE_AUTH_ENABLED=false
PHONE_AUTH_CHANNEL_ORDER=flash_call,voice_code,verification_number
ZVONOK_ENABLED=false
ZVONOK_PUBLIC_KEY=
```

Для каскада нужны **Redis**, включённые `PHONE_AUTH_ENABLED` и `ZVONOK_ENABLED`, ключ Zvonok и исходящий HTTPS. Секретный ключ нельзя писать в URL и логи.

Локально: `make db-up` + Redis из `docker compose`, токен в `.env`, перезапуск API (`make start` или `docker compose up -d --force-recreate api`).


На витрине и в Mini App подключены футер и статические документы. Тексты в репозитории — **типовой черновик**, их нужно сверить с юристом и подставить **реальные реквизиты** в `.env`.

| URL | Назначение |
|-----|------------|
| `/privacy` | Политика конфиденциальности (152-ФЗ) |
| `/terms` | Пользовательское соглашение / публичная оферта |
| `/consent` | Согласие на обработку ПДн (текст для checkout) |
| `/returns` | Возврат и обмен |

**Переменные в `.env`** (без заполнения реквизиты на сайте не показываются — будет предупреждение):

```env
LEGAL_ENTITY_NAME=ИП Иванов Иван Иванович
LEGAL_INN=000000000000
LEGAL_OGRNIP=000000000000000
LEGAL_ADDRESS=000000, г. Москва, ул. Пример, д. 1
LEGAL_EMAIL=shop@example.com
LEGAL_PHONE=+7 (999) 000-00-00
LEGAL_REVISION_DATE=27.05.2026
PUBLIC_SITE_URL=https://your-domain.example
```

**Где лежит код:**

- шаблоны: `src/templates/site/legal/` (`privacy.html`, `terms.html`, `consent.html`, `returns.html`)
- футер: `src/templates/site/_footer.html` (веб-витрина; в checkout Mini App — ссылки на legal внизу формы)
- роуты: `src/web/routers/site_pages.py`
- реквизиты из env: `src/web/storefront_legal.py`, глобал `legal` в `src/web/templating.py`
- согласие на checkout: чекбокс в `src/templates/site/checkout.html`, логика в `src/static/site/js/checkout.js`

**Чеклист перед публикацией:**

| Что проверить | В коде / на сайте |
|---------------|-------------------|
| Заменены тестовые контакты (email, телефон, ИНН, адрес) | Заполнить все `LEGAL_*` в `.env` на проде |
| Нет англ. solely в политике | п. 5.2: «исключительно» |
| Таблица в п. 4 политики | HTML-таблица с `scope="col"`, ссылки на `/terms` и `/consent` |
| Ссылка на `/terms` | футер, privacy п. 1.2, checkout, login |
| Ссылка на `/consent` | футер, privacy, checkout, login |
| Точная дата редакции | `LEGAL_REVISION_DATE` (ДД.ММ.ГГГГ), иначе — текущая UTC |
| Документы на сайте, не в Google Docs | страницы `/privacy`, `/terms`, … |
| Ссылка в футере на `/privacy` | «Политика конфиденциальности» |

Дополнительно: отдать тексты юристу (SBP, доставка, Перечень 2463); проверить checkout и Mini App.

**После смены `LEGAL_*` в `.env`:** `docker compose restart api` **не подхватывает** новые переменные — нужно пересоздать контейнер:

```bash
docker compose up -d --force-recreate api
```

После правок только шаблонов/кода (без `.env`) достаточно `docker compose restart api`.

## Быстрый старт (Docker)

```bash
make up
```

`make up` и `make up-d` поднимают только базовый стек: `db`, `redis`, `api`,
`bot`. Воркеры запускаются отдельно:

```bash
make pricing-up          # пересчёт наценок
make availability-up     # проверка наличия поставщика
make catalog-workers-up  # import + dom + finalize
make workers-up-all      # все воркеры
```

Сервисы:

- API: `http://localhost:8010`
- PostgreSQL доступен на порту `5437` хоста

Запуск в фоне:

```bash
make up-d
```

Остановка базового стека:

```bash
make down
```

## Локальный запуск (API вне Docker)

Запустить контейнер с БД:

```bash
make db-up
```

Запустить API локально:

```bash
make start
```

Локальный адрес API:

- `http://localhost:8001`

## Миграции

Создать миграцию:

```bash
make migrate-create MSG=add_new_table
```

Применить миграции:

```bash
make migrate
```

## Telegram-бот

Локальный запуск бота:

```bash
make bot
```

Обязательные значения в `.env`:

- `TG_BOT_SHOP`
- `TG_MINI_APP_URL`

## Основные группы API

- `/products` - каталог и данные товаров
- `/cart` - операции с корзиной
- `/orders` - заказы: `POST /orders/checkout` (оформление), `GET /orders/my`; legacy `POST /orders` → **410 Gone**
- `/payment` - платежный поток
- `/auth` - авторизация (Telegram, email OTP, phone verification codes)
- `/admin/*` - административные роуты

## Подтверждение наличия (пограничный остаток)

Если при checkout **хотя бы одна позиция** имеет доступный остаток `0 < available < STOCK_LOW_MIN_QTY` (по умолчанию `2`):

| Что происходит | Значение |
|----------------|----------|
| Заказ | создаётся, статус `processing` |
| `availability_confirmation_status` | `pending` |
| Оплата | заблокирована (`payment_allowed=false`) |
| Админ | отдельное TG-уведомление с позициями для проверки |
| Клиент | бейдж и строка «Оплата»: «Проверяем наличие»; над кнопкой «Оплата станет доступна после проверки.»; кнопка «Оплатить» disabled |

**Админка** (`/internal/admin/orders?id=…`):

- блок «Подтверждение наличия» — **Подтвердить** / **Товар недоступен**;
- «Товары для проверки остатка» — ссылка `#id Название`, остаток/доступно, бейдж «На витрине» / «Снят с витрины» (по галочке `is_active`, без auto-снятия);
- заказы с `pending` подсвечиваются в списке (оранжевая полоска слева).

**После решения админа:**

| Действие | Результат |
|----------|-----------|
| Подтвердить | `confirmed`, оплата доступна |
| Товар недоступен | `unavailable`, оплата недоступна, клиенту «Часть товаров недоступна.» |

Статус заказа при reject **не** меняется на `cancelled`; inventory / `is_active` **не** трогаются автоматически — только вручную в карточке товара.

**Ключевые файлы:**

- `src/services/orders/order_service.py` — `_collect_low_stock_items`, `confirm_availability`, `mark_availability_unavailable`
- `src/services/payment_service.py` — guard `payment_allowed`
- `src/services/admin_notification_service.py` — TG админу
- `src/web/routers/admin_orders_pages.py` — POST confirm/reject
- `src/templates/site/admin/partials/_order_availability_stock_check.html`
- `frontend/src/app/components/OrdersList.tsx`, `CheckoutOrderAcceptedDialog.tsx`

**Тесты:** `tests/unit/test_order_availability.py` · `make test-unit`

**Переменная:** `STOCK_LOW_MIN_QTY` в `.env` / `src/core/config.py` (порог «мало на складе»).

## Быстрая загрузка каталога (витрина / Mini App)

### Как устроено

**API (разделённые ответственности):**

| Эндпоинт | Назначение |
|----------|------------|
| `GET /products` | Список карточек **без** `COUNT(*)` (`count_total=False`) |
| `GET /products/count` | Число товаров в текущем срезе (Redis, отдельно от списка) |
| `GET /products/subcategories` | Pills подкатегорий; без `?sub=` — только slug/label (скелет), с `?sub=rackets` — L2/L3 и счётчики для одной ветки |

**Бэкенд:**

- **Redis-кэш подкатегорий** — `src/services/catalog/read/subcategories_cache.py`, TTL `CATALOG_SUBCATEGORIES_CACHE_TTL_SECONDS` (по умолчанию 900 с).
- **Redis-кэш count** — `src/services/catalog/read/count_cache.py`, TTL `CATALOG_COUNT_CACHE_TTL_SECONDS` (по умолчанию 180 с).
- **Ленивая загрузка** — `CatalogService.get_catalog_subcategories()`: полные счётчики L2/L3 только при `?sub=`, не для всего дерева сразу.
- **Параллель L2/L3** — `asyncio.gather` в **разных** `async_session_maker()` сессиях (одна сессия на два запроса даёт 500).
- **Денормализация остатков** — поля `products.catalog_in_stock` и `products.available_qty` (миграция `j1k2l3m4n5o6`); фильтр «в наличии» без `stock − reserved` на каждый ряд. Обновление: `CatalogStockService` при заказах/импорте + `scripts/refresh_catalog_stock.py`. **Админка:** вкладка «Нулевой остаток» = `catalog_in_stock = false`

**Фронт (`frontend/src/lib/storefront/`):**

- `subcategoriesCache.ts` — кэш ответов по `top` + `sub` на клиенте.
- `catalog.ts` — `fetchCatalogSubcategories(top, sub?)`, `fetchCatalogProductCount(...)`.
- `prefetchCatalogSubcategories.ts` + `MiniAppLayout` — прогрев pills в idle.
- `ProductGrid` — скелет pills сразу, детали по клику/фильтру; count параллельно со списком.

### Обслуживание (не забыть)

После массового импорта или правок таксономии (`src/core/catalog_subcategories.py`):

```bash
make subcategories-cache-clear    # prod: make prod-subcategories-cache-clear
make facets-cache-clear           # prod: make prod-facets-cache-clear
```

Импорт каталога: после каждого чанка `refresh_products` только для затронутых id; в finalize (`run_catalog_deactivate_missing`) — один `refresh_all()`. `catalog_import_job` сбрасывает facets / subcategories / count в Redis.

`make catalog-stock-refresh` — backfill после миграции, cron-сверка, аварийный сброс; **обязателен после правок storefront registry** (`l2_sets.py`, `storefront_nav.py`) — пересчёт `catalog_in_stock`, `available_qty`, `storefront_nav_status`

Переменные в `.env`: `CATALOG_SUBCATEGORIES_CACHE_TTL_SECONDS`, `CATALOG_COUNT_CACHE_TTL_SECONDS`, `CATALOG_FACETS_CACHE_TTL_SECONDS` (`0` — отключить кэш).

Ключевые файлы: `src/services/catalog/read/service.py`, `src/repositories/product_repo.py`, `src/services/catalog/stock/service.py`.

## Деплой на VPS (кратко)

- **Бэкап БД и очистка диска:** `scripts/backup_postgres.sh`, `scripts/disk_cleanup.sh` — на сервере `make prod-backup`, `make prod-disk-cleanup`, cron: `make prod-cron-help` (подробнее [`scripts/README.md`](scripts/README.md)).
- Домен и HTTPS (Caddy/Nginx) → `PUBLIC_SITE_URL`, `TG_MINI_APP_URL`, `ALLOWED_HOSTS`.
- В **@BotFather**: Domain для Login Widget и URL Mini App (`/app`).
- `TG_BOT_USERNAME` — **@username** бота (без `@`), не отображаемое имя.
- Если с сервера **нет исходящего HTTPS** (таймаут `curl https://api.telegram.org/`):
  - в корневом `.env`: `TG_BOT_PROXY=http://user:pass@host:port` (тот же прокси, что для скрапера);
  - worker подхватывает `HTTP_PROXY` / `HTTPS_PROXY` из `TG_BOT_PROXY` (см. `docker-compose.yml`).
- **DHL tracking:** datacenter IP на prod может блокироваться Akamai:
  - `DHL_TRACKING_PROXY_URL=http://user:pass@host:port` — residential proxy для HTTP (опционально);
  - `DHL_TRACKING_USE_BROWSER=true` (default) — третий шаг: Playwright на отдельном `worker-dhl`, очередь `dhl_browser_tracking`;
  - после смены env — пересоздать `worker-tracking` и `worker-dhl`; проверка — «Проверить сейчас» в админке заказа с CJ.

Проверка бота: `docker compose logs -f bot` → `Start polling` без `TelegramNetworkError`.

Парсер и worker: `make parser` / `docker compose --profile scraper run --rm scraper`, очередь `catalog`, логи `docker compose logs -f worker`.

## Импорт каталога: сначала без картинок, потом с картинками

На слабом VPS (~4 ГБ RAM) worker при `download_images=true` может падать с **exit 137 (OOM)** — в БД останется 0 товаров.

### Фаза 1 — заполнить каталог (без скачивания файлов)

В `src/scraper/.env`:

```env
SCRAPER_IMPORT_DOWNLOAD_IMAGES=false
```

Очистить зависшую очередь (если нужно) и запустить парсер заново. В БД появятся товары, цены, описания. CDN поставщика пишется в `product_images.source_url`, managed `url` пустой. Cover `products.image_url` остаётся NULL, пока нет `/media`.

Проверка:

```bash
docker compose exec db psql -U shopstore -d shopstore_db -c "SELECT count(*) FROM products;"
```

### Фаза 2 — докачать картинки на сервер

Когда есть запас по RAM:

1. **Swap** (пример 2 ГБ) *или* VPS с большей памятью (8 ГБ+).
2. В `src/scraper/.env`:

```env
SCRAPER_IMPORT_DOWNLOAD_IMAGES=true
```

3. Повторный прогон парсера (`make parser` или `docker compose --profile scraper run --rm scraper`).

`ProductService.import_products` обновит существующие товары по `external_id` / URL и скачает изображения в Storage (`STORAGE_BACKEND`: local / dual / s3). CDN остаётся в `source_url`. Нужны `TG_BOT_PROXY` / прокси для worker, если прямой HTTPS с VPS недоступен.

Очередь перед повтором при необходимости сбросить:

```bash
docker compose exec redis redis-cli DEL rq:queue:catalog rq:failed:catalog rq:started:catalog
docker compose up -d worker
```

Подробнее о файлах парсера — [`src/scraper/README.md`](src/scraper/README.md).

LibreTranslate (fallback EN→RU, не Google): сервис `libretranslate` в compose, volume `lt_models`. В `worker-import` / `worker-dom-1` / `worker-dom-2` / `worker-translation` задано `SCRAPER_LIBRETRANSLATE_URL=http://libretranslate:5000`. Локально без сервиса URL пустой — поведение Phase 5. Timeout: `SCRAPER_LIBRETRANSLATE_TIMEOUT` (default 60).

## Примечания

- При старте приложения может выполняться автозаполнение демо-данными.
- Не коммитьте `.env` и любые секретные ключи в git.
