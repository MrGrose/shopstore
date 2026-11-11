from src.models.product import Product, ProductVariant


# Доступный остаток одного варианта с учётом резерва.
def variant_available_qty(
    inventory: int,
    reserved: int,
    *,
    available: bool = True,
) -> int:
    if not available:
        return 0
    return max(0, int(inventory or 0) - int(reserved or 0))


# Остаток для карточки витрины: max по вариантам или product.stock − резерв.
def product_display_available_stock(
    product: Product,
    product_reserved: int,
    variants: list[ProductVariant],
    variant_reserved: dict[int, int],
) -> int:
    if variants:
        return max(
            (
                variant_available_qty(
                    int(v.inventory_quantity or 0),
                    variant_reserved.get(v.id, 0),
                    available=bool(v.available),
                )
                for v in variants
            ),
            default=0,
        )
    return max(0, int(product.stock or 0) - int(product_reserved or 0))


# Первый вариант с доступным остатком (как при добавлении в корзину без variant_id).
def pick_buyable_variant_id(
    variants: list[ProductVariant],
    variant_reserved: dict[int, int],
    preferred_id: int | None = None,
) -> int | None:
    if not variants:
        return None

    def available(v: ProductVariant) -> int:
        return variant_available_qty(
            int(v.inventory_quantity or 0),
            variant_reserved.get(v.id, 0),
            available=bool(v.available),
        )

    if preferred_id is not None:
        match = next((v for v in variants if v.id == preferred_id), None)
        if match and available(match) > 0:
            return preferred_id

    for variant in variants:
        if available(variant) > 0:
            return variant.id
    return None
