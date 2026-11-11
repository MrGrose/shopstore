# Откуда брать логику (не визуал)

В этой ветке **не правим** `src/templates/site/*` и **не копируем** CSS/HTML старой витрины.

| Новый код | Старый источник логики |
|-----------|----------------------|
| `src/lib/storefront/api.ts` | `src/static/site/js/storefront-api.js`, `tg-login.js` |
| `src/lib/storefront/cart.ts` | `storefront-cart-core.js`, `storefront-cart.js` |
| `src/lib/storefront/catalog.ts` | `storefront-catalog-grid.js`, API `/products` |
| `src/lib/storefront/auth.ts` | `tg-login.js` |
| `pages/CheckoutPage.tsx` (будущее) | `checkout.js` |
| `pages/OrdersPage.tsx` (будущее) | `storefront-orders.js` |
| Варианты / остатки | `storefront-variants.js`, `buyer-stock-badge.js` |

Бэкенд и контракты API: `src/api/routers/*` — меняем только если не хватает эндпоинта.
