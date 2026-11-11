from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product
from src.schemas.catalog_import import (
    ProductImport,
    ProductImportFeature,
    ProductImportImage,
    ProductImportVariant,
)
from src.services.catalog.categories.pipeline import catalog_fields_changed
from src.services.catalog.importing.helpers import (
    hash_text,
    sync_product_cover_from_gallery,
)
from src.services.catalog.importing.product_complete import (
    has_valid_product_description,
)
from src.services.catalog.importing.resolution import resolve_catalog_for_product
from src.services.catalog.supplier.snapshot import apply_supplier_snapshot_to_product
from src.utils.datetime_fmt import utc_now_naive
from src.utils.html_text import strip_html_plaintext
from src.utils.images import discard_product_local_media, is_local_product_media_url
from src.utils.translate_descriptions import stored_description_ru_is_valid


@dataclass
class UpdateFlags:
    has_changes: bool
    refresh_media: bool
    features_changed: bool
    write_categories: bool


# Считает флаги изменений для update path (graphql / dom).
def compute_update_flags(
    existing: Product,
    sale_price: Decimal,
    regular_price: Decimal,
    stock: int,
    incoming_variant_signature,
    current_variant_signature,
    incoming_gallery_layout,
    current_gallery_layout,
    incoming_gallery_url_signature,
    current_gallery_url_signature,
    incoming_feature_signature,
    current_feature_signature,
    incoming_description: str | None,
    is_dom_full: bool,
    is_dom_import: bool,
    incoming_has_features: bool,
    catalog: dict[str, str | None],
    category_l2: str | None,
    sport_type: str | None,
    trade_group: str | None,
    write_categories: bool,
    is_graphql_base: bool = False,
) -> UpdateFlags:
    features_changed = (
        current_feature_signature != incoming_feature_signature
        if (is_dom_full and (incoming_has_features or is_dom_import))
        else False
    )
    catalog_changed = (
        catalog_fields_changed(
            existing,
            catalog=catalog,
            category_l2=category_l2,
            sport_type=sport_type,
            trade_group=trade_group,
        )
        if write_categories
        else False
    )
    track_gallery = is_dom_full or is_graphql_base
    gallery_layout_changed = (
        current_gallery_layout != incoming_gallery_layout if track_gallery else False
    )
    gallery_urls_changed = (
        current_gallery_url_signature != incoming_gallery_url_signature
        if track_gallery
        else False
    )
    gallery_changed = gallery_layout_changed or gallery_urls_changed
    incoming_desc_hash = hash_text(strip_html_plaintext(incoming_description))
    hash_changed = (
        incoming_desc_hash is not None
        and incoming_desc_hash != existing.description_hash
    )
    description_changed = incoming_desc_hash is not None and (
        (is_dom_import and hash_changed)
        or (is_dom_full and not stored_description_ru_is_valid(existing.description_ru))
    )
    has_changes = any(
        [
            Decimal(existing.supplier_price_eur or 0) != sale_price,
            Decimal(existing.regular_price or 0) != regular_price,
            int(existing.stock or 0) != stock,
            current_variant_signature != incoming_variant_signature,
            gallery_changed,
            description_changed,
            features_changed,
            catalog_changed,
        ]
    )
    return UpdateFlags(
        has_changes=has_changes,
        refresh_media=gallery_changed,
        features_changed=features_changed,
        write_categories=write_categories,
    )


# GraphQL skip path: snapshot изменился — пересчитать категории.
def bump_changes_if_snapshot_updated(
    existing: Product,
    product,
    import_payload: dict[str, Any],
    catalog: dict[str, str | None],
    write_categories: bool,
) -> tuple[bool, dict[str, str | None], bool, str | None, str | None, str | None]:
    if not apply_supplier_snapshot_to_product(existing, import_payload):
        return False, catalog, write_categories, None, None, None
    catalog, write_categories = resolve_catalog_for_product(
        product=product,
        existing=existing,
        import_payload=import_payload,
        is_graphql_base=True,
        is_dom_import=False,
        snapshot_target=existing,
    )
    category_l2 = catalog["category_l2"]
    sport_type = catalog["sport_type"]
    trade_group = catalog["trade_group"]
    if write_categories and catalog_fields_changed(
        existing,
        catalog=catalog,
        category_l2=category_l2,
        sport_type=sport_type,
        trade_group=trade_group,
    ):
        return True, catalog, write_categories, category_l2, sport_type, trade_group
    return False, catalog, write_categories, category_l2, sport_type, trade_group


# Применяет update к существующему SKU (graphql skeleton или dom enrichment).
async def apply_existing_product_update(
    existing: Product,
    product: ProductImport,
    flags: UpdateFlags,
    sale_price: Decimal,
    regular_price: Decimal,
    stock: int,
    external_id: str | None,
    image_url: str | None,
    product_url: str,
    catalog: dict[str, str | None],
    category_l2: str | None,
    sport_type: str | None,
    trade_group: str | None,
    pricing_category_key: str | None,
    eur_rate: Decimal,
    is_graphql_base: bool,
    is_dom_full: bool,
    is_dom_import: bool,
    translation_map: dict[str, str],
    variants_payload: list[ProductImportVariant],
    selected_variant: ProductImportVariant | None,
    media_gallery: list[ProductImportImage],
    features: list[ProductImportFeature],
    download_images: bool,
    downloaded_cache: dict[str, str | None],
    session: AsyncSession,
    apply_description,
    attach_images,
    attach_features,
    upsert_variants,
    apply_pricing,
) -> None:
    existing.title = product.title
    existing.brand = product.brand
    if is_dom_import:
        apply_description(existing, product.description, translation_map)
    existing.supplier_price_eur = sale_price
    existing.regular_price = regular_price
    existing.product_url = product_url
    old_image_url = existing.image_url
    old_gallery_urls = [image.url for image in existing.images]
    if (
        not flags.refresh_media
        and image_url
        and is_local_product_media_url(image_url)
        and (not existing.image_url or image_url != existing.image_url)
    ):
        existing.image_url = image_url
    existing.stock = stock
    if not is_graphql_base:
        existing.is_active = product.is_active
    existing.external_id = external_id
    if flags.write_categories:
        existing.category_l1 = catalog["category_l1"]
        existing.category_l2 = category_l2
        existing.category_l3 = catalog["category_l3"]
        existing.sport_type = sport_type
        existing.trade_group = trade_group
        if catalog["gender"] is not None:
            existing.gender = catalog["gender"]
        existing.pricing_category_key = pricing_category_key
    existing.eur_rate_snapshot = eur_rate
    existing.catalog_synced_at = utc_now_naive()
    if (
        is_dom_full
        and is_dom_import
        and has_valid_product_description(existing.description_raw)
    ):
        existing.dom_full_at = utc_now_naive()
    if flags.refresh_media:
        discard_product_local_media(
            image_url=old_image_url,
            gallery_urls=old_gallery_urls,
        )
        existing.images.clear()
        existing.image_url = None
        await attach_images(existing, media_gallery, download_images, downloaded_cache)
        sync_product_cover_from_gallery(
            existing,
            downloaded_cache=downloaded_cache if download_images else None,
        )
        if not existing.image_url and is_local_product_media_url(image_url):
            existing.image_url = image_url
    if flags.features_changed:
        existing.features.clear()
        attach_features(existing, features)
    with session.no_autoflush:
        upsert_variants(existing, variants_payload, selected_variant)
    await session.flush()
    await apply_pricing(existing)
