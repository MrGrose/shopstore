from typing import Any

from src.models.product import Product
from src.schemas.catalog_import import ProductImport
from src.services.catalog.categories.pipeline import (
    catalog_fields_changed,
    catalog_fields_from_product,
    resolve_catalog_fields_from_import,
    resolve_catalog_fields_from_supplier_snapshot,
)
from src.services.catalog.supplier.snapshot import (
    apply_supplier_snapshot_to_product,
    build_supplier_snapshot,
    merge_supplier_taxonomy_from_pdp_meta,
)


# Возвращает category fields и флаг «нужно писать category_* в БД».
def resolve_catalog_for_product(
    product: ProductImport,
    existing: Product | None,
    import_payload: dict[str, Any],
    is_graphql_base: bool,
    is_dom_import: bool,
    is_dom_full: bool = False,
    snapshot_target: Product | None = None,
) -> tuple[dict[str, str | None], bool]:
    if is_dom_import and existing is not None:
        if not is_dom_full:
            return catalog_fields_from_product(existing), False
        if not merge_supplier_taxonomy_from_pdp_meta(existing, product.pdp_meta):
            return catalog_fields_from_product(existing), False
        snapshot = existing.supplier_snapshot_json
        if not snapshot:
            return catalog_fields_from_product(existing), False
        catalog = resolve_catalog_fields_from_supplier_snapshot(
            snapshot,
            title=product.title,
            gender=product.pdp_meta.gender,
        )
        write = catalog_fields_changed(
            existing,
            catalog,
            catalog.get("category_l2"),
            catalog.get("sport_type"),
            catalog.get("trade_group"),
        )
        return catalog, write

    if is_graphql_base:
        if snapshot_target is not None:
            apply_supplier_snapshot_to_product(snapshot_target, import_payload)
        snapshot = None
        if snapshot_target is not None:
            snapshot = snapshot_target.supplier_snapshot_json
        if not snapshot:
            snapshot = build_supplier_snapshot(import_payload)
        if not snapshot:
            if existing is not None:
                return catalog_fields_from_product(existing), False
            return {}, False
        catalog = resolve_catalog_fields_from_supplier_snapshot(
            snapshot,
            title=product.title,
            gender=product.pdp_meta.gender,
        )
        if existing is None:
            return catalog, True
        write = catalog_fields_changed(
            existing,
            catalog,
            catalog.get("category_l2"),
            catalog.get("sport_type"),
            catalog.get("trade_group"),
        )
        return catalog, write

    return (
        resolve_catalog_fields_from_import(
            product.gtm,
            product.pdp_meta,
            title=product.title,
        ),
        True,
    )
