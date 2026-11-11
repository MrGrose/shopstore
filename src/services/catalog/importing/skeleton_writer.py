from decimal import Decimal
from typing import Any

from src.models.product import Product
from src.schemas.catalog_import import ProductImport, ProductImportVariant
from src.services.catalog.importing.resolution import resolve_catalog_for_product
from src.utils.datetime_fmt import utc_now_naive


# Сохраняет DOM-поля при graphql update существующего SKU.
def preserve_graphql_dom_fields(
    existing: Product,
    product: ProductImport,
    variants_payload: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
    resolve_stock,
    preserve_variants,
    preserve_selected,
) -> tuple[
    Decimal,
    Decimal,
    int,
    list[ProductImportVariant],
    ProductImportVariant | None,
]:
    sale_price = Decimal(existing.supplier_price_eur or 0)
    regular_price = Decimal(existing.regular_price or 0)
    variants_payload = preserve_variants(variants_payload, existing)
    selected_variant = preserve_selected(selected_variant, existing)
    stock = resolve_stock(product.stock, variants_payload, selected_variant)
    return sale_price, regular_price, stock, variants_payload, selected_variant


# Пишет supplier snapshot и category_* на новый graphql SKU.
def apply_graphql_snapshot_to_product(
    db_product: Product,
    product: ProductImport,
    import_payload: dict[str, Any],
) -> dict[str, str | None]:
    catalog, _write = resolve_catalog_for_product(
        product=product,
        existing=None,
        import_payload=import_payload,
        is_graphql_base=True,
        is_dom_import=False,
        snapshot_target=db_product,
    )
    db_product.category_l1 = catalog["category_l1"]
    db_product.category_l2 = catalog["category_l2"]
    db_product.category_l3 = catalog["category_l3"]
    db_product.sport_type = catalog["sport_type"]
    db_product.trade_group = catalog["trade_group"]
    db_product.gender = catalog["gender"]
    return catalog


# Обновляет catalog_synced_at без других изменений (skip path).
def touch_catalog_sync(existing: Product) -> None:
    existing.catalog_synced_at = utc_now_naive()
