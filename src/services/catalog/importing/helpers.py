import asyncio
import hashlib
import logging
import random
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.models.product import Product, ProductFeature, ProductImage, ProductVariant
from src.schemas.catalog_import import (
    ProductImportFeature,
    ProductImportImage,
    ProductImportVariant,
    coerce_import_price,
)
from src.scraper.config.settings import load_settings
from src.utils.html_text import strip_html_plaintext
from src.utils.images import (
    is_local_product_media_url,
    is_malformed_product_image_url,
    local_product_media_exists,
    save_image_from_url,
)
from src.utils.translate_descriptions import (
    is_invalid_translation_response,
    is_mostly_russian,
    stored_description_ru_is_valid,
    translate_description_html,
)
from src.utils.variant_sort import apply_variant_option_sort_keys

logger = logging.getLogger(__name__)


# Приводит цену из строковых и числовых значений к Decimal.
def parse_price(value: Any) -> Decimal:
    return coerce_import_price(value)


# Вычисляет складской остаток по данным вариантов.
def resolve_stock(
    fallback_stock: int,
    variants: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
) -> int:
    if variants:
        return max(0, sum(v.inventory_quantity for v in variants))
    if selected_variant is not None:
        return max(0, selected_variant.inventory_quantity)
    return max(0, int(fallback_stock or 0))


# Стабильный dedupe-ключ для одного import batch; None — не объединять.
def gallery_asset_dedupe_key(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if is_local_product_media_url(raw):
        return f"local:{raw}"
    if not raw.startswith("http"):
        return None
    canonical = canonical_supplier_gallery_url(raw)
    if not canonical:
        return None
    return f"supplier:{canonical}"


# Добавляет галерею изображений товара.
async def attach_images(
    product: Product,
    gallery: list[ProductImportImage],
    download_images: bool,
    downloaded_cache: dict[str, str | None],
) -> None:
    seen_dedupe_keys: set[str] = set()
    position = 0
    for item in gallery:
        if not item.url.strip():
            continue
        if is_malformed_product_image_url(item.url):
            logger.warning(
                "Skip malformed gallery URL for product %s: %s",
                product.external_id,
                item.url,
            )
            continue
        dedupe_key = gallery_asset_dedupe_key(item.url)
        if dedupe_key is not None:
            if dedupe_key in seen_dedupe_keys:
                continue
            seen_dedupe_keys.add(dedupe_key)
        source_url = item.url.strip() if item.url.startswith("http") else None
        managed_url = await resolve_image_url(
            item.url, download_images, downloaded_cache
        )
        if is_local_product_media_url(item.url):
            managed_url = managed_url or item.url.strip()
        if source_url and is_malformed_product_image_url(source_url):
            continue
        if managed_url and is_malformed_product_image_url(managed_url):
            managed_url = None
        if not source_url and not managed_url:
            continue
        product.images.append(
            ProductImage(
                url=managed_url,
                source_url=source_url,
                alt=item.alt,
                position=position,
            )
        )
        position += 1


# Выставляет products.image_url только на managed /media.
def sync_product_cover_from_gallery(
    product: Product,
    downloaded_cache: dict[str, str | None] | None = None,
) -> None:
    _ = downloaded_cache
    if not product.images:
        product.image_url = None
        return
    images = sorted(product.images, key=lambda row: row.position or 0)
    for image in images:
        url = str(image.url or "").strip()
        if is_local_product_media_url(url):
            product.image_url = url
            return
    product.image_url = None


# Скачивает HTTP URL в Storage и возвращает managed /media или None.
def _find_cached_download(
    source_url: str,
    downloaded_cache: dict[str, str | None],
) -> tuple[bool, str | None]:
    if source_url in downloaded_cache:
        return True, downloaded_cache[source_url]
    target = gallery_asset_dedupe_key(source_url)
    if target is None:
        return False, None
    for cached_url, managed in downloaded_cache.items():
        if gallery_asset_dedupe_key(cached_url) == target:
            downloaded_cache[source_url] = managed
            return True, managed
    return False, None


async def resolve_image_url(
    source_url: str | None,
    download_images: bool,
    downloaded_cache: dict[str, str | None],
) -> str | None:
    if not source_url or not download_images or not source_url.startswith("http"):
        return None
    found, managed = _find_cached_download(source_url, downloaded_cache)
    if found:
        return managed
    local_url = await save_image_from_url(source_url)
    downloaded_cache[source_url] = local_url
    return local_url


# Добавляет характеристики товара.
def attach_features(product: Product, features: list[ProductImportFeature]) -> None:
    for idx, item in enumerate(features):
        name = item.feature_name
        if not name:
            continue
        product.features.append(
            ProductFeature(
                name=name,
                value=item.feature_value,
                icon_url=item.icon_url,
                position=idx,
            )
        )


# Раскладка галереи (alt + позиция), без URL.
def build_gallery_layout_signature(
    gallery: list[ProductImportImage],
) -> tuple[tuple[str | None, int], ...]:
    signature: list[tuple[str | None, int]] = []
    pos = 0
    for item in gallery:
        if not item.url.strip():
            continue
        alt = item.alt.strip() if item.alt is not None else None
        signature.append((alt, pos))
        pos += 1
    return tuple(signature)


# Сигнатура раскладки галереи из ORM.
def current_gallery_layout_signature(
    product: Product,
) -> tuple[tuple[str | None, int], ...]:
    return tuple(
        (image.alt, int(image.position or 0))
        for image in sorted(product.images, key=lambda image: image.position or 0)
        if (image.url or image.source_url)
    )


# Нормализует URL галереи для сравнения (path без query).
def normalize_gallery_image_url(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")).lower()


# Канонический supplier asset key (files/...) для shopify и supplier-demo proxy.
def canonical_supplier_gallery_url(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw or is_local_product_media_url(raw):
        return ""
    path = urlsplit(raw).path.lower()
    marker = "/files/"
    if marker in path:
        return path[path.rindex(marker) + 1 :]
    return path.lstrip("/")


# Supplier URL signature из GraphQL/DOM payload.
def build_supplier_gallery_url_signature(
    gallery: list[ProductImportImage],
) -> tuple[str, ...]:
    urls: list[str] = []
    for item in gallery:
        canonical = canonical_supplier_gallery_url(item.url)
        if canonical:
            urls.append(canonical)
    return tuple(urls)


# Supplier URL signature из ORM; local /media сопоставляется с incoming по position.
def current_supplier_gallery_url_signature(
    product: Product,
    incoming_gallery: list[ProductImportImage],
) -> tuple[str, ...]:
    db_by_position = {
        int(image.position or 0): image
        for image in product.images
        if (image.url or image.source_url)
    }
    signatures: list[str] = []
    position = 0
    for item in incoming_gallery:
        if not item.url.strip():
            continue
        incoming_canonical = canonical_supplier_gallery_url(item.url)
        if not incoming_canonical:
            continue
        db_image = db_by_position.get(position)
        position += 1
        if db_image is None:
            signatures.append("")
            continue
        stored_url = str(db_image.url or "").strip()
        stored_source = str(db_image.source_url or "").strip()
        if stored_source:
            signatures.append(
                canonical_supplier_gallery_url(stored_source) or incoming_canonical
            )
            continue
        if is_local_product_media_url(stored_url):
            if local_product_media_exists(stored_url):
                signatures.append(incoming_canonical)
            else:
                signatures.append(f"missing-local:{Path(stored_url).name}")
            continue
        db_canonical = canonical_supplier_gallery_url(stored_url)
        signatures.append(db_canonical or incoming_canonical)
    return tuple(signatures)


# Сигнатура URL галереи из payload.
def build_gallery_url_signature(
    gallery: list[ProductImportImage],
) -> tuple[str, ...]:
    urls: list[str] = []
    for item in gallery:
        normalized = normalize_gallery_image_url(item.url)
        if normalized:
            urls.append(normalized)
    return tuple(urls)


# Сигнатура URL галереи из ORM.
def current_gallery_url_signature(product: Product) -> tuple[str, ...]:
    return tuple(
        normalize_gallery_image_url(image.source_url or image.url)
        for image in sorted(product.images, key=lambda image: image.position or 0)
        if (image.url or image.source_url)
    )


# Сигнатура характеристик из payload.
def build_feature_signature(
    features: list[ProductImportFeature],
) -> tuple[tuple[str | int | None, ...], ...]:
    signature: list[tuple[str | int | None, ...]] = []
    for idx, item in enumerate(features):
        name = item.feature_name
        if not name:
            continue
        signature.append((name, item.feature_value, item.icon_url, idx))
    return tuple(signature)


# Сигнатура характеристик из ORM.
def current_feature_signature(
    product: Product,
) -> tuple[tuple[str | int | None, ...], ...]:
    return tuple(
        (feature.name, feature.value, feature.icon_url, int(feature.position or 0))
        for feature in sorted(
            product.features, key=lambda feature: feature.position or 0
        )
        if feature.name
    )


# Собирает ключ варианта из payload.
def variant_payload_key(item: ProductImportVariant) -> tuple[str, str, str, str]:
    return (
        str(item.id or ""),
        str(item.sku or ""),
        str(item.option1 or ""),
        str(item.option2 or ""),
    )


# Собирает ключ варианта из ORM.
def variant_model_key(variant: ProductVariant) -> tuple[str, str, str, str]:
    return (
        str(variant.variant_external_id or ""),
        str(variant.sku or ""),
        str(variant.option1 or ""),
        str(variant.option2 or ""),
    )


# Добавляет варианты, объединяя product_data и selected_variant.
def attach_variants(
    product: Product,
    variants_payload: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
) -> None:
    by_id: dict[str, ProductImportVariant] = {}
    for idx, item in enumerate(variants_payload):
        key = str(item.id) if item.id is not None else f"__idx_{idx}"
        by_id[key] = item

    if selected_variant is not None:
        match_key = (
            str(selected_variant.id) if selected_variant.id is not None else None
        )
        if match_key and match_key in by_id:
            base = by_id[match_key]
            by_id[match_key] = base.model_copy(
                update=selected_variant.model_dump(exclude_unset=True)
            )
        else:
            by_id["__selected__"] = selected_variant

    for item in by_id.values():
        variant = ProductVariant(
            variant_external_id=(str(item.id) if item.id is not None else None),
            sku=item.sku,
            option1=item.option1,
            option2=item.option2,
            option3=item.option3,
            price=item.price,
            compare_at_price=item.compare_at_price,
            inventory_quantity=item.inventory_quantity,
            available=item.available,
        )
        apply_variant_option_sort_keys(variant, product.category_l2)
        product.variants.append(variant)


# Обновляет/добавляет варианты без удаления (FK заказов).
def upsert_variants(
    product: Product,
    variants_payload: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
) -> None:
    incoming_probe = Product(
        title="",
        brand="",
        sale_price=Decimal("0"),
        supplier_price_eur=Decimal("0"),
        regular_price=Decimal("0"),
        stock=0,
        product_url="probe://variant-upsert",
        is_active=True,
    )
    attach_variants(incoming_probe, variants_payload, selected_variant)

    def _variant_external_id(variant: ProductVariant) -> str:
        return str(variant.variant_external_id or "")

    # Fallback only when variant has no supplier external id.
    def _variant_fallback_key(variant: ProductVariant) -> tuple[str, str, str, str]:
        return (
            _variant_external_id(variant),
            str(variant.sku or ""),
            str(variant.option1 or ""),
            str(variant.option2 or ""),
        )

    existing_by_external_id: dict[str, ProductVariant] = {}
    existing_by_fallback: dict[tuple[str, str, str, str], ProductVariant] = {}
    for variant in product.variants:
        external_id = _variant_external_id(variant)
        if external_id:
            existing_by_external_id[external_id] = variant
            continue
        existing_by_fallback[_variant_fallback_key(variant)] = variant

    incoming_external_ids: set[str] = set()
    incoming_fallback_keys: set[tuple[str, str, str, str]] = set()
    for incoming in incoming_probe.variants:
        external_id = _variant_external_id(incoming)
        if external_id:
            incoming_external_ids.add(external_id)
            target = existing_by_external_id.get(external_id)
        else:
            fallback_key = _variant_fallback_key(incoming)
            incoming_fallback_keys.add(fallback_key)
            target = existing_by_fallback.get(fallback_key)
        if target is None:
            variant = ProductVariant(
                variant_external_id=incoming.variant_external_id,
                sku=incoming.sku,
                option1=incoming.option1,
                option2=incoming.option2,
                option3=incoming.option3,
                price=incoming.price,
                compare_at_price=incoming.compare_at_price,
                inventory_quantity=incoming.inventory_quantity,
                available=incoming.available,
            )
            apply_variant_option_sort_keys(variant, product.category_l2)
            product.variants.append(variant)
            continue
        target.sku = incoming.sku
        target.option1 = incoming.option1
        target.option2 = incoming.option2
        target.option3 = incoming.option3
        target.price = incoming.price
        target.compare_at_price = incoming.compare_at_price
        target.inventory_quantity = incoming.inventory_quantity
        target.available = incoming.available
        apply_variant_option_sort_keys(target, product.category_l2)

    for existing_variant in product.variants:
        external_id = _variant_external_id(existing_variant)
        if external_id:
            if external_id in incoming_external_ids:
                continue
        elif _variant_fallback_key(existing_variant) in incoming_fallback_keys:
            continue
        existing_variant.available = False
        existing_variant.inventory_quantity = 0


# GraphQL available=false бьёт stale true; qty=0 GraphQL не затирает DOM qty при true.
def _merge_graphql_variant_with_existing(
    incoming: ProductImportVariant,
    existing: ProductVariant,
) -> ProductImportVariant:
    prices = {
        "price": existing.price or Decimal("0"),
        "compare_at_price": existing.compare_at_price or Decimal("0"),
    }
    if not incoming.available:
        return incoming.model_copy(
            update={
                "available": False,
                "inventory_quantity": 0,
                **prices,
            }
        )
    return incoming.model_copy(
        update={
            "available": True,
            "inventory_quantity": int(existing.inventory_quantity or 0),
            **prices,
        }
    )


# Сохраняет stock/price существующих вариантов при graphql update.
def preserve_existing_variant_state(
    variants_payload: list[ProductImportVariant],
    product: Product,
) -> list[ProductImportVariant]:
    existing_map = {variant_model_key(v): v for v in product.variants}
    preserved: list[ProductImportVariant] = []
    for item in variants_payload:
        existing = existing_map.get(variant_payload_key(item))
        if existing is None:
            preserved.append(item)
            continue
        preserved.append(_merge_graphql_variant_with_existing(item, existing))
    return preserved


# Сохраняет stock/price выбранного варианта при graphql update.
def preserve_selected_variant_state(
    selected_variant: ProductImportVariant | None,
    product: Product,
) -> ProductImportVariant | None:
    if selected_variant is None:
        return None
    existing_map = {variant_model_key(v): v for v in product.variants}
    existing = existing_map.get(variant_payload_key(selected_variant))
    if existing is None:
        return selected_variant
    return _merge_graphql_variant_with_existing(selected_variant, existing)


# Сигнатура вариантов из payload.
def build_variant_signature(
    variants_payload: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
) -> tuple[tuple[str | int | Decimal | bool | None, ...], ...]:
    probe = Product(
        title="",
        brand="",
        sale_price=Decimal("0"),
        supplier_price_eur=Decimal("0"),
        regular_price=Decimal("0"),
        stock=0,
        product_url="probe://variant-signature",
        is_active=True,
    )
    attach_variants(probe, variants_payload, selected_variant)
    return tuple(
        sorted(
            (
                variant.variant_external_id,
                variant.sku,
                variant.option1,
                variant.option2,
                variant.option3,
                Decimal(variant.price or 0),
                Decimal(variant.compare_at_price or 0),
                int(variant.inventory_quantity or 0),
                bool(variant.available),
            )
            for variant in probe.variants
        )
    )


# Сигнатура вариантов из ORM.
def current_variant_signature(
    product: Product,
) -> tuple[tuple[str | int | Decimal | bool | None, ...], ...]:
    return tuple(
        sorted(
            (
                variant.variant_external_id,
                variant.sku,
                variant.option1,
                variant.option2,
                variant.option3,
                Decimal(variant.price or 0),
                Decimal(variant.compare_at_price or 0),
                int(variant.inventory_quantity or 0),
                bool(variant.available),
            )
            for variant in product.variants
        )
    )


# Возвращает sha256 от текста; для пустого — None.
def hash_text(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Пауза между запросами Google Translate из scraper settings.
def _translate_sleep_range() -> tuple[float, float]:
    settings = load_settings()
    lo = float(settings.translate_sleep_min)
    hi = float(settings.translate_sleep_max)
    if hi < lo:
        hi = lo
    return lo, hi


# Параллелизм catalog translation; минимум 1.
def _translate_parallelism() -> int:
    return max(1, int(load_settings().translate_parallelism))


# True, если перевод можно класть в map (не error/echo/empty).
def _usable_translation(source: str, translated: str | None) -> bool:
    if not translated:
        return False
    return not is_invalid_translation_response(source, translated)


# Параллельно переводит уникальные описания чанка.
async def translate_chunk_descriptions(
    raw_descriptions: list[str | None],
) -> dict[str, str]:
    candidates: set[str] = set()
    for raw in raw_descriptions:
        text = (raw or "").strip()
        if text and not is_mostly_russian(text):
            candidates.add(text)
    if not candidates:
        return {}

    sleep_range = _translate_sleep_range()
    semaphore = asyncio.Semaphore(_translate_parallelism())

    # Переводит один уникальный текст описания.
    async def _translate_one(text: str) -> tuple[str, str | None]:
        async with semaphore:
            try:
                translated = await asyncio.to_thread(
                    translate_description_html,
                    text,
                    "auto",
                    sleep_range,
                )
            except Exception as exc:
                logger.warning("Перевод описания не удался: %s", exc)
                translated = None
            await asyncio.sleep(random.uniform(*sleep_range))
            if _usable_translation(text, translated):
                return text, translated
            return text, None

    results = await asyncio.gather(*[_translate_one(t) for t in candidates])
    return {raw: translated for raw, translated in results if translated}


# Достаёт переведённое описание из словаря.
def lookup_translation(
    raw_text: str | None, translation_map: dict[str, str]
) -> str | None:
    if raw_text is None or not raw_text.strip():
        return None
    return translation_map.get(raw_text.strip())


# Пишет raw/hash; RU только при валидном переводе, иначе сохраняет прежний валидный RU.
def apply_description(
    existing: Product,
    raw_text: str | None,
    translation_map: dict[str, str],
) -> None:
    cleaned = strip_html_plaintext(raw_text)
    new_hash = hash_text(cleaned)
    same_hash = existing.description_hash == new_hash
    if same_hash and stored_description_ru_is_valid(existing.description_ru):
        return
    translated = lookup_translation(cleaned, translation_map)
    if translated:
        translated = strip_html_plaintext(translated)
    if translated and is_invalid_translation_response(cleaned, translated):
        translated = None
    old_hash = existing.description_hash
    existing.description_raw = cleaned
    existing.description_hash = new_hash
    if translated:
        existing.description_ru = translated
        existing.description_translated_hash = new_hash
        return
    if stored_description_ru_is_valid(existing.description_ru):
        if existing.description_translated_hash is None:
            existing.description_translated_hash = old_hash or ""
        return
    existing.description_ru = None
    existing.description_translated_hash = None
