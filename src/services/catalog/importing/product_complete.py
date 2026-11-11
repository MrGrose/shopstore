from sqlalchemy import and_, func, not_, or_, select

from src.models.product import Product, ProductFeature, ProductImage
from src.scraper.config.settings import load_settings
from src.utils.html_text import is_manufacturer_imprint_description

HOLD_DOM_LAST_ERRORS: tuple[str, ...] = (
    "invalid_description",
    "invalid_gallery",
    "invalid_pdp",
)


# Есть осмысленное описание (не manufacturer imprint).
def has_valid_product_description(text: str | None) -> bool:
    cleaned = (text or "").strip()
    return bool(cleaned) and not is_manufacturer_imprint_description(cleaned)


# Проверяет, обогащён ли товар DOM (derived state, не persist).
def is_product_complete(product: Product) -> bool:
    if not product.external_id or not product.product_url:
        return False
    if not has_valid_product_description(product.description_raw):
        return False
    if len(product.images or []) < 1:
        return False
    if len(product.features or []) >= 1:
        return True
    return product.dom_full_at is not None


# Лимит DOM-попыток из scraper settings (порог HOLD).
def default_dom_max_attempts() -> int:
    return max(1, load_settings().dom_max_attempts)


# HOLD: exhausted FULL с invalid_description / invalid_gallery / invalid_pdp.
def is_enrichment_hold(product: Product, max_attempts: int) -> bool:
    if int(product.dom_attempts or 0) < max(1, max_attempts):
        return False
    return (product.dom_last_error or "") in HOLD_DOM_LAST_ERRORS


# SQL: enrichment HOLD (не COMPLETE). is_active не трогаем.
def enrichment_hold_sql_criterion(max_attempts: int):
    return and_(
        Product.dom_attempts >= max(1, max_attempts),
        Product.dom_last_error.in_(HOLD_DOM_LAST_ERRORS),
    )


# SQL: непустая строка (зеркало truthy-проверки Python).
def _non_empty_string(column):
    return and_(column.isnot(None), column != "")


# SQL: короткий manufacturer/legal imprint в description_raw.
def _manufacturer_imprint_sql_criterion():
    raw = Product.description_raw
    return and_(
        func.length(func.trim(raw)) < 150,
        or_(
            raw.ilike("%www.%"),
            raw.ilike("%TRADINTER%"),
            raw.ilike("%Nike Retail%"),
            raw.ilike("%Focus International%"),
            raw.ilike("%adidas AG%"),
            raw.ilike("%Spodeco GmbH%"),
            raw.ilike("%Supplier-Demo Europe%"),
        ),
    )


# SQL: валидное описание (не пустое и не manufacturer imprint).
def _valid_description_sql_criterion():
    return and_(
        _non_empty_string(Product.description_raw),
        not_(_manufacturer_imprint_sql_criterion()),
    )


# SQL: imprint после FULL — узкий recovery cohort, не все incomplete.
def recoverable_imprint_sql_criterion():
    has_image = (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id)
        .correlate(Product)
        .exists()
    )
    return and_(
        _manufacturer_imprint_sql_criterion(),
        Product.dom_full_at.isnot(None),
        has_image,
    )


# True, если в gallery есть хотя бы один http(s) URL.
def _gallery_has_http_url(gallery: list | None) -> bool:
    for item in gallery or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        else:
            url = str(item or "").strip()
        if url.startswith(("http://", "https://", "//")):
            return True
    return False


# Код ошибки FULL PDP или None, если description и gallery валидны.
def validate_full_dom_details(details: dict | None) -> str | None:
    payload = details or {}
    description = payload.get("description") or ""
    gallery = payload.get("media_gallery") or []
    desc_ok = has_valid_product_description(str(description))
    gallery_ok = _gallery_has_http_url(gallery if isinstance(gallery, list) else [])
    if not desc_ok and not gallery_ok:
        return "invalid_pdp"
    if not desc_ok:
        return "invalid_description"
    if not gallery_ok:
        return "invalid_gallery"
    return None


# SQL-критерий COMPLETE (зеркало is_product_complete).
def product_complete_sql_criterion():
    has_image = (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id)
        .correlate(Product)
        .exists()
    )
    has_feature = (
        select(ProductFeature.id)
        .where(ProductFeature.product_id == Product.id)
        .correlate(Product)
        .exists()
    )
    return and_(
        _non_empty_string(Product.external_id),
        _non_empty_string(Product.product_url),
        _valid_description_sql_criterion(),
        has_image,
        or_(has_feature, Product.dom_full_at.isnot(None)),
    )


# SQL-критерий INCOMPLETE (отрицание COMPLETE).
def product_incomplete_sql_criterion():
    return not_(product_complete_sql_criterion())
