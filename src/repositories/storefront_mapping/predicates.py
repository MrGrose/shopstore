from src.models.product import Product


# Проверяет, что у товара есть persisted supplier taxonomy для mapping.
def is_catalogized_product(product: Product) -> bool:
    return (
        product.sport_type is not None
        and product.category_l1 is not None
        and product.category_l2 is not None
    )


# SQL-совместимое условие catalogized для query builder.
def catalogized_sql_filters(model: type[Product]) -> list:
    return [
        model.sport_type.is_not(None),
        model.category_l1.is_not(None),
        model.category_l2.is_not(None),
    ]


# Кортеж supplier taxonomy для сравнения изменений.
def product_taxonomy_tuple(product: Product) -> tuple[str | None, ...]:
    return (
        product.sport_type,
        product.category_l1,
        product.category_l2,
        product.category_l3,
    )


# Активный товар с неполной taxonomy.
def is_invalid_taxonomy_product(product: Product) -> bool:
    if not product.is_active:
        return False
    return not is_catalogized_product(product)
