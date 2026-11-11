import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.jobs.dom_observability import log_dom_product_db
from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.schemas.catalog_import import (
    ProductImport,
    ProductImportList,
    ProductImportVariant,
)
from src.services.catalog.display.placement_service import StorefrontPlacementService
from src.services.catalog.display.taxonomy import product_taxonomy_tuple
from src.services.catalog.importing import helpers as imp
from src.services.catalog.importing.catalog_match import (
    canonical_product_url,
    normalize_external_id,
    product_in_catalog_snapshot,
)
from src.services.catalog.importing.enrichment_writer import (
    UpdateFlags,
    apply_existing_product_update,
    bump_changes_if_snapshot_updated,
    compute_update_flags,
)
from src.services.catalog.importing.resolution import resolve_catalog_for_product
from src.services.catalog.importing.skeleton_writer import (
    apply_graphql_snapshot_to_product,
    preserve_graphql_dom_fields,
    touch_catalog_sync,
)
from src.services.catalog.stock.service import CatalogStockService
from src.services.pricing_service import PricingService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.html_text import strip_html_plaintext

logger = logging.getLogger(__name__)


class ProductImportService:
    # Сессия, CRUD и pricing для graphql/DOM import.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.product_crud = CrudProduct(session=session, model=Product)
        self.pricing_service = PricingService(session=session)

    # Импортирует batch товаров; опционально снимает отсутствующие с витрины.
    async def import_products(
        self,
        data: ProductImportList,
        download_images: bool = True,
        deactivate_missing: bool = False,
    ) -> dict[str, int | list[int]]:
        await self.pricing_service.get_margin_rules()
        settings = await self.pricing_service.get_settings()
        created = 0
        updated = 0
        skipped = 0
        deactivated = 0
        touched_ids: set[int] = set()
        taxonomy_changed_ids: set[int] = set()
        new_products: list[Product] = []
        downloaded_cache: dict[str, str | None] = {}
        incoming_external_ids: set[str] = set()
        incoming_urls: set[str] = set()
        incoming_top_categories: set[str] = set()
        translation_map: dict[str, str] = {}
        for product in data.products:
            result = await self._import_one_product(
                product=product,
                download_images=download_images,
                downloaded_cache=downloaded_cache,
                translation_map=translation_map,
                settings=settings,
                incoming_external_ids=incoming_external_ids,
                incoming_urls=incoming_urls,
                incoming_top_categories=incoming_top_categories,
                new_products=new_products,
                touched_ids=touched_ids,
                taxonomy_changed_ids=taxonomy_changed_ids,
            )
            created += result["created"]
            updated += result["updated"]
            skipped += result["skipped"]

        if deactivate_missing:
            deactivated = await self.deactivate_missing_from_snapshot(
                incoming_external_ids=incoming_external_ids,
                incoming_urls=incoming_urls,
                incoming_top_categories=incoming_top_categories,
            )
        await self.session.flush()
        for db_product in new_products:
            if db_product.id is not None:
                touched_ids.add(int(db_product.id))
                taxonomy_changed_ids.add(int(db_product.id))
        placement_svc = StorefrontPlacementService(self.session)
        for product_id in sorted(taxonomy_changed_ids):
            await placement_svc.on_product_taxonomy_changed(product_id)
        await self.session.commit()
        stock_boundary_flipped_ids: list[int] = []
        if touched_ids:
            stock_result = await CatalogStockService(self.session).refresh_products(
                sorted(touched_ids)
            )
            stock_boundary_flipped_ids = stock_result.boundary_flipped_ids
            await self.session.commit()
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "deactivated": deactivated,
            "stock_boundary_flipped_ids": stock_boundary_flipped_ids,
        }

    # Импортирует один товар из payload (create / update / skip).
    async def _import_one_product(
        self,
        product: ProductImport,
        download_images: bool,
        downloaded_cache: dict[str, str | None],
        translation_map: dict[str, str],
        settings,
        incoming_external_ids: set[str],
        incoming_urls: set[str],
        incoming_top_categories: set[str],
        new_products: list[Product],
        touched_ids: set[int],
        taxonomy_changed_ids: set[int],
    ) -> dict[str, int]:
        import_payload = product.model_dump(mode="json")
        selected_variant = product.selected_variant
        variants_payload = list(product.variants)
        is_graphql_base = product.import_source == "graphql_base"
        is_dom_import = product.import_source == "dom"
        is_graphql_skeleton = is_graphql_base
        incoming_has_features = bool(product.features)
        dom_mode = str(product.dom_mode or "").upper()
        is_dom_full = is_dom_import and dom_mode != "LITE"

        sale_price = product.resolved_sale_price
        regular_price = product.regular_price
        external_id = product.item_id or product.gtm.item_id
        stock = imp.resolve_stock(product.stock, variants_payload, selected_variant)

        existing = await self._find_existing(external_id, product.product_url)

        if existing is not None and is_graphql_base:
            sale_price, regular_price, stock, variants_payload, selected_variant = (
                preserve_graphql_dom_fields(
                    existing,
                    product,
                    variants_payload,
                    selected_variant,
                    resolve_stock=imp.resolve_stock,
                    preserve_variants=imp.preserve_existing_variant_state,
                    preserve_selected=imp.preserve_selected_variant_state,
                )
            )
            self._reactivate_catalog_product(existing)

        if existing is not None and is_dom_import:
            self._reactivate_catalog_product(existing)

        if is_graphql_skeleton and existing is None:
            sale_price = Decimal("0")
            regular_price = Decimal("0")
            stock = 0

        catalog, write_categories = resolve_catalog_for_product(
            product=product,
            existing=existing,
            import_payload=import_payload,
            is_graphql_base=is_graphql_base,
            is_dom_import=is_dom_import,
            is_dom_full=is_dom_full,
            snapshot_target=existing,
        )
        category_l2 = catalog["category_l2"]
        trade_group = catalog["trade_group"]
        sport_type = catalog["sport_type"]
        pricing_category_key = self.pricing_service.resolve_category_key(
            sport_type=sport_type,
            category_l2=category_l2,
        )
        if external_id:
            incoming_external_ids.add(str(external_id))
        incoming_urls.add(product.product_url)
        if sport_type:
            incoming_top_categories.add(sport_type)

        if existing is None:
            db_product = await self._create_product(
                product=product,
                is_graphql_base=is_graphql_base,
                is_graphql_skeleton=is_graphql_skeleton,
                import_payload=import_payload,
                catalog=catalog,
                category_l2=category_l2,
                sport_type=sport_type,
                trade_group=trade_group,
                pricing_category_key=pricing_category_key,
                sale_price=sale_price,
                regular_price=regular_price,
                stock=stock,
                external_id=external_id,
                variants_payload=variants_payload,
                selected_variant=selected_variant,
                download_images=download_images,
                downloaded_cache=downloaded_cache,
                translation_map=translation_map,
                eur_rate=Decimal(settings.eur_rate),
            )
            self.session.add(db_product)
            new_products.append(db_product)
            return {"created": 1, "updated": 0, "skipped": 0}

        prev_taxonomy = product_taxonomy_tuple(existing)

        flags = compute_update_flags(
            existing,
            sale_price=sale_price,
            regular_price=regular_price,
            stock=stock,
            incoming_variant_signature=imp.build_variant_signature(
                variants_payload, selected_variant
            ),
            current_variant_signature=imp.current_variant_signature(existing),
            incoming_gallery_layout=imp.build_gallery_layout_signature(
                product.media_gallery
            ),
            current_gallery_layout=imp.current_gallery_layout_signature(existing),
            incoming_gallery_url_signature=(
                imp.build_supplier_gallery_url_signature(product.media_gallery)
                if is_graphql_base
                else imp.build_gallery_url_signature(product.media_gallery)
            ),
            current_gallery_url_signature=(
                imp.current_supplier_gallery_url_signature(
                    existing, product.media_gallery
                )
                if is_graphql_base
                else imp.current_gallery_url_signature(existing)
            ),
            incoming_feature_signature=imp.build_feature_signature(product.features),
            current_feature_signature=imp.current_feature_signature(existing),
            incoming_description=product.description,
            is_dom_full=is_dom_full,
            is_dom_import=is_dom_import,
            is_graphql_base=is_graphql_base,
            incoming_has_features=incoming_has_features,
            catalog=catalog,
            category_l2=category_l2,
            sport_type=sport_type,
            trade_group=trade_group,
            write_categories=write_categories,
        )
        if not flags.has_changes and is_graphql_base:
            bumped, catalog, write_categories, category_l2, sport_type, trade_group = (
                bump_changes_if_snapshot_updated(
                    existing,
                    product,
                    import_payload,
                    catalog,
                    write_categories,
                )
            )
            if bumped:
                flags = UpdateFlags(
                    has_changes=True,
                    refresh_media=flags.refresh_media,
                    features_changed=flags.features_changed,
                    write_categories=write_categories,
                )

        if not flags.has_changes:
            touch_catalog_sync(existing)
            self.session.add(existing)
            touched_ids.add(int(existing.id))
            if is_dom_import:
                log_dom_product_db(
                    int(existing.id),
                    db_outcome="skipped",
                    supplier_price_committed=False,
                )
            return {"created": 0, "updated": 0, "skipped": 1}

        image_url = existing.image_url
        if flags.refresh_media:
            image_url = None
        elif not image_url and product.image_url:
            image_url = await imp.resolve_image_url(
                product.image_url, download_images, downloaded_cache
            )

        await apply_existing_product_update(
            existing,
            product,
            flags=flags,
            sale_price=sale_price,
            regular_price=regular_price,
            stock=stock,
            external_id=external_id,
            image_url=image_url,
            product_url=product.product_url,
            catalog=catalog,
            category_l2=category_l2,
            sport_type=sport_type,
            trade_group=trade_group,
            pricing_category_key=pricing_category_key,
            eur_rate=Decimal(settings.eur_rate),
            is_graphql_base=is_graphql_base,
            is_dom_full=is_dom_full,
            is_dom_import=is_dom_import,
            translation_map=translation_map,
            variants_payload=variants_payload,
            selected_variant=selected_variant,
            media_gallery=product.media_gallery,
            features=product.features,
            download_images=download_images,
            downloaded_cache=downloaded_cache,
            session=self.session,
            apply_description=imp.apply_description,
            attach_images=imp.attach_images,
            attach_features=imp.attach_features,
            upsert_variants=imp.upsert_variants,
            apply_pricing=self.pricing_service.apply_pricing_to_product,
        )
        self.session.add(existing)
        touched_ids.add(int(existing.id))
        if flags.write_categories or product_taxonomy_tuple(existing) != prev_taxonomy:
            taxonomy_changed_ids.add(int(existing.id))
        if is_dom_import:
            supplier = existing.supplier_price_eur
            log_dom_product_db(
                int(existing.id),
                db_outcome="updated",
                supplier_price_committed=True,
                supplier_price_eur=str(supplier) if supplier is not None else None,
            )
        return {"created": 0, "updated": 1, "skipped": 0}

    # Ищет товар по external_id или URL.
    async def _find_existing(
        self, external_id: str | None, product_url: str
    ) -> Product | None:
        if external_id:
            existing = await self.product_crud.get_by_external_id_with_related(
                external_id
            )
            if existing is not None:
                return existing
        return await self.product_crud.get_by_url_with_related(product_url)

    # Создаёт новый Product из import payload.
    async def _create_product(
        self,
        product: ProductImport,
        is_graphql_base: bool,
        is_graphql_skeleton: bool,
        import_payload: dict[str, Any],
        catalog: dict[str, str | None],
        category_l2: str | None,
        sport_type: str | None,
        trade_group: str | None,
        pricing_category_key: str | None,
        sale_price: Decimal,
        regular_price: Decimal,
        stock: int,
        external_id: str | None,
        variants_payload: list[ProductImportVariant],
        selected_variant: ProductImportVariant | None,
        download_images: bool,
        downloaded_cache: dict[str, str | None],
        translation_map: dict[str, str],
        eur_rate: Decimal,
    ) -> Product:
        description_raw = None
        if not is_graphql_skeleton:
            description_raw = strip_html_plaintext(product.description)
        description_ru = imp.lookup_translation(description_raw, translation_map)
        if description_ru:
            description_ru = strip_html_plaintext(description_ru)
        description_hash = imp.hash_text(description_raw)
        db_product = Product(
            title=product.title,
            brand=product.brand or "",
            sale_price=sale_price,
            regular_price=regular_price,
            supplier_price_eur=sale_price,
            product_url=product.product_url,
            image_url=None,
            description_raw=description_raw,
            description_ru=description_ru,
            description_hash=description_hash,
            description_translated_hash=description_hash if description_ru else None,
            stock=stock,
            is_active=product.is_active,
            external_id=external_id,
            category_l1=catalog["category_l1"],
            category_l2=category_l2,
            category_l3=catalog["category_l3"],
            sport_type=sport_type,
            trade_group=trade_group,
            gender=catalog["gender"],
            pricing_category_key=pricing_category_key,
            eur_rate_snapshot=eur_rate,
            catalog_synced_at=utc_now_naive(),
        )
        if is_graphql_base:
            apply_graphql_snapshot_to_product(db_product, product, import_payload)
        if not is_graphql_skeleton:
            await imp.attach_images(
                db_product,
                product.media_gallery,
                download_images,
                downloaded_cache,
            )
            imp.sync_product_cover_from_gallery(
                db_product,
                downloaded_cache=downloaded_cache if download_images else None,
            )
            if not db_product.image_url and product.image_url:
                managed_cover = await imp.resolve_image_url(
                    product.image_url, download_images, downloaded_cache
                )
                if managed_cover:
                    db_product.image_url = managed_cover
            imp.attach_features(db_product, product.features)
        imp.attach_variants(db_product, variants_payload, selected_variant)
        await self.pricing_service.apply_pricing_to_product(db_product)
        return db_product

    # Снимает с витрины товары из top-кatегорий цикла, которых не было в парсинге.
    async def deactivate_missing_from_snapshot(
        self,
        incoming_external_ids: set[str],
        incoming_urls: set[str],
        incoming_top_categories: set[str],
    ) -> int:
        if not incoming_top_categories:
            return 0

        normalized_external_ids = {
            normalize_external_id(value) for value in incoming_external_ids if value
        }
        normalized_urls = {
            canonical_product_url(value) for value in incoming_urls if value
        }

        active_products = await self.product_crud.list_active_by_top_categories(
            incoming_top_categories
        )
        deactivated = 0
        deactivated_ids: list[int] = []
        for db_product in active_products:
            if product_in_catalog_snapshot(
                external_id=db_product.external_id,
                product_url=db_product.product_url,
                incoming_external_ids=normalized_external_ids,
                incoming_urls=normalized_urls,
            ):
                continue
            logger.info(
                "Finalize: снятие id=%s external_id=%s (нет в GraphQL, было stock=%s)",
                db_product.id,
                db_product.external_id,
                db_product.stock,
            )
            db_product.is_active = False
            db_product.stock = 0
            db_product.deactivated_at = utc_now_naive()
            self.session.add(db_product)
            deactivated += 1
            deactivated_ids.append(int(db_product.id))
        if deactivated_ids:
            await CatalogStockService(self.session).refresh_products(deactivated_ids)
        return deactivated

    # Реактивирует товар, снятый ранее с витрины.
    def _reactivate_catalog_product(self, product: Product) -> None:
        if product.is_active and product.deactivated_at is None:
            return
        product.is_active = True
        product.deactivated_at = None
        self.session.add(product)
