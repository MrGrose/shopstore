import argparse
import asyncio
import logging

from sqlalchemy import func, select

from src.jobs.queue import enqueue_translation_product
from src.models.product import Product
from src.repositories.session import async_session_maker
from src.scraper.config.settings import load_settings
from src.utils.html_text import is_manufacturer_imprint_description
from src.utils.translate_descriptions import (
    HUGE_RAW_CHARS,
    is_google_error_page,
    is_invalid_translation_response,
    stored_description_ru_is_valid,
    translate_description_html,
    translation_backfill_skip_reason,
)

logger = logging.getLogger(__name__)


# Пауза между чанками Google Translate из scraper settings.
def _sleep_range() -> tuple[float, float]:
    settings = load_settings()
    lo = float(settings.translate_sleep_min)
    hi = float(settings.translate_sleep_max)
    if hi < lo:
        hi = lo
    return lo, hi


# Сканирует каталог и ставит translation jobs, без вызова LibreTranslate.
async def dispatch_pending_translations(
    dry_run: bool,
    force: bool,
    limit: int | None,
) -> dict[str, object]:
    processed = 0
    enqueued = 0
    selected = 0
    errors = 0
    skip_counts: dict[str, int] = {}
    selected_ids: list[int] = []
    inactive_error_ids: list[int] = []
    total_rows = 0

    async with async_session_maker() as session:
        stmt = select(Product).where(
            func.length(func.trim(func.coalesce(Product.description_raw, ""))) > 0
        )
        result = await session.scalars(stmt)
        products: list[Product] = list(result.all())
        total_rows = len(products)

        for product in products:
            raw = (product.description_raw or "").strip()
            ru = product.description_ru
            product_id = int(product.id) if product.id is not None else 0
            if (
                not product.is_active
                and is_google_error_page(ru)
                and not is_manufacturer_imprint_description(raw)
                and len(raw) < HUGE_RAW_CHARS
            ):
                inactive_error_ids.append(product_id)
            reason = translation_backfill_skip_reason(
                raw,
                ru,
                bool(product.is_active),
                force=force,
                raw_hash=product.description_hash,
                translated_hash=product.description_translated_hash,
            )
            if reason is not None:
                skip_counts[reason] = skip_counts.get(reason, 0) + 1
                processed += 1
                continue
            if limit is not None and len(selected_ids) >= limit:
                skip_counts["limit"] = skip_counts.get("limit", 0) + 1
                processed += 1
                continue
            selected += 1
            selected_ids.append(product_id)
            if dry_run:
                processed += 1
                continue
            try:
                enqueue_translation_product(
                    product_id, raw_hash=product.description_hash
                )
            except Exception as exc:
                logger.exception(
                    "Не удалось поставить перевод id=%s: %s",
                    product_id,
                    exc,
                )
                errors += 1
                processed += 1
                continue
            enqueued += 1
            processed += 1
        await session.rollback()

    return {
        "processed": processed,
        "translated": enqueued,
        "enqueued": enqueued,
        "selected": selected,
        "errors": errors,
        "skipped": skip_counts,
        "selected_ids": selected_ids[:40],
        "selected_ids_total": len(selected_ids),
        "inactive_error_ids": inactive_error_ids,
        "total_rows": total_rows,
    }


# Переводит один товар; повторно проверяет актуальность перед Google/LT.
async def _translate_product(product_id: int) -> dict[str, object]:
    async with async_session_maker() as session:
        product = await session.get(Product, product_id)
        if product is None:
            return {"status": "missing", "product_id": product_id}
        raw = (product.description_raw or "").strip()
        reason = translation_backfill_skip_reason(
            raw,
            product.description_ru,
            bool(product.is_active),
            raw_hash=product.description_hash,
            translated_hash=product.description_translated_hash,
        )
        if reason is not None:
            return {
                "status": "skip",
                "reason": reason,
                "product_id": product_id,
            }
        sleep_range = _sleep_range()
        try:
            new_desc = await asyncio.to_thread(
                translate_description_html,
                raw,
                "auto",
                sleep_range,
            )
        except Exception as exc:
            logger.warning(
                "Перевод id=%s не удался: %s",
                product_id,
                exc,
            )
            new_desc = None
        if new_desc:
            new_desc = new_desc.strip()
        if new_desc and not is_invalid_translation_response(raw, new_desc):
            product.description_ru = new_desc
            product.description_translated_hash = product.description_hash
            session.add(product)
            await session.commit()
            return {
                "status": "translated",
                "product_id": product_id,
                "chars": len(new_desc),
            }
        if stored_description_ru_is_valid(product.description_ru):
            await session.rollback()
            logger.info(
                "id=%s перевод не удался, сохранён прежний RU",
                product_id,
            )
            return {
                "status": "failed_preserved",
                "product_id": product_id,
            }
        product.description_ru = None
        product.description_translated_hash = None
        session.add(product)
        await session.commit()
        logger.info("id=%s перевод не удался, description_ru сброшен", product_id)
        return {"status": "failed_cleared", "product_id": product_id}


# RQ entrypoint: перевод одного SKU в очереди translation.
def run_translate_product(product_id: int) -> dict[str, object]:
    return asyncio.run(_translate_product(int(product_id)))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Очередь перевода описаний.")
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Найти кандидатов и поставить translation jobs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только список кандидатов, без enqueue.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ставить даже валидный актуальный RU.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Максимум jobs за прогон.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    if not args.dispatch:
        raise SystemExit("Укажите --dispatch")
    stats = asyncio.run(
        dispatch_pending_translations(
            dry_run=args.dry_run,
            force=args.force,
            limit=args.limit,
        )
    )
    logger.info("Готово: %s", stats)


if __name__ == "__main__":
    main()
