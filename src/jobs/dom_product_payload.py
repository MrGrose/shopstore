import logging
from decimal import Decimal
from typing import Any

from src.jobs.queue import get_catalog_dom_queue
from src.models.product import Product, ProductVariant
from src.scraper.config.settings import Settings

logger = logging.getLogger(__name__)


# Преобразует Decimal в строку с округлением до 2 знаков после запятой.
def money_str(value: Any) -> str:
    if value in (None, ""):
        return "0"
    return str(Decimal(value).quantize(Decimal("0.01")))


# Собирает dict варианта для DOM enrichment из ORM.
def variant_payload(variant: ProductVariant) -> dict[str, Any]:
    return {
        "id": (
            int(variant.variant_external_id)
            if str(variant.variant_external_id or "").isdigit()
            else variant.variant_external_id
        ),
        "sku": variant.sku,
        "option1": variant.option1,
        "option2": variant.option2,
        "option3": variant.option3,
        "available": bool(variant.available),
        "inventory_quantity": int(variant.inventory_quantity or 0),
        "price": money_str(variant.price),
        "compare_at_price": money_str(variant.compare_at_price),
    }


# Собирает dict товара для DOM enrichment из ORM.
def product_payload(product: Product) -> dict[str, Any]:
    variants = [variant_payload(variant) for variant in product.variants]
    selected_variant = next(
        (variant for variant in variants if variant.get("available")),
        variants[0] if variants else {},
    )
    return {
        "id": product.id,
        "title": product.title,
        "brand": product.brand,
        "description": product.description_raw or product.description or "",
        "sale_price": money_str(product.supplier_price_eur),
        "sale_price_numeric": money_str(product.supplier_price_eur),
        "regular_price": money_str(product.regular_price),
        "product_url": product.product_url or "",
        "image_url": product.image_url or "",
        "item_id": product.external_id,
        "gtm": {
            "item_id": product.external_id,
            "item_name": product.title,
            "item_brand": product.brand,
            "item_category": product.category_l1,
            "item_category2": product.category_l2,
            "item_category3": product.category_l3,
            "item_sport_type": product.sport_type,
            "item_trade_group": product.trade_group,
        },
        "features": [],
        "media_gallery": [],
        "product_data": {"variants": variants},
        "selected_variant": selected_variant,
        "pdp_meta": {},
        "stock": int(product.stock or 0),
        "is_active": bool(product.is_active),
    }


# Ставит чанки товаров в catalog_dom.
def enqueue_dom_product_chunks(
    products: list[dict[str, Any]],
    env: Settings,
    owner_token: str | None = None,
) -> int:
    if not products:
        return 0
    queue = get_catalog_dom_queue()
    chunk_size = max(1, env.import_chunk_size)
    enqueued = 0
    for idx in range(0, len(products), chunk_size):
        chunk = products[idx : idx + chunk_size]  # noqa: E203
        if owner_token is not None:
            job = queue.enqueue(
                env.catalog_dom_enrichment_func,
                chunk,
                env.import_download_images,
                owner_token,
                job_timeout=env.catalog_dom_job_timeout,
            )
        else:
            job = queue.enqueue(
                env.catalog_dom_enrichment_func,
                chunk,
                env.import_download_images,
                job_timeout=env.catalog_dom_job_timeout,
            )
        enqueued += 1
        logger.info(
            "DOM enqueue: размер=%s (id=%s), задач=%s",
            len(chunk),
            job.id,
            enqueued,
        )
    return enqueued
