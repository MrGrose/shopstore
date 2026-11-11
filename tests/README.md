# Tests

Частичное покрытие (~30 тестов).

```bash
make test           # все pytest (нужен --extra web)
make test-unit      # tests/unit/ (пока пусто)
make api-smoke      # smoke без pytest
```

Существующие файлы в корне `tests/` — переносить в `tests/unit/` по мере рефактора.

Приоритет новых тестов: `cart_service`, `order_service`, `pricing_service`, `promo_service`.
