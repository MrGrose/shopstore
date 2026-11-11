from typing import Any

from src.models.product import Product
from src.schemas.catalog_import import ProductImportGtm, ProductImportPdpMeta
from src.scraper.sources.graphql_categories import resolve_graphql_categories
from src.services.catalog.categories.taxonomy import infer_category_l3
from src.services.catalog.text import text_or_none
from src.utils.labels import infer_gender_from_title, normalize_gender


# Категории из persisted supplier_snapshot_json (единственный primary input).
def resolve_catalog_fields_from_supplier_snapshot(
    snapshot: dict[str, Any] | None,
    title: str | None = None,
    gender: str | None = None,
) -> dict[str, str | None]:
    if not snapshot:
        return _empty_catalog_fields()
    import_sport = text_or_none(snapshot.get("import_collection_sport")) or ""
    product_type = text_or_none(snapshot.get("product_type")) or ""
    collections = [
        (row["handle"], row["title"])
        for row in (snapshot.get("collections") or [])
        if isinstance(row, dict) and row.get("handle")
    ]
    supplier_taxonomy = snapshot.get("supplier_taxonomy")
    if not isinstance(supplier_taxonomy, dict):
        supplier_taxonomy = None
    categories = resolve_graphql_categories(
        sport_type=import_sport,
        product_type=product_type,
        collections=collections,
        title=title or "",
        supplier_taxonomy=supplier_taxonomy,
    )
    category_l1 = categories.get("category_l1") or import_sport or None
    category_l2 = categories.get("category_l2") or product_type or None
    category_l3 = categories.get("category_l3")
    sport_type = categories.get("sport_type")
    trade_group = categories.get("trade_group") or product_type or None
    if not category_l3 and category_l2:
        category_l3 = infer_category_l3(category_l2=category_l2, title=title)
    resolved_gender = normalize_gender(gender) or infer_gender_from_title(title)
    return {
        "category_l1": category_l1,
        "category_l2": category_l2,
        "category_l3": category_l3,
        "sport_type": sport_type,
        "trade_group": trade_group,
        "gender": resolved_gender,
    }


# Legacy: gtm + pdp_meta (manual import / transition).
def resolve_catalog_fields_from_import(
    gtm: ProductImportGtm | dict[str, Any] | None,
    pdp_meta: ProductImportPdpMeta | dict[str, Any] | None,
    title: str | None = None,
) -> dict[str, str | None]:
    from src.services.catalog.categories.sport_policy import resolve_storefront_sport
    from src.utils.labels import normalize_category_levels, normalize_sport_type

    if isinstance(gtm, dict):
        gtm_model = ProductImportGtm.model_validate(gtm)
    else:
        gtm_model = gtm or ProductImportGtm()
    if isinstance(pdp_meta, dict):
        pdp_model = ProductImportPdpMeta.model_validate(pdp_meta)
    else:
        pdp_model = pdp_meta or ProductImportPdpMeta()
    if pdp_model.has_supplier_block and pdp_model.supplier is not None:
        gender = text_or_none(pdp_model.gender) or text_or_none(gtm_model.item_gender)
        return resolve_catalog_fields_from_supplier_snapshot(
            pdp_model.supplier.model_dump(),
            title=title,
            gender=gender,
        )

    category_l1 = text_or_none(pdp_model.item_category) or text_or_none(
        gtm_model.item_category
    )
    category_l3 = text_or_none(pdp_model.item_category3) or text_or_none(
        gtm_model.item_category3
    )
    sport_raw = text_or_none(pdp_model.sport_type) or gtm_model.item_sport_type
    import_sport = normalize_sport_type(sport_raw) or text_or_none(sport_raw)
    category_l2, category_l3 = normalize_category_levels(
        text_or_none(pdp_model.item_category2)
        or text_or_none(gtm_model.item_category2),
        category_l3,
        sport_type=import_sport,
    )
    if not category_l3 and category_l2:
        category_l3 = infer_category_l3(category_l2=category_l2, title=title)
    sport_type = resolve_storefront_sport(
        import_collection_sport=import_sport,
        merchandise_l1=category_l1,
        merchandise_l2=category_l2,
        product_type=text_or_none(pdp_model.trade_group)
        or text_or_none(gtm_model.item_trade_group),
        title=title,
        supplier_taxonomy_sport=text_or_none(pdp_model.sport_type)
        or gtm_model.item_sport_type,
    )
    trade_group = text_or_none(pdp_model.trade_group) or text_or_none(
        gtm_model.item_trade_group
    )
    return {
        "category_l1": category_l1,
        "category_l2": category_l2,
        "category_l3": category_l3,
        "sport_type": sport_type,
        "trade_group": trade_group,
        "gender": normalize_gender(
            text_or_none(pdp_model.gender) or text_or_none(gtm_model.item_gender)
        ),
    }


# Пишет category_* на Product из projection (single writer backfill).
def apply_catalog_fields_to_product(
    product: Product,
    catalog: dict[str, str | None],
) -> bool:
    changed = catalog_fields_changed(
        product,
        catalog=catalog,
        category_l2=catalog.get("category_l2"),
        sport_type=catalog.get("sport_type"),
        trade_group=catalog.get("trade_group"),
    )
    if not changed:
        return False
    product.category_l1 = catalog.get("category_l1")
    product.category_l2 = catalog.get("category_l2")
    product.category_l3 = catalog.get("category_l3")
    product.sport_type = catalog.get("sport_type")
    product.trade_group = catalog.get("trade_group")
    return True


# Текущие category_* из ORM (DOM path read-only).
def catalog_fields_from_product(product: Product) -> dict[str, str | None]:
    return {
        "category_l1": product.category_l1,
        "category_l2": product.category_l2,
        "category_l3": product.category_l3,
        "sport_type": product.sport_type,
        "trade_group": product.trade_group,
        "gender": product.gender,
    }


# Проверяет, изменились ли поля категорий у товара.
def catalog_fields_changed(
    existing: Product,
    catalog: dict[str, str | None],
    category_l2: str | None,
    sport_type: str | None,
    trade_group: str | None,
) -> bool:
    return any(
        [
            (existing.category_l1 or None) != catalog.get("category_l1"),
            (existing.category_l2 or None) != category_l2,
            (existing.category_l3 or None) != catalog.get("category_l3"),
            (existing.sport_type or None) != sport_type,
            (existing.trade_group or None) != trade_group,
        ]
    )


# Пустой набор category_* для fallback pipeline.
def _empty_catalog_fields() -> dict[str, str | None]:
    return {
        "category_l1": None,
        "category_l2": None,
        "category_l3": None,
        "sport_type": None,
        "trade_group": None,
        "gender": None,
    }
