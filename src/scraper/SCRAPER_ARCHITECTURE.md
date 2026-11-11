# Архитектура scraper / parsing (step4)

Документ для нового разработчика: как устроен парсинг **без чтения всего кода**.
Сейчас в проде один поставщик — **supplier-demo.com** (Shopify). Архитектура step4
решает главную боль: **медленный DOM и 429 (слишком много запросов)**.

См. также: [`README.md`](README.md) — команды, env, статус API, pipeline-график.

---

## 1. Общее описание системы

### Аналогия

Система работает как **умный конвейер на складе**:

1. Сначала привозят **коробку с наклейкой** (GraphQL — быстро, весь каталог).
2. Кладовщик **ставит коробку на полку** (import в БД).
3. Проверяют **список «что должно быть»** и убирают лишнее с витрины (finalize).
4. Отдельный работник **открывает каждую коробку** и сверяет цену/остаток (DOM step4).
   Сначала смотрит через «щель в двери» (HTTP), если не видно — открывает дверь (браузер).

### Что делает новая версия (step4)

| Было (боль) | Стало (step4) |
|-------------|----------------|
| На каждый товар — тяжёлый браузер | **Один браузер на чанк** (~36 SKU) |
| HTTP без cookies → 429 | **Cookie sync**: Playwright → HTTP |
| Запросы подряд без пауз | **Burst pacing**: пачка → пауза |
| Всё через `page.goto` | **HTTP-first**: браузер только если HTML плохой |

### Три воркера + scraper

```text
make parser (scraper)     →  ставит задачи в очереди
worker-import             →  пишет базу в PostgreSQL
worker-finalize           →  снимает пропавшие товары
worker-dom-1 / worker-dom-2 →  цены, stock, детали PDP (общая очередь catalog_dom)
worker-translation        →  description_ru, не блокирует catalog_dom
```

Целевая схема **1+1 A**: две lane, по одному worker, один TP-аккаунт, разные IP.
Очередь `catalog_dom` общая. HTTP-first, Playwright fallback, adaptive 429.

`make parser` **не ждёт** окончания DOM — DOM идёт **в фоне**.

---

## 2. Высокоуровневая схема (flow)

### Весь каталог (один прогон)

```text
                    ┌─────────────────────────────────────┐
                    │  make parser  (src/scraper/app.py)   │
                    └─────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           │
   Collection DOM              GraphQL pages                      │
   (listing, availability)     (все товары каталога)             │
          │                           │                           │
          │                           ├──► catalog_import (RQ)    │
          │                           └──► catalog_dom (RQ)         │
          │                                       │               │
          │                           worker-import               │
          │                           (база в БД)                 │
          │                                       │               │
          │                           import очередь пуста?       │
          │                                       ▼               │
          │                           свежий GraphQL snapshot     │
          │                                       │               │
          │                           catalog_finalize (RQ)       │
          │                           (снять пропавших)           │
          │                                       │               │
          └───────────────────────────────────────┴──► parser OK │
                                                          DOM ещё │
                                                          крутится│
                                                                  ▼
                                        worker-dom-1 + worker-dom-2 (step4, 1+1)
```

### Один товар внутри DOM-чанка

```text
RQ-задача (чанк ~36 товаров)
        │
        ▼
 open_dom_chunk()  ──►  DomSession (браузер + HTTP client + pacing)
        │
        ▼
 Для каждого SKU в чанке:
        │
        ├─► before_product()     pacing / warming / throttle
        │
        ├─► PRIMARY: HTTP-first?
        │       ├─ да, HTML OK  ──► parse_product_page_details()
        │       └─ нет          ──► browser: new_page() → goto → HTML
        │
        ├─► parse_product_page_details()
        │
        ├─► FULL: validate_full_dom_details()
        │       ├─ invalid_*  ──► failed, attempts+1, без apply/import
        │       └─ ok         ──► apply_dom_details()
        │
        ├─► LITE: apply_dom_details(update_details=False)  только price/stock
        │
        └─► after_product()      burst pause + micro-sleep
        │
        ▼
 Recovery pass (только failed, http_first=false, browser)
        │
        ▼
 ProductImportService → PostgreSQL
        │
        ▼
 session.close()  (закрыть HTTP + browser)
```

---

## 3. Главные принципы новой архитектуры

### Primary → Recovery

**Primary** — быстрый путь: HTTP-first, потом browser при необходимости.
**Recovery** — второй проход **только для упавших** SKU в том же чанке, **без HTTP-first**
(сразу браузер). Код: `catalog_import_job.run_catalog_dom_enrichment_chunk`.

Почему так: HTTP даёт 95%+ скорости; recovery добирает «тяжёлые» страницы без
торможения всего чанка.

### Браузер не перезапускается на каждый товар

На весь DOM-чанк один `BrowserManager` → один `BrowserContext` (`DomSession`).
Закрытие — только в `session.close()` после чанка.

**Почему:** запуск Chromium дорогой; cookies и «доверие» сайта копятся в сессии.

### `new_page()` вместо полного recreate browser

Browser path: `ctx.new_page()` → `goto` → `page.close()`.
Контекст и cookies **живут**.

**Почему:** новая вкладка легче, чем новый браузер; cookies общие.

### Когда создаётся `new_context()`

В основном DOM-потоке — **один context на чанк**.
`new_context_for_slot()` в `browser_manager.py` — для прокси-слотов / login, не для
обычного step4-чанка.

### Poisoned session («отравленная сессия»)

Сессия, где cookies устарели, Cloudflare «запомнил» бота, или после серии 429 HTTP
отдаёт challenge/login вместо товара.

**Признаки:** `reject_http_html_reason` → `login`, `captcha`, `challenge`; много
failed в recovery.

**Лечение:** `make login-lane LANE=1` и `LANE=2` → свой `storage_state.json` на lane, стабильный egress.

### Playwright — source of truth для cookies

`ScraperHttpClient.sync_cookies_from_context()` **читает** cookies из Playwright.
После успешного browser fetch — `sync_cookies_after_browser()` (Playwright → HTTP).

**Почему HTTP sync односторонний:** браузер проходит JS/challenge; aiohttp — нет.
Копируем результат браузера в HTTP, не наоборот.

### Зачем fallback-стратегии

Сайт **нестабилен**: то отдаёт полный HTML по HTTP, то challenge, то пустую страницу.
Цепочка HTTP → browser → recovery — это **страховки**, не «лишний код».

---

## 4. Структура папок

> В проекте **нет** отдельных папок `adapters/`, `pipeline/`, `recovery/`.
> Роли распределены по файлам ниже — «если хочешь поменять X, иди сюда».

```text
src/scraper/
├── app.py                 # Оркестратор: GraphQL, очереди, finalize
├── dom_session.py         # Сессия на DOM-чанк (step4)
├── pacing.py              # Burst pauses, warming, challenge throttle
├── telemetry.py           # Метрики dom_chunk в логах
├── config/
│   ├── settings.py        # SCRAPER_* из src/scraper/.env
│   └── config.py          # ParseConfig (headless, storage_state)
├── sources/               # «Откуда взять список товаров»
│   ├── graphql_catalog.py # Shopify GraphQL → dict товара
│   ├── collection_dom.py  # Listing: видимые variant ID (availability)
│   └── graphql_categories.py
├── enrichment/            # «Обогатить один товар с PDP»
│   ├── product_dom.py     # HTTP-first, browser, recovery batch
│   └── http_validate.py   # Достаточен ли HTML для парсинга
├── parsers/               # «Разобрать HTML, без браузера»
│   ├── product_pdp.py     # script#product-data, цены, variants
│   └── pdp_support.py
├── infrastructure/
│   ├── browser_manager.py # Playwright launch, proxy, login
│   ├── http_client.py     # aiohttp + cookies из Playwright
│   ├── popup_handler.py
│   ├── session/           # availability / make login
│   ├── session-1/         # catalog_dom lane 1
│   └── session-2/         # catalog_dom lane 2
├── snapshots/
│   └── catalog_snapshot.py # Снимок для finalize missing
└── commands/
    └── login.py           # Ручной логин, сохранить сессию

src/jobs/
├── catalog_import_job.py  # RQ: import chunk, DOM chunk, deactivate
├── queue.py               # Очереди + GET status для API
└── dom_watchdog.py        # Переочередить зависшие DOM jobs

src/services/
└── product_import_service.py  # Нормализация категорий, upsert в БД
```

### Карта «хочу поменять → файл»

| Хочу поменять… | Файл |
|----------------|------|
| URL коллекций, флаги step4 | `src/scraper/.env`, `config/settings.py` |
| Как тянем каталог (GraphQL) | `sources/graphql_catalog.py` |
| Селекторы/разбор PDP HTML | `parsers/product_pdp.py` |
| Когда HTTP «достаточен» | `enrichment/http_validate.py` |
| Порядок HTTP → browser | `enrichment/product_dom.py` |
| Паузы anti-429 | `pacing.py`, `dom_session.py` |
| Один браузер на чанк | `dom_session.py` |
| Cookies HTTP ↔ Playwright | `infrastructure/http_client.py` |
| Постановка задач в RQ | `app.py` |
| Запись в БД, категории | `services/product_import_service.py` |
| Снятие пропавших товаров | `app.py` + `catalog_import_job.run_catalog_deactivate_missing` |
| Статус очередей (API) | `jobs/queue.py`, `schemas/scraper_status.py` |

---

## 5. Как проходит парсинг одного товара (step-by-step)

Пример: товар уже попал в DOM-чанк как `dict` с `product_url`.

| Шаг | Что происходит | Где в коде |
|-----|----------------|------------|
| 1 | RQ вызывает `run_catalog_dom_enrichment_chunk` | `catalog_import_job.py` |
| 2 | `open_dom_chunk()` — браузер + HTTP client + pacing | `dom_session.py` |
| 3 | `before_product()` — warming, throttle, burst | `dom_session.py`, `pacing.py` |
| 4 | **Primary fetch:** HTTP-first с cookies | `product_dom.fetch_product_html` |
| 5 | HTML проверяется: product-data, member price, final price | `http_validate.py` |
| 6 | Если HTTP плохой → `new_page()`, `goto`, ждём `#product-data` | `product_dom.py` |
| 7 | После browser success → cookies Playwright → HTTP | `http_client.sync_cookies_from_context` |
| 8 | `parse_product_page_details(html)` — чистый парсинг | `parsers/product_pdp.py` |
| 9 | `apply_dom_details` — цена EUR, stock по variants | `product_dom.py` |
| 10 | `after_product()` — burst pause, sleep 1.2–2.5s | `dom_session.py` |
| 11 | Если primary failed → **recovery** pass, `http_first=false` | `catalog_import_job.py` |
| 12 | Успешные → `ProductImportService.import_products` | `product_import_service.py` |
| 13 | Нормализация sport_type, category_l2/l3, gender | `normalize_*` в import service |
| 14 | Commit в PostgreSQL, `dom_attempts` / `dom_last_error` | `Product` model |
| 15 | `session.close()` — конец чанка | `dom_session.py` |

**GraphQL-этап (до DOM)** для того же товара: быстрее, даёт карточку на витрине
с `stock=0` до прихода DOM.

---

## 6. Recovery logic

### Два уровня recovery

**A. Внутри чанка (основной)** — после primary pass:

```text
failed_products → enrich_products_with_dom(http_first=False) → тот же ctx
```

**B. Внутри одного SKU** — retry rounds (`SCRAPER_ENRICH_RETRY_ROUNDS`):

неудачные товары повторяются до N раз с `workers=1`.

**C. Backoff при challenge/429** — `_needs_dom_backoff` → sleep 30–90s.

### Что происходит, если что-то сломалось

| Проблема | Поведение системы |
|----------|-------------------|
| **Timeout** HTTP/browser | SKU в `failed_products`, retry round или recovery pass |
| **Cloudflare / captcha** | `reject_http_html_reason` → browser path; telemetry `challenge` |
| **Broken DOM** (нет `#product-data`) | browser reload/retry; затем failed |
| **Bad proxy** | Ошибки fetch; при recovery proxy pool в `browser_manager` |
| **Empty page** | `no_product_data` → browser |
| **Login page** | `login` в http_validate → browser + проверить `storage_state` |
| **429 rate limit** | backoff sleep; burst pacing снижает частоту |

Step4 цель: на primary **почти всё через HTTP**, recovery **≈ 0** в норме.

---

## 7. Как добавить новый сайт (supplier)

Сейчас код **заточен под Shopify Storefront + supplier-demo PDP**.
Новый сайт = новый «адаптер», не один флаг.

### Пошагово

1. **Источник каталога**
   - API/GraphQL → новый модуль в `sources/` (по образцу `graphql_catalog.py`).
   - Нет API → парсинг listing/sitemap.

2. **Формат товара**
   - Выход — тот же `dict`, что ждёт `ProductImportService` (`product_url`, `item_id`, variants…).

3. **PDP: селекторы и парсер**
   - `parsers/product_pdp.py` — разбор HTML/JSON страницы товара.
   - `http_validate.py` — какие маркеры считать «HTML достаточным».

4. **Нормализация**
   - `product_import_service.py`: `normalize_sport_type`, `normalize_category_levels`, размеры.
   - Витрина: `src/utils/labels.py`, taxonomy.

5. **Category mapping**
   - Сырые категории поставщика → `category_l1/l2/l3`, `sport_type`.

6. **Тесты**
   - Фикстура HTML PDP → unit test парсера.
   - Smoke: 1 чанк, `SCRAPER_MAX_PRODUCTS=5`.

7. **Env**
   - `SCRAPER_BASE_URL`, `SCRAPER_COLLECTION_URLS`, токены API в `src/scraper/.env`.

8. **step4**
   - Обычно те же флаги, если сайт похож на защищённый Shopify.
   - Иначе — подобрать pacing и http_validate под новую разметку.

---

## 8. Как НЕ сломать систему (anti-patterns)

| ❌ Не делать | Почему плохо |
|-------------|--------------|
| Закрывать browser/session после каждого SKU | Потеря cookies, 429, ×5 медленнее |
| Full browser recreate внутри чанка | То же |
| Две lane на один session JSON / один IP | Гонка cookies, бан |
| Ломать cookie sync (HTTP без Playwright cookies) | HTTP-first перестаёт работать |
| Sequential heavy requests без pacing | 429 на весь чанк |
| Обходить recovery pipeline (патчить «всегда success») | Тихие нули в stock/цене |
| Менять прокси/IP посреди прогона | Poisoned session |
| Finalize до полного GraphQL (`MAX_PRODUCTS` обрезан) | Снимете живые товары с витрины |
| GraphQL import перетирает DOM-цену | Уже защищено — не снимать защиту в import service |

---

## 9. Debugging guide

### Куда смотреть логи

| Что | Команда / место |
|-----|-----------------|
| DOM step4, `dom_chunk` JSON | `make worker-dom-logs` |
| Import | `docker compose logs -f worker-import` |
| Finalize | `docker compose logs -f worker-finalize` |
| Scraper orchestrator | `docker compose logs scraper` (при `make parser`) |
| Очереди RQ | `make queue-status` |
| Статус API (admin) | `GET /api/products/catalog/import/status` |

### Типичные симптомы

| Симптом | Вероятная причина | Действие |
|---------|-------------------|----------|
| Товар не обновился | DOM ещё в очереди или failed | API `phase=dom`, `make worker-dom-logs`, `dom_last_error` в БД |
| Stock пропал / 0 | DOM failed или variant не сматчился | Логи SKU, recovery pass |
| Пустой DOM / no_product_data | Challenge или сессия | `make login-lane LANE=1|2`, свой egress |
| Вырос retry / recovery | HTTP перестал проходить | cookie sync, сессия, 429 |
| Cloudflare банит | Слишком быстро / два воркера | step4 pacing, один IP |
| Finalize снял лишнее | Неполный snapshot | `SCRAPER_MAX_PRODUCTS=0`, `FINALIZE_MISSING` |
| Статус «завис» | RQ job stale | `make dom-watchdog-apply` |
| `pacing_overhead_pct > 20%` | Норма для step4 | См. README, смотреть `http_success_ratio` |

### Полезные поля в `dom_chunk` (лог)

- `http_success_ratio` — должен быть ≈ 1.0
- `recovery_ratio` — ≈ 0
- `pacing_overhead_pct` — 35–45% нормально (паузы anti-429)
- `challenge_ratio_last_window` — должно быть низко

### Поля в БД (`products`)

- `dom_attempts`, `dom_last_error`, `dom_last_attempt_at`
- `catalog_synced_at`, `deactivated_at` (finalize)

---

## 10. Карта зависимостей

```text
src/scraper/.env
       │
       ▼
config/settings.py ─────────────────────────────────────────┐
       │                                                    │
       ▼                                                    │
app.py ──► sources/graphql_catalog.py                       │
       │         │                                          │
       │         ▼                                          │
       ├──► sources/collection_dom.py                       │
       │                                                    │
       ├──► jobs/queue.py ──► RQ redis                      │
       │         │                                          │
       │         ├── catalog_import ──► catalog_import_job  │
       │         ├── catalog_dom ─────► catalog_import_job  │
       │         └── catalog_finalize ► catalog_import_job  │
       │                          │                         │
       │                          ▼                         │
       │                   dom_session.py                   │
       │                          │                         │
       │            ┌─────────────┼─────────────┐           │
       │            ▼             ▼             ▼           │
       │     browser_manager  http_client   pacing.py       │
       │            │             │             │           │
       │            └─────────────┼─────────────┘           │
       │                          ▼                         │
       │                   product_dom.py                   │
       │                          │                         │
       │                          ▼                         │
       │                   parsers/product_pdp.py           │
       │                          │                         │
       │                          ▼                         │
       └── snapshots/catalog_snapshot.py                    │
                                  │                         │
                                  ▼                         │
                    product_import_service.py ◄─────────────┘
                                  │
                                  ▼
                           PostgreSQL (products)
```

**Правило:** меняя парсер HTML → трогай `parsers/`.
Меняя способ загрузки страницы → `enrichment/product_dom.py` + `http_validate.py`.
Меняя очереди/порядок finalize → `app.py`.
Меняя витрину/категории → `product_import_service.py`.

---

## 11. Краткий TL;DR (1–2 минуты)

**Что это:** конвейер обновления каталога с supplier-demo. Быстро тянем список товаров
(GraphQL), пишем в БД, снимаем исчезнувших (finalize), в фоне уточняем **цену и stock**
через PDP (step4).

**Step4:** один браузер на чанк, cookies из Playwright в HTTP, сначала HTTP-запрос
страницы товара, браузер только если HTML плохой, паузы между пачками — чтобы не
получить 429.

**Порядок:** Collection DOM → GraphQL → import **и** dom в очередь → ждём import →
finalize → parser готов, DOM ещё работает.

**Смотреть прогресс:** `GET /api/products/catalog/import/status` (`phase`, `dom_queue_*`)
и `make worker-dom-logs`.

**Не ломать:** одна session на lane, не убивать сессию на каждый товар, не отключать cookie
sync, не finalize на обрезанном каталоге.

**Сломалось:** `make worker-dom-logs` → `dom_chunk` → при зависании `dom-watchdog-apply` →
при login/challenge `make login`.

Полный pipeline-график и env: [`README.md`](README.md).
