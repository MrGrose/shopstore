from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.order_limits import is_supplier_unit_storefront_allowed
from src.models.order import Order
from src.models.product import Product, ProductImage
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.schemas.catalog_import import ProductImportList
from src.schemas.product import (
    ProductAdminOrderRowSchema,
    ProductAdminSchema,
    ProductAdminVariantSchema,
    ProductCreate,
    ProductSchema,
    ProductUpdate,
    ProductVariantSchema,
)
from src.services.catalog.display.admin_mapping_status import (
    storefront_mapping_status_label_ru,
)
from src.services.catalog.display.admin_status import (
    admin_mapping_orphan_reason,
    admin_nav_status_from_resolution,
    admin_product_tree_status,
)
from src.services.catalog.importing.coordinator import ProductImportService
from src.services.catalog.importing.helpers import sync_product_cover_from_gallery
from src.services.catalog.importing.product_complete import (
    default_dom_max_attempts,
    is_enrichment_hold,
)
from src.services.catalog.read.caches import invalidate_catalog_read_caches
from src.services.catalog.read.service import CatalogService
from src.services.catalog.stock.service import CatalogStockService
from src.services.pricing_service import PricingService
from src.utils.datetime_fmt import format_datetime_msk

PRODUCT_ADMIN_ORDER_HISTORY_PAGE_SIZE = 20


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.product_crud = CrudProduct(session=session, model=Product)
        self.order_crud = CrudOrder(session=session, model=Order)
        self.pricing_service = PricingService(session=session)
        self.catalog = CatalogService(session)
        self.import_service = ProductImportService(session)

    # Возвращает товар по идентификатору.
    async def get_product(self, id: int) -> Product | None:
        product = await self.product_crud.get_by_id_with_related(id)
        if product:
            await self.catalog.enrich_for_display([product])
        return product

    # Товар для публичной витрины (404, если скрыт бренд, кап TP или HOLD).
    async def get_product_for_storefront(self, id: int) -> Product | None:
        product = await self.get_product(id)
        if not product:
            return None
        if is_enrichment_hold(product, default_dom_max_attempts()):
            return None
        if not is_supplier_unit_storefront_allowed(product.supplier_price_eur):
            return None
        if not await self.catalog.is_brand_storefront_visible(product.brand):
            return None
        return product

    # Схема товара для карточки в админке (остатки, резервы, DOM).
    async def get_product_admin_schema(
        self, product_id: int
    ) -> ProductAdminSchema | None:
        product = await self.get_product(product_id)
        if not product:
            return None
        reserved_map = await self.order_crud.get_reserved_quantities([product.id])
        reserved = int(reserved_map.get(product.id, 0))
        variant_ids = [int(v.id) for v in (product.variants or [])]
        reserved_by_variant = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        admin_variants: list[ProductAdminVariantSchema] = []
        for variant in product.variants or []:
            inv = int(variant.inventory_quantity or 0)
            variant_reserved = int(reserved_by_variant.get(variant.id, 0))
            base = ProductVariantSchema.model_validate(variant)
            admin_variants.append(
                ProductAdminVariantSchema(
                    **base.model_dump(),
                    reserved_stock=variant_reserved,
                    available_for_sale=max(0, inv - variant_reserved),
                )
            )
        base = ProductSchema.model_validate(product)
        payload = base.model_dump()
        payload.pop("variants", None)
        repo = StorefrontMappingRepository(self.session)
        active = await repo.get_active_release()
        resolution = None
        if active is not None:
            resolution = await repo.get_product_resolution(active.id, product.id)
        nav_status = admin_nav_status_from_resolution(product, resolution)
        orphan_reason = admin_mapping_orphan_reason(resolution)
        hidden_brands = await self.catalog.get_hidden_brands_set()
        placed: set[int] = set()
        if active is not None:
            placed = await self.product_crud.product_ids_with_storefront_placement(
                active.id, [product.id]
            )
        tree = admin_product_tree_status(
            is_active=bool(product.is_active),
            catalog_in_stock=bool(product.catalog_in_stock),
            brand=product.brand,
            supplier_price_eur=product.supplier_price_eur,
            hidden_brands=hidden_brands,
            has_placement=int(product.id) in placed,
            resolution=resolution,
        )
        return ProductAdminSchema(
            **payload,
            variants=admin_variants,
            supplier_price_eur=Decimal(str(product.supplier_price_eur or 0)),
            reserved_stock=reserved,
            dom_last_error=product.dom_last_error,
            catalog_synced_at_display=format_datetime_msk(
                product.catalog_synced_at,
                with_tz_label=False,
            ),
            storefront_mapping_status=nav_status,
            storefront_mapping_status_label_ru=storefront_mapping_status_label_ru(
                nav_status
            ),
            storefront_mapping_orphan_reason=orphan_reason,
            catalog_inclusion=tree.inclusion,
            storefront_site=tree.site,
            storefront_hide_reasons=list(tree.reasons),
        )

    # Страница истории заказов товара для админ-вкладки «Заказы».
    async def get_product_order_history_page(
        self, product_id: int, page: int = 1
    ) -> tuple[list[ProductAdminOrderRowSchema], int, int, int]:
        page_size = PRODUCT_ADMIN_ORDER_HISTORY_PAGE_SIZE
        total = await self.order_crud.count_orders_for_product(product_id)
        total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
        safe_page = min(max(1, int(page)), total_pages)
        rows = await self.order_crud.list_orders_for_product(
            product_id,
            page=safe_page,
            page_size=page_size,
        )
        items = [ProductAdminOrderRowSchema.model_validate(row) for row in rows]
        return items, total, total_pages, safe_page

    # Прикрепляет галерею к ручному товару.
    @staticmethod
    def _normalize_admin_gallery_urls(urls: list[str]) -> list[str]:
        clean: list[str] = []
        seen: set[str] = set()
        for raw in urls:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            clean.append(url)
        return clean

    @classmethod
    def _replace_admin_gallery(cls, product: Product, urls: list[str]) -> None:
        product.images.clear()
        for idx, url in enumerate(cls._normalize_admin_gallery_urls(urls)):
            product.images.append(
                ProductImage(url=url, alt=None, position=idx),
            )

    @classmethod
    def _attach_admin_gallery(cls, product: Product, urls: list[str]) -> None:
        clean = cls._normalize_admin_gallery_urls(urls)
        if not clean:
            return
        for idx, url in enumerate(clean):
            product.images.append(
                ProductImage(url=url, alt=None, position=idx),
            )
        sync_product_cover_from_gallery(product)

    # Сбрасывает Redis read-кэши каталога после успешного commit.
    @staticmethod
    def _invalidate_catalog_read_caches(reason: str) -> None:
        invalidate_catalog_read_caches(reason=reason)

    # Создает товар по идентификатору.
    async def create_product(
        self,
        payload: ProductCreate,
        gallery_urls: list[str] | None = None,
    ) -> Product:
        if await self.product_crud.get_by_url(payload.product_url):
            raise ValueError("Продукт с таким URL уже существует")
        db_product = Product(
            **payload.model_dump(), supplier_price_eur=payload.sale_price
        )
        merged_urls = list(gallery_urls or [])
        if payload.image_url and payload.image_url not in merged_urls:
            merged_urls.insert(0, payload.image_url)
        if merged_urls:
            self._attach_admin_gallery(db_product, merged_urls)
        elif payload.image_url:
            db_product.image_url = payload.image_url
        await self.pricing_service.apply_pricing_to_product(db_product)
        self.session.add(db_product)
        await self.session.commit()
        await self.session.refresh(db_product)
        await CatalogStockService(self.session).refresh_products([db_product.id])
        await self.session.commit()
        self._invalidate_catalog_read_caches("product_create")
        return db_product

    # Остаток товара без вариантов.
    @staticmethod
    def _apply_stock(product: Product, stock: int) -> None:
        product.stock = max(0, int(stock))

    # Остатки по SKU (variant_id -> quantity); product.stock = сумма.
    @staticmethod
    def _apply_variant_stocks(product: Product, stocks: dict[int, int]) -> None:
        # Создаем словарь вариантов по ID.
        variant_by_id = {v.id: v for v in product.variants or []}
        # Обновляем остатки по SKU.
        for variant_id, quantity in stocks.items():
            variant = variant_by_id.get(variant_id)
            if variant is None:
                raise ValueError(f"Вариант #{variant_id} не найден")
            qty = max(0, int(quantity))
            variant.inventory_quantity = qty
            variant.available = qty > 0
        product.stock = sum(
            int(v.inventory_quantity or 0) for v in (product.variants or [])
        )

    # Обновляет товар по идентификатору.
    async def update_product(
        self,
        id: int,
        payload: ProductUpdate,
        variant_stocks: dict[int, int] | None = None,
        gallery_urls: list[str] | None = None,
    ) -> Product:
        product = await self.product_crud.get_by_id_with_related(id)
        if not product:
            raise ValueError("Продукт не найден")
        # Проверяем, что URL не дублируется.
        if payload.product_url and payload.product_url != product.product_url:
            duplicate = await self.product_crud.get_by_url(payload.product_url)
            if duplicate and duplicate.id != product.id:
                raise ValueError("Продукт с таким URL уже существует")
        # Извлекаем данные для обновления.
        raw_updates = payload.model_dump(exclude_unset=True)
        image_url = raw_updates.pop("image_url", "__unset__")
        updates = {
            key: value for key, value in raw_updates.items() if value is not None
        }
        stock_value = updates.pop("stock", None)
        sale_price = updates.pop("sale_price", None)
        regular_price = updates.pop("regular_price", None)

        # Обновляем поля товара.
        for field, value in updates.items():
            setattr(product, field, value)

        # Обновляем остатки по SKU.
        if variant_stocks:
            self._apply_variant_stocks(product, variant_stocks)
        elif stock_value is not None:
            # Если у товара есть варианты, то остаток нужно указывать по SKU.
            if product.variants:
                raise ValueError("У товара есть варианты, укажите остаток по SKU")
            self._apply_stock(product, stock_value)

        # Обновляем цены.
        if sale_price is not None:
            product.sale_price = sale_price
            product.regular_price = (
                regular_price if regular_price is not None else sale_price
            )
        elif regular_price is not None:
            product.regular_price = regular_price

        if gallery_urls is not None:
            self._replace_admin_gallery(product, gallery_urls)
        if image_url != "__unset__":
            product.image_url = image_url or None
            if not product.image_url and product.images:
                sync_product_cover_from_gallery(product)

        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        await CatalogStockService(self.session).refresh_products([product.id])
        await self.session.commit()
        self._invalidate_catalog_read_caches("product_update")
        return product

    # Массово включает/выключает товары по виду спорта и опционально category_l2.
    async def bulk_set_active_by_top_category(
        self,
        top_category: str,
        is_active: bool,
        category_l2: str | None = None,
    ) -> int:
        affected_ids = await self.product_crud.bulk_set_active_by_top_category(
            top_category,
            is_active,
            category_l2=category_l2,
        )
        if affected_ids:
            await CatalogStockService(self.session).refresh_products(affected_ids)
            await self.session.commit()
            self._invalidate_catalog_read_caches(
                "product_bulk_set_active_by_top_category"
            )
        return len(affected_ids)

    # Массово включает/выключает товары на витрине.
    async def bulk_set_active(self, product_ids: list[int], is_active: bool) -> int:
        if not product_ids:
            return 0
        updated = 0
        for product_id in product_ids:
            product = await self.product_crud.get_by_id(product_id)
            if not product:
                continue
            if product.is_active == is_active:
                continue
            product.is_active = is_active
            self.session.add(product)
            updated += 1
        if updated:
            await self.session.commit()
            await CatalogStockService(self.session).refresh_products(product_ids)
            await self.session.commit()
            self._invalidate_catalog_read_caches("product_bulk_set_active")
        return updated

    # Деактивирует товар по идентификатору.
    async def soft_delete_product(self, id: int) -> Product:
        product = await self.product_crud.get_by_id(id)
        if not product:
            raise ValueError("Продукт не найден")
        product.is_active = False
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        await CatalogStockService(self.session).refresh_products([product.id])
        await self.session.commit()
        self._invalidate_catalog_read_caches("product_soft_delete")
        return product

    # Удаляет товар по идентификатору.
    async def hard_delete_product(self, id: int) -> Product:
        try:
            deleted = await self.product_crud.delete(id)
            self._invalidate_catalog_read_caches("product_hard_delete")
            return deleted
        except IntegrityError as exc:
            raise ValueError(
                "Нельзя удалить: товар связан с заказами или корзинами"
            ) from exc

    # Импортирует товары из списка.
    async def import_products(
        self,
        data: ProductImportList,
        download_images: bool = True,
        deactivate_missing: bool = False,
    ) -> dict[str, int | list[int]]:
        return await self.import_service.import_products(
            data,
            download_images=download_images,
            deactivate_missing=deactivate_missing,
        )

    # Деактивирует товары, которые отсутствуют в snapshot.
    async def deactivate_missing_from_snapshot(
        self,
        incoming_external_ids: set[str],
        incoming_urls: set[str],
        incoming_top_categories: set[str],
    ) -> int:
        return await self.import_service.deactivate_missing_from_snapshot(
            incoming_external_ids=incoming_external_ids,
            incoming_urls=incoming_urls,
            incoming_top_categories=incoming_top_categories,
        )
