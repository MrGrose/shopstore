from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.models.pricing import MarginRule, PricingSettings
from src.models.product import Product, ProductVariant
from src.services.pricing.calculator import calculate_price_rub
from src.services.pricing.price_check import (
    ExpectedStorefrontPrice,
    apply_expected_storefront_price,
    storefront_price_is_current,
)
from src.services.pricing.rules import resolve_margin_rule
from src.services.pricing.service import PricingService


# Создаёт правило для чистых resolver-тестов.
def _rule(
    sport_type: str,
    slug: str,
    margin: str = "30",
    is_active: bool = True,
) -> MarginRule:
    return MarginRule(
        id=1,
        sport_type=sport_type,
        subcategory_slug=slug,
        margin_percent=Decimal(margin),
        is_active=is_active,
        updated_at=datetime(2026, 7, 14, 12, 0, 0),
    )


# Выбирает активное exact-правило storefront-группы.
def test_margin_rule_resolution_exact() -> None:
    rules = [_rule("Padel", "balls"), _rule("Padel", "__fallback__", "40")]

    resolved = resolve_margin_rule("Padel", "Padel balls", rules)

    assert resolved.rule.subcategory_slug == "balls"
    assert resolved.category_key == "Padel:balls"
    assert resolved.fallback_reason is None


# Выбирает fallback для товара вне точной storefront-группы.
def test_margin_rule_resolution_fallback() -> None:
    rules = [_rule("Padel", "__fallback__", "40")]

    resolved = resolve_margin_rule("Padel", "Unknown", rules)

    assert resolved.rule.subcategory_slug == "__fallback__"
    assert resolved.category_key == "Padel:__fallback__"
    assert resolved.fallback_reason == "no_storefront_group"


# Выбирает fallback, если exact-правило выключено.
def test_margin_rule_resolution_inactive_exact() -> None:
    rules = [
        _rule("Padel", "balls", is_active=False),
        _rule("Padel", "__fallback__", "40"),
    ]

    resolved = resolve_margin_rule("Padel", "Padel balls", rules)

    assert resolved.rule.subcategory_slug == "__fallback__"
    assert resolved.fallback_reason == "exact_rule_inactive"


# Сохраняет результат старой формулы после выноса calculator.
def test_calculate_price_rub_keeps_existing_formula() -> None:
    assert calculate_price_rub(Decimal("10"), Decimal("100"), Decimal("30")) == Decimal(
        "1300.00"
    )


# Обновляет snapshots и все варианты одним ожидаемым значением.
def test_apply_expected_storefront_price_updates_product_and_variants() -> None:
    product = Product(
        supplier_price_eur=Decimal("10"),
        sale_price=Decimal("1000"),
        regular_price=Decimal("1000"),
        pricing_category_key="Padel:accessories",
        eur_rate_snapshot=Decimal("90"),
        margin_snapshot_percent=Decimal("20"),
        markup_snapshot=Decimal("1.2"),
    )
    product.variants = [
        ProductVariant(
            price=Decimal("1000"), compare_at_price=Decimal("1200"), available=False
        ),
        ProductVariant(price=Decimal("1300"), compare_at_price=None, available=True),
    ]
    expected = ExpectedStorefrontPrice(
        supplier_price_eur=Decimal("10"),
        final_price=Decimal("1300"),
        category_key="Padel:balls",
        eur_rate=Decimal("100"),
        margin_percent=Decimal("30"),
        markup_snapshot=Decimal("1.2"),
    )

    changed = apply_expected_storefront_price(product, expected)

    assert changed is True
    assert product.sale_price == Decimal("1300")
    assert product.regular_price == Decimal("1300")
    assert product.pricing_category_key == "Padel:balls"
    assert [variant.price for variant in product.variants] == [
        Decimal("1300"),
        Decimal("1300"),
    ]
    assert all(variant.compare_at_price is None for variant in product.variants)


# Не меняет повторно уже корректный товар и варианты.
def test_apply_expected_storefront_price_is_idempotent() -> None:
    expected = ExpectedStorefrontPrice(
        supplier_price_eur=Decimal("10"),
        final_price=Decimal("1300"),
        category_key="Padel:balls",
        eur_rate=Decimal("100"),
        margin_percent=Decimal("30"),
        markup_snapshot=Decimal("1.2"),
    )
    product = Product(
        supplier_price_eur=expected.supplier_price_eur,
        sale_price=expected.final_price,
        regular_price=expected.final_price,
        pricing_category_key=expected.category_key,
        eur_rate_snapshot=expected.eur_rate,
        margin_snapshot_percent=expected.margin_percent,
        markup_snapshot=expected.markup_snapshot,
    )
    product.variants = [
        ProductVariant(
            price=expected.final_price, compare_at_price=None, available=False
        )
    ]

    assert storefront_price_is_current(product, expected) is True
    assert apply_expected_storefront_price(product, expected) is False


# Service меняет snapshots и варианты вместе, но commit оставляет batch-контроллеру.
def test_verify_loaded_storefront_price_updates_atomically_without_commit() -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    service = PricingService(session)
    rule = _rule("Padel", "balls")
    settings = PricingSettings(
        eur_rate=Decimal("100"),
        markup_multiplier=Decimal("1.2"),
    )
    product = Product(
        supplier_price_eur=Decimal("10"),
        sale_price=Decimal("1000"),
        regular_price=Decimal("1000"),
        sport_type="Padel",
        category_l2="Padel balls",
    )
    product.variants = [
        ProductVariant(price=Decimal("1000"), compare_at_price=Decimal("1200"))
    ]

    changed = service.verify_loaded_storefront_price(
        product,
        settings,
        [rule],
        expected_rule_version=rule.updated_at,
    )

    assert changed is True
    assert product.sale_price == Decimal("1300.00")
    assert product.regular_price == Decimal("1300.00")
    assert product.pricing_category_key == "Padel:balls"
    assert product.eur_rate_snapshot == Decimal("100")
    assert product.margin_snapshot_percent == Decimal("30")
    assert product.markup_snapshot == Decimal("1.2")
    assert product.variants[0].price == Decimal("1300.00")
    assert product.variants[0].compare_at_price is None
    session.add.assert_called_once_with(product)
    session.commit.assert_not_awaited()
