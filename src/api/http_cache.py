import hashlib

from src.models.product import Product


# Собирает ETag для публичной карточки товара.
def build_product_etag(product: Product, mapping_release_id: int | None) -> str:
    synced = product.catalog_synced_at
    synced_part = synced.isoformat() if synced else ""
    release = mapping_release_id if mapping_release_id is not None else 0
    payload = (
        f"{product.id}:{release}:"
        f"{product.sale_price}:{product.regular_price}:"
        f"{product.stock}:{product.catalog_in_stock}:"
        f"{int(product.is_active)}:{synced_part}"
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f'W/"p{product.id}-{digest}"'
