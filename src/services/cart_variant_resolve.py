from src.models.product import Product


# Подбирает variant_id при добавлении без явного выбора (как addCatalogProduct).
def resolve_cart_variant_id(product: Product, variant_id: int | None) -> int | None:
    if variant_id is not None:
        return variant_id
    variants = list(product.variants or [])
    if not variants:
        return None
    if len(variants) == 1:
        return variants[0].id
    in_stock = [
        variant
        for variant in variants
        if variant.available and int(variant.inventory_quantity or 0) > 0
    ]
    if in_stock:
        return in_stock[0].id
    return None
