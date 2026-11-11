from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.api.routers.product import get_products
from src.core.config import settings
from src.core.order_limits import is_supplier_unit_storefront_allowed
from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.services.catalog.read.scope import CatalogScope


def test_admin_scope_does_not_cap_supplier_unit() -> None:
    admin = CatalogScope.from_admin_mode("in_catalog")
    assert admin.exclude_over_supplier_unit_cap is False
    assert admin.catalog_read_kwargs()["exclude_over_supplier_unit_cap"] is False


def test_catalog_base_filters_include_supplier_unit_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    repo = CrudProduct(session=None, model=Product)
    without_cap = repo._catalog_base_filters()
    with_cap = repo._catalog_base_filters(exclude_over_supplier_unit_cap=True)
    assert len(with_cap) == len(without_cap) + 1
    assert is_supplier_unit_storefront_allowed(Decimal("270.01")) is True
    assert is_supplier_unit_storefront_allowed(Decimal("270.02")) is False


# Кап в SQL сравнивается как Decimal, чтобы 270.01 не потерялся на float.
def test_supplier_unit_cap_filter_binds_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    repo = CrudProduct(session=None, model=Product)
    filters: list = []
    repo._append_supplier_unit_cap_filter(filters, True)
    compiled = str(filters[0].compile(compile_kwargs={"literal_binds": True}))
    assert "270.01" in compiled


@pytest.mark.asyncio
async def test_public_products_admin_keeps_supplier_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /products с admin всё равно режет закупку выше лимита."""
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    captured: dict[str, object] = {}

    async def fake_query(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            top_category=None,
            mapping_release_id=None,
            chip_node_ids=None,
        )

    async def fake_list(_self: object, **kwargs: object) -> tuple[list, None, bool]:
        captured.update(kwargs)
        return [], None, False

    monkeypatch.setattr(
        "src.api.routers.product._resolve_catalog_query",
        fake_query,
    )
    monkeypatch.setattr(
        "src.api.routers.product.CatalogService.get_products_list",
        fake_list,
    )
    await get_products(
        page=1,
        page_size=10,
        brand=None,
        gender=None,
        color=None,
        size=None,
        price_min=None,
        price_max=None,
        sort_price=None,
        q=None,
        top_category=None,
        db=None,  # type: ignore[arg-type]
    )

    assert captured["exclude_over_supplier_unit_cap"] is True
    samples = (
        SimpleNamespace(id=18611, supplier_price_eur=Decimal("294.08")),
        SimpleNamespace(id=2, supplier_price_eur=Decimal("100.00")),
    )
    visible_ids = [
        row.id
        for row in samples
        if not captured["exclude_over_supplier_unit_cap"]
        or is_supplier_unit_storefront_allowed(row.supplier_price_eur)
    ]
    assert visible_ids == [2]

    admin_scope = CatalogScope.from_admin_mode("in_catalog")
    assert admin_scope.exclude_over_supplier_unit_cap is False
    assert admin_scope.catalog_read_kwargs()["exclude_over_supplier_unit_cap"] is False
