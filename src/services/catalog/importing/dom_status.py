import logging
from collections import Counter
from datetime import UTC, datetime

from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker

logger = logging.getLogger(__name__)


# External id из DOM payload.
def product_external_id(product: dict) -> str | None:
    gtm = product.get("gtm") or {}
    external_id = product.get("item_id") or gtm.get("item_id")
    return str(external_id) if external_id else None


# Ищет Product для записи dom_attempts / dom_last_error.
async def find_product_for_dom_status(session, product: dict) -> Product | None:
    crud = CrudProduct(session=session, model=Product)
    external_id = product_external_id(product)
    if external_id:
        db_product = await crud.get_by_external_id(external_id)
        if db_product is not None:
            return db_product
    product_url = str(product.get("product_url") or "")
    if product_url:
        return await crud.get_by_url(product_url)
    return None


# Считает причины ошибок DOM по чанку.
def dom_error_counts(products: list[dict]) -> dict[str, int]:
    return dict(
        Counter(str(product.get("_dom_last_error") or "error") for product in products)
    )


# Отделяет 404/410 — их не гоняем через recovery proxy.
def split_terminal_dom_failures(
    products: list[dict],
) -> tuple[list[dict], list[dict]]:
    from src.scraper.enrichment.product_dom import is_non_recoverable_dom_error

    recoverable: list[dict] = []
    terminal: list[dict] = []
    for product in products:
        reason = str(product.get("_dom_last_error") or "")
        if is_non_recoverable_dom_error(reason):
            terminal.append(product)
        else:
            recoverable.append(product)
    return recoverable, terminal


# Обновляет dom_attempts / dom_last_error после DOM chunk.
async def record_dom_status(
    success_products: list[dict],
    failed_products: list[dict],
) -> None:
    if not success_products and not failed_products:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    visibility_boundary_ids: list[int] = []
    async with async_session_maker() as session:
        success_rows: list[tuple[Product, dict]] = []
        for product in success_products:
            db_product = await find_product_for_dom_status(session, product)
            if db_product is not None:
                success_rows.append((db_product, product))
        success_rows.sort(key=lambda row: int(row[0].id or 0))

        for db_product, _product in success_rows:
            db_product.dom_attempts = 0
            db_product.dom_last_error = None
            db_product.dom_last_attempt_at = now
            session.add(db_product)
        from src.scraper.enrichment.product_dom import is_non_recoverable_dom_error

        failed_rows: list[tuple[Product, dict]] = []
        for product in failed_products:
            db_product = await find_product_for_dom_status(session, product)
            if db_product is not None:
                failed_rows.append((db_product, product))
        failed_rows.sort(key=lambda row: int(row[0].id or 0))

        for db_product, product in failed_rows:
            dom_error = str(product.get("_dom_last_error") or "error")[:255]
            db_product.dom_last_error = dom_error
            db_product.dom_last_attempt_at = now
            if is_non_recoverable_dom_error(dom_error):
                if db_product.is_active:
                    visibility_boundary_ids.append(int(db_product.id))
                db_product.is_active = False
                db_product.deactivated_at = now
                db_product.dom_attempts = 0
                db_product.dom_last_error = None
            else:
                db_product.dom_attempts = int(db_product.dom_attempts or 0) + 1
            session.add(db_product)
        await session.commit()
    if visibility_boundary_ids:
        from src.services.catalog.read.caches import invalidate_catalog_read_caches

        invalidate_catalog_read_caches(reason="record_dom_status_boundary")
