# scripts/media

Проектные скрипты product media (I1–I8.1). Не личные утилиты.

Запускать из **корня репозитория**. Production этими командами не гонять,
пока отдельно не согласуете cutover.


---

## Назначение

| Скрипт | Что делает | Меняет данные? |
|--------|------------|----------------|
| `migrate_remove_duplicate_previews.py` | Удаляет `_300/_600/_900`, байтово идентичные original | `--apply` удаляет файлы |
| `migrate_product_media_to_s3.py` | Копирует originals local ↔ S3 (size+SHA256). Variants пропускает | `--apply` пишет в S3 или обратно на диск |
| `backfill_product_image_variants.py` | Создаёт missing `_300/_600/_900` через Storage | `--apply` пишет variants |
| `verify_local_vs_s3_product_media.py` | Inventory local vs S3, size+SHA256 | нет |
| `remove_local_product_media.py` | Удаляет local original только при match с S3 | `--apply` удаляет local файлы |

Все, кроме verify, по умолчанию **dry-run**. Без `--apply` ничего не пишут и не удаляют.

DB URL скрипты не меняют. CDN не скачивают. Support/Telegram media не трогают.

---

## Порядок

Если идёте по цепочке с нуля:

1. `migrate_remove_duplicate_previews.py` — убрать copyfile-дубли превью.
2. `migrate_product_media_to_s3.py` — залить originals в S3.
3. `backfill_product_image_variants.py` — дописать `_300/_600/_900`.
4. `verify_local_vs_s3_product_media.py` — сверить local и S3.
5. `remove_local_product_media.py` — убрать verified local copies.

Шаг можно пропустить, если он уже сделан. Verify — перед destructive `--apply` на шаге 5.

Make:

```bash
make media-remove-duplicate-previews
make media-remove-duplicate-previews APPLY=1
make media-backfill-image-variants
make media-backfill-image-variants APPLY=1
make media-verify-local-vs-s3
make media-remove-local-product-media
make media-remove-local-product-media APPLY=1
```

---

## Prerequisites

- Корень репозитория, `uv`, зависимости проекта.
- Для S3-скриптов: поднятый SeaweedFS и `S3_*` в окружении.
- Local originals живут в docker volume `shopstore_media` (`/app/media/products` в api).
  Скрипты, которые читают диск, нужно гонять там, где этот volume виден
  (`docker exec` / bind-mount), не с пустого `media/products` на хосте.

---

## Environment

Из корневого `.env` / `.env.example`:

- `STORAGE_BACKEND` — `local` / `dual` / `s3` (backfill берёт текущий backend)
- `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`
- `MEDIA_ROOT` — для скриптов, которые смотрят локальный диск

Scraper `SCRAPER_IMPORT_DOWNLOAD_IMAGES` эти скрипты не читают.

---

## Production

**Не запускать на production** без отдельной команды. Особенно `--apply` у
remove/backfill/migrate. `STORAGE_BACKEND` на prod пока `local`.

Перед любым `--apply` на сервере: `make prod-backup`.

---

## Примеры

```bash
# 1. дубли превью — отчёт, потом удаление
uv run python scripts/media/migrate_remove_duplicate_previews.py
uv run python scripts/media/migrate_remove_duplicate_previews.py --apply

# 2. originals → S3
uv run python scripts/media/migrate_product_media_to_s3.py
uv run python scripts/media/migrate_product_media_to_s3.py --apply
uv run python scripts/media/migrate_product_media_to_s3.py --reverse --apply

# 3. variants
uv run python scripts/media/backfill_product_image_variants.py
S3_ENDPOINT=http://127.0.0.1:8333 uv run python scripts/media/backfill_product_image_variants.py --apply

# 4–5. сверка и cleanup local
uv run python scripts/media/verify_local_vs_s3_product_media.py
uv run python scripts/media/remove_local_product_media.py
uv run python scripts/media/remove_local_product_media.py --apply
```

`--apply` у remove удаляет local файл только если S3 object есть и size+SHA256
совпадают. Known corrupted originals не удаляются.

Backfill не перезаписывает существующие variants и не удаляет originals.
Стоп после 25 ошибок подряд.
