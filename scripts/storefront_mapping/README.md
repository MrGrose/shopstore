# Storefront mapping v2 — ops-скрипты

CLI для release-scoped mapping: nodes → rules → placements → activate.

Запуск из **корня репозитория**. Окружение задаёт `.env` / `DATABASE_URL` (dev или prod — одни и те же команды).


### Код: где что лежит

| Путь | Роль |
|------|------|
| `src/services/catalog/categories/` | Supplier taxonomy import — **не** storefront navigation |
| `src/services/catalog/display/` | Storefront mapping v2 — seed, resolver, release lifecycle |
| `src/services/catalog/read/` | Public catalog API через placements active release |
| `scripts/storefront_mapping/` | Ops CLI для release pipeline (этот README) |

**Rules:** только из `storefront_ux_blueprint.json`. Seed **не** генерирует rules из текущей taxonomy в БД.

## Простыми словами: кто что делает

**Release** — версия «карты витрины». Пока draft — клиент её не видит. После activate — именно она решает, в каких категориях показывается товар.

| Часть | Что это | Аналогия |
|-------|---------|----------|
| **Blueprint JSON** | Файл в git: дерево категорий + правила «supplier L2/L3 → chip» | Чертёж витрины |
| **Nodes** | Категории в БД: Tennis → Обувь → Кроссовки | Пункты меню на сайте |
| **Rules** | «Если у товара sport=L2=L3 такие-то → положить в chip X» | Таблица соответствий |
| **Placements** | Запись «товар N лежит в chip M» для конкретного release | Куда положили SKU на полку |
| **Resolutions** | Итог resolver: mapped / unmapped / excluded / error | Статус для админки |
| **Active release** | Одна включённая версия — её читает API каталога | Текущая раскладка магазина |

**Скрипты не меняют сами товары** — только mapping-таблицы. Импорт taxonomy (`category_l1/l2/l3`) — отдельный pipeline.

### Кто за что отвечает (скрипт → действие)

| Скрипт | Простыми словами |
|--------|------------------|
| `seed_storefront_mapping.py` | «Разложить чертёж»: создать draft и скопировать nodes + rules из JSON в БД |
| `seed_storefront_catalog_rules.py` | «Пересобрать blueprint» в editable release (`StorefrontMappingSeeder`) |
| `backfill_storefront_placements.py` | «Разложить все товары по полкам»: для каждого SKU применить rules → placements |
| `storefront_mapping_reconciler.py` | «Проверка качества»: сколько unmapped, битая taxonomy, ошибки — только отчёт |
| `verify_storefront_coverage.py` | «Можно ли включать?»: да/нет; если нет — exit 1 |
| `mark_storefront_release_verified.py` | «Поставить галочку verified» — человек/CI согласился с отчётом |
| `shadow_compare_storefront_mapping.py` | «Сходится ли с каталогом?»: count в БД = count через API |
| `activate_storefront_release.py` | «Включить эту версию витрины» — старая уходит в archived |
| `rollback_storefront_release.py` | «Откатиться на старую версию» — клон archived → снова activate |
| `export_storefront_ux_blueprint.py` | «Сохранить из БД в JSON» для правки UX и коммита в git |
| `sync_storefront_node_labels_from_blueprint.py` | «Подтянуть русские названия» в nodes release из JSON в git |

**Ты (ops)** — запускаешь pipeline по порядку, смотришь отчёты, activate + restart API.
**API каталога** — после activate читает placements active release, клиент видит новую витрину.

## Быстрый старт (Makefile)

```bash
make storefront-mapping-seed
make storefront-placements-backfill RELEASE_ID=1
make storefront-mapping-reconcile RELEASE_ID=1
make storefront-coverage-verify RELEASE_ID=1
make storefront-release-verify RELEASE_ID=1
make storefront-mapping-shadow RELEASE_ID=1
make storefront-release-activate RELEASE_ID=1
docker compose restart api
```

Перед activate на prod: `make prod-backup`, gates на prod-copy (`docs/gates/2026-06-21-storefront-mapping-v2/`).

## Типичный pipeline

| Шаг | Make | Script |
|-----|------|--------|
| 1. Seed draft из blueprint | `make storefront-mapping-seed` | `seed_storefront_mapping.py` |
| 2. Backfill placements | `make storefront-placements-backfill RELEASE_ID=N` | `backfill_storefront_placements.py` |
| 3. Reconciler (отчёт) | `make storefront-mapping-reconcile RELEASE_ID=N` | `storefront_mapping_reconciler.py` |
| 4. Gate перед verify | `make storefront-coverage-verify RELEASE_ID=N` | `verify_storefront_coverage.py` |
| 5. Mark verified | `make storefront-release-verify RELEASE_ID=N` | `mark_storefront_release_verified.py` |
| 6. Shadow parity | `make storefront-mapping-shadow RELEASE_ID=N` | `shadow_compare_storefront_mapping.py` |
| 7. Activate | `make storefront-release-activate RELEASE_ID=N` | `activate_storefront_release.py` |
| 8. Restart API | `docker compose restart api` | — |

## Скрипты

### `seed_storefront_mapping.py`

**Простыми словами:** первый шаг — «загрузить чертёж витрины в БД».

Создаёт draft release (если нет) и заливает nodes + rules из `src/services/catalog/display/storefront_ux_blueprint.json`.

```bash
PYTHONPATH=. uv run python scripts/storefront_mapping/seed_storefront_mapping.py
PYTHONPATH=. uv run python scripts/storefront_mapping/seed_storefront_mapping.py --release-id 1
```

### `seed_storefront_catalog_rules.py`

**Простыми словами:** повторно залить nodes + rules из blueprint в editable release (через `StorefrontMappingSeeder`).

Вызывает `StorefrontMappingSeeder.seed_release` — тот же seed, что и greenfield, с проверкой editable release.

```bash
make storefront-catalog-rules-seed RELEASE_ID=1
```

### `backfill_storefront_placements.py`

**Простыми словами:** «прогнать все товары через правила» и записать, куда каждый попал.

Прогоняет resolver по catalogized товарам → placements + resolutions. Draft → `backfilled`.

```bash
make storefront-placements-backfill RELEASE_ID=1
# точечный recompute:
PYTHONPATH=. uv run python scripts/storefront_mapping/backfill_storefront_placements.py \
  --release-id 1 --product-ids 100,101,102
```

### `storefront_mapping_reconciler.py`

**Простыми словами:** диагностика — что не замапилось и почему. Ничего не включает.

Coverage-отчёт: `invalid_taxonomy`, `unexpected_unmapped`, `mapping_error`, integrity. Не меняет release status.

```bash
make storefront-mapping-reconcile RELEASE_ID=1
PYTHONPATH=. uv run python scripts/storefront_mapping/storefront_mapping_reconciler.py \
  --release-id 1 --json
```

### `verify_storefront_coverage.py`

**Простыми словами:** автоматический «стоп-кран» перед verify — если есть блокеры, команда падает.

Exit code 1, если reconciler блокирует activation (`blocks_activation`).

```bash
make storefront-coverage-verify RELEASE_ID=1
```

### `mark_storefront_release_verified.py`

**Простыми словами:** «я посмотрел отчёт — можно готовить к включению».

Ставит release статус `verified` (после успешного reconcile + coverage gate).

```bash
make storefront-release-verify RELEASE_ID=1
```

### `activate_storefront_release.py`

**Простыми словами:** переключатель — с этого момента сайт живёт по этому release.

Активирует verified release (advisory lock, предыдущий active → archived). **После — restart API.**

```bash
make storefront-release-activate RELEASE_ID=1
docker compose restart api
```

### `rollback_storefront_release.py`

**Простыми словами:** «вернуть как было» — поднять старую archived-версию как новую active.

Rollback: клон archived release → draft → backfill path → activate.

```bash
make storefront-release-rollback ARCHIVED_ID=1
```

### `shadow_compare_storefront_mapping.py`

**Простыми словами:** двойная проверка — число товаров в mapping совпадает с тем, что отдаёт каталог API.

Parity: counts placements в repo vs `CatalogService` (All + Tennis/Padel/Running). Gate перед prod.

```bash
make storefront-mapping-shadow RELEASE_ID=1
```

### `export_storefront_ux_blueprint.py`

**Простыми словами:** вытащить текущую раскладку из БД в JSON для правки UX и коммита в git.

Экспорт candidate JSON из release в БД. **Только manual UX review** — не коммитить без ревью.

```bash
PYTHONPATH=. uv run python scripts/storefront_mapping/export_storefront_ux_blueprint.py \
  --release-id 2 --out /tmp/candidate.json
```

### `sync_storefront_node_labels_from_blueprint.py`

**Простыми словами:** подтянуть русские подписи категорий в БД из JSON, не пересоздавая release.

One-off: синхронизирует `label_ru` nodes в release из committed blueprint (по `display_key` + structural key).

```bash
PYTHONPATH=. uv run python scripts/storefront_mapping/sync_storefront_node_labels_from_blueprint.py \
  --release-id 2
```

## Dev vs prod

| | Dev | Prod |
|---|-----|------|
| Seed / backfill / reconcile | ✅ основной цикл | ✅ первый rollout |
| Activate / rollback | ✅ | ✅ после backup + gates |
| Export blueprint | ✅ UX review | редко |
| Sync labels | ✅ one-off | ✅ one-off |

Cron не предусмотрен — ручной ops pipeline.

## Переменные Makefile

| Переменная | Для |
|------------|-----|
| `RELEASE_ID` | backfill, reconcile, verify, activate, shadow |
| `ARCHIVED_ID` | rollback |
