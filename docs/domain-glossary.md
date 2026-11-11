# Доменный словарь (Shopstore)

Один канонический термин на сущность. При новом термине или переименовании в коде/UI — обновить эту страницу.


## Интерфейсы

| Термин | Значение |
|--------|----------|
| REST API | `src/api/` — витрина, Mini App, интеграции |
| Admin HTMX | `src/web/routers/admin_*`, префикс `/internal/admin/*` |
| Storefront SPA | `frontend/` → React-витрина |
| Telegram bot | `src/bot/` |

## Слои

`models` → `repositories` → `services` → `api` / `web` / `bot`. Бизнес-логика только в `services/`.

## Пользователь и доступ

| Термин | Значение |
|--------|----------|
| `UserRole` | `buyer`, `admin`, `referral` |
| JWT / `access_token` | REST: Bearer; витрина и admin: httpOnly cookie |
| `guest_cart_id` | Cookie гостевой корзины; merge при логине |
| `referral_code` | Cookie реферальной привязки |
| Panel login | `ADMIN_PANEL_LOGIN` / `ADMIN_PANEL_PASSWORD` → JWT (отдельно от Telegram-admin) |

Deps: REST — `src/api/deps.py` (`get_current_user`, `require_admin_user`); SSR — `src/web/deps.py` (`require_storefront_user`).

## Каталог

| Термин | Значение |
|--------|----------|
| Product / `product_variants` | Карточка и варианты (размер и т.д.) |
| Catalog import pipeline | Очереди `catalog_import` → `catalog_dom` → `catalog_finalize` |
| `catalog_in_stock`, `available_qty` | Денормализация остатков для витрины |
| DOM enrichment | PDP-парсер — авторитет для member price и stock (см. catalog architecture) |

## Корзина

| Термин | Значение |
|--------|----------|
| `cart_items` | Источник правды в PostgreSQL |
| Владелец корзины | `user_id` **или** `guest_cart_id` (не оба) |
| `CartService` | Расчёты и merge; не в роутере |

## Заказ

| Термин | Значение |
|--------|----------|
| `OrderService` | Создание, статусы, транзакции |
| `OrderStatus` | Базовая цепочка: `created` → `processing` → `delivery` → `completed` / `cancelled` / `failed`; после оплаты — `assembling` (admin actions, см. ADR 2026-07-03) |
| `order_items`, `order_events` | Состав и история |
| `idempotency_key` | Защита от дублей при создании |

## Оплата

| Термин | Значение |
|--------|----------|
| `PaymentService` | Init и статус оплаты (СБП) |
| `order_payment_attempts` | Попытка оплаты = отдельный SBP order и QR |
| SBP | Провайдер СБП (`src/integrations/sbp/`, `SBP_ENABLED`) |
| `provider_status` | Статус у провайдера; успех — `IPS_ACCEPTED` |
| Callback | `POST /payments/sbp/callback` (подпись RSA) |

## Уведомления

| Термин | Значение |
|--------|----------|
| Notification outbox | Асинхронная доставка (`notification_outbox_job`) |
| Admin order created | `AdminNotificationService` — синхронно в Telegram при создании заказа |

## Рефералы и промо

| Термин | Значение |
|--------|----------|
| `ReferralService` | Alias, commission, `referral_earnings` |
| `PromoService` | Промокод при checkout |

## Интеграции

`src/integrations/`: `sbp/`, `telegram_client`, `telegram_gateway/`, `smtp_client` (email OTP).

## Не путать

| Избегать | Канон |
|----------|--------|
| «оплата в полях заказа» как одна попытка | `order_payment_attempts` |
| Роль из клиентского input | `UserRole` из БД после проверенного логина |
| Бизнес-правило в router/schema | `services/` |
