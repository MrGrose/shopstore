from dataclasses import dataclass
from decimal import Decimal

from src.models.product import Product


@dataclass(frozen=True)
class ExpectedStorefrontPrice:
    supplier_price_eur: Decimal
    final_price: Decimal
    category_key: str
    eur_rate: Decimal
    margin_percent: Decimal
    markup_snapshot: Decimal


# Сравнивает Decimal-поле модели с ожидаемым значением.
def _decimal_matches(current: object, expected: Decimal) -> bool:
    if current is None:
        return False
    return Decimal(str(current)) == expected


# Проверяет, нужны ли товару или вариантам pricing-изменения.
def storefront_price_is_current(
    product: Product,
    expected: ExpectedStorefrontPrice,
) -> bool:
    product_matches = (
        _decimal_matches(product.supplier_price_eur, expected.supplier_price_eur)
        and _decimal_matches(product.sale_price, expected.final_price)
        and _decimal_matches(product.regular_price, expected.final_price)
        and product.pricing_category_key == expected.category_key
        and _decimal_matches(product.eur_rate_snapshot, expected.eur_rate)
        and _decimal_matches(product.margin_snapshot_percent, expected.margin_percent)
        and _decimal_matches(product.markup_snapshot, expected.markup_snapshot)
    )
    variants_match = all(
        _decimal_matches(variant.price, expected.final_price)
        and variant.compare_at_price is None
        for variant in product.variants
    )
    return product_matches and variants_match


# Применяет только отличающиеся pricing-поля товара и вариантов.
def apply_expected_storefront_price(
    product: Product,
    expected: ExpectedStorefrontPrice,
) -> bool:
    if storefront_price_is_current(product, expected):
        return False
    product.supplier_price_eur = expected.supplier_price_eur
    product.sale_price = expected.final_price
    product.regular_price = expected.final_price
    product.pricing_category_key = expected.category_key
    product.eur_rate_snapshot = expected.eur_rate
    product.margin_snapshot_percent = expected.margin_percent
    product.markup_snapshot = expected.markup_snapshot
    for variant in product.variants:
        if not _decimal_matches(variant.price, expected.final_price):
            variant.price = expected.final_price
        if variant.compare_at_price is not None:
            variant.compare_at_price = None
    return True
