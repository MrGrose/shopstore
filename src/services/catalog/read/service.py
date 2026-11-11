import asyncio
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import (
    get_reference_ttl_cache,
    invalidate_reference_ttl_cache,
    set_reference_ttl_cache,
    single_flight,
)
from src.core.config import settings
from src.core.order_limits import max_supplier_goods_eur
from src.models.order import Order
from src.models.product import Product, ProductVariant
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.schemas.catalog import (
    ADMIN_BRANDS_PAGE_SIZE,
    AdminBrandRow,
    CatalogFacetOptionSchema,
    CatalogFacetsSchema,
    CatalogFilterSelection,
    CatalogPageState,
    CatalogProductMetaSchema,
)
from src.schemas.catalog_labels import CatalogNavigationSchema, CatalogSubCategorySchema
from src.schemas.product import ProductPublicCardSchema
from src.services.catalog.display.admin_status import (
    admin_nav_status_from_resolution,
    admin_product_tree_status,
)
from src.services.catalog.display.catalog_read import StorefrontCatalogReadService
from src.services.catalog.display.navigation import build_catalog_navigation
from src.services.catalog.display.runtime import require_active_release_id
from src.services.catalog.read.caches import (
    build_count_cache_key,
    build_facets_cache_key,
    build_subcategories_cache_key,
    get_cached_count,
    get_cached_facets,
    get_cached_subcategories,
    invalidate_catalog_read_caches,
    set_cached_count,
    set_cached_facets,
    set_cached_subcategories,
)
from src.services.catalog.read.scope import (
    CATALOG_ALL_TOP_CATEGORY,
    CATALOG_TOP_ORDER,
    AdminCatalogTree,
    CatalogScope,
    CatalogStockFilters,
    normalize_storefront_top_category,
    require_complete_from_stock_filters,
)
from src.services.catalog.read.sort import (
    CatalogAdminSort,
    normalize_admin_sort,
    normalize_sort_price,
)
from src.utils.images import resolve_product_cover_url
from src.utils.labels import (
    normalize_gender,
    translate_color_value,
    translate_gender,
    translate_subcategory_type,
)
from src.utils.pagination import catalog_total_pages
from src.utils.product_availability import (
    product_display_available_stock,
    variant_available_qty,
)


# Переводит label_ru types подкатегории по актуальному словарю (в т.ч. из Redis-кэша).
def _refresh_subcategory_type_labels(
    row: CatalogSubCategorySchema,
) -> CatalogSubCategorySchema:
    level = row.type_level or "l2"
    return row.model_copy(
        update={
            "types": [
                item.model_copy(
                    update={
                        "label_ru": item.label_ru
                        or translate_subcategory_type(item.key, type_level=level),
                    }
                )
                for item in row.types
            ],
        }
    )


class CatalogService:
    # AsyncSession и CRUD для read API каталога.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.product_crud = CrudProduct(session=session, model=Product)
        self.order_crud = CrudOrder(session=session, model=Order)

    # Имена брендов, скрытых с витрины (из catalog_hidden_brands).
    async def get_hidden_brands_set(self) -> frozenset[str]:
        cached = get_reference_ttl_cache("catalog:hidden_brands")
        if cached is not None:
            return cached
        names = await self.product_crud.get_hidden_brand_names()
        result = frozenset(names)
        set_reference_ttl_cache("catalog:hidden_brands", result)
        return result

    # Набор скрытых брендов для repo-фильтра витрины.
    async def _hidden_brands_for_read(
        self, exclude_hidden_brands: bool
    ) -> frozenset[str] | None:
        if not exclude_hidden_brands:
            return None
        return await self.get_hidden_brands_set()

    # Виден ли бренд на витрине.
    async def is_brand_storefront_visible(self, brand: str | None) -> bool:
        name = (brand or "").strip()
        if not name:
            return True
        hidden = await self.get_hidden_brands_set()
        return name not in hidden

    # Сводка для вкладки «Бренды» (без фильтров поиска/видимости).
    async def get_admin_brands_summary(self) -> dict[str, int]:
        counts = await self.product_crud.list_distinct_brands_with_counts()
        hidden = await self.get_hidden_brands_set()
        visible_brands = 0
        for brand, _count in counts:
            if brand in hidden:
                continue
            visible_brands += 1
        total = len(counts)
        return {
            "total_brands": total,
            "visible_brands": visible_brands,
            "hidden_brands": total - visible_brands,
        }

    # Строки для админ-вкладки «Бренды» (страница списка).
    async def list_admin_brand_rows(
        self,
        q: str | None = None,
        visibility: str = "all",
        page: int = 1,
        page_size: int = ADMIN_BRANDS_PAGE_SIZE,
    ) -> tuple[list[AdminBrandRow], int, int, int, int]:
        counts = await self.product_crud.list_distinct_brands_with_counts()
        hidden = await self.get_hidden_brands_set()
        term = (q or "").strip().lower()
        mode = (visibility or "all").strip().lower()
        rows: list[AdminBrandRow] = [
            {
                "brand": brand,
                "product_count": count,
                "storefront_visible": brand not in hidden,
            }
            for brand, count in counts
        ]
        if term:
            rows = [row for row in rows if term in str(row["brand"]).lower()]
        if mode == "visible":
            rows = [row for row in rows if row["storefront_visible"]]
        elif mode == "hidden":
            rows = [row for row in rows if not row["storefront_visible"]]
        brand_total = len(rows)
        products_total = sum(row["product_count"] for row in rows)
        safe_size = max(1, int(page_size))
        total_pages = catalog_total_pages(brand_total, safe_size)
        safe_page = min(max(1, int(page)), total_pages)
        start = (safe_page - 1) * safe_size
        page_rows = rows[start : start + safe_size]
        return page_rows, brand_total, products_total, total_pages, safe_page

    # Переключает видимость бренда на витрине.
    async def set_brand_storefront_visible(self, brand: str, visible: bool) -> None:
        await self.product_crud.set_brand_hidden(brand, hidden=not visible)
        await self.session.commit()
        invalidate_reference_ttl_cache("catalog:hidden_brands")
        invalidate_catalog_read_caches(reason="brand_visibility")

    # Дополняет товары для отображения.
    async def enrich_for_display(
        self,
        products: list[Product],
        resolve_local_images: bool = True,
    ) -> None:
        if resolve_local_images:
            self._resolve_display_images(products)
        await self._attach_available_stock(products)

    # Возвращает список товаров с пагинацией.
    async def get_products_list(
        self,
        page: int,
        page_size: int,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        top_category: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        sort_price: str | None = None,
        admin_sort: CatalogAdminSort | None = None,
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        exclude_hidden_brands: bool = False,
        storefront_mapping_status: str | None = None,
        resolve_local_images: bool = True,
        count_total: bool = True,
        load_product_images: bool = True,
        load_cover_image: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
        admin_mapping_release_id: int | None = None,
        admin_tree: AdminCatalogTree | None = None,
        admin_tree_release_id: int | None = None,
        admin_tree_hidden_brands: frozenset[str] | None = None,
    ) -> tuple[list[Product], int | None, bool]:
        hidden = await self._hidden_brands_for_read(exclude_hidden_brands)
        items, total, has_more = await self.product_crud.paginate_products(
            page,
            page_size,
            category=category,
            categories=categories,
            category_l3=category_l3,
            top_category=top_category,
            brands=brands,
            genders=genders,
            colors=colors,
            sizes=sizes,
            price_min=price_min,
            price_max=price_max,
            sort_price=sort_price,
            admin_sort=admin_sort,
            q=q,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
            hidden_brands_to_exclude=hidden,
            storefront_mapping_status=storefront_mapping_status,
            count_total=count_total,
            load_product_images=load_product_images,
            load_cover_image=load_cover_image,
            mapping_release_id=mapping_release_id,
            chip_node_ids=chip_node_ids,
            admin_mapping_release_id=admin_mapping_release_id,
            admin_tree=admin_tree,
            admin_tree_release_id=admin_tree_release_id,
            admin_tree_hidden_brands=admin_tree_hidden_brands,
        )
        await self.enrich_for_display(items, resolve_local_images=resolve_local_images)
        if admin_tree is not None and admin_tree_release_id is not None:
            await self._attach_admin_tree_status(
                items,
                admin_tree_release_id,
                admin_tree_hidden_brands or frozenset(),
            )
        elif admin_mapping_release_id is not None:
            await self._attach_admin_nav_status(items, admin_mapping_release_id)
        return items, total, has_more

    # Проставляет catalog/site/reason на ORM-объекты страницы админки.
    async def _attach_admin_tree_status(
        self,
        products: list[Product],
        release_id: int,
        hidden_brands: frozenset[str],
    ) -> None:
        if not products:
            return
        repo = StorefrontMappingRepository(self.session)
        ids = [product.id for product in products]
        resolutions = await repo.get_product_resolutions_map(release_id, ids)
        placed = await self.product_crud.product_ids_with_storefront_placement(
            release_id, ids
        )
        for product in products:
            status = admin_product_tree_status(
                is_active=bool(product.is_active),
                catalog_in_stock=bool(product.catalog_in_stock),
                brand=product.brand,
                supplier_price_eur=product.supplier_price_eur,
                hidden_brands=hidden_brands,
                has_placement=int(product.id) in placed,
                resolution=resolutions.get(product.id),
            )
            setattr(product, "catalog_inclusion", status.inclusion)
            setattr(product, "storefront_site", status.site)
            setattr(product, "storefront_hide_reasons", list(status.reasons))
            nav = admin_nav_status_from_resolution(product, resolutions.get(product.id))
            setattr(product, "storefront_mapping_status", nav)

    # Проставляет admin nav pill на ORM-объекты из resolutions release.
    async def _attach_admin_nav_status(
        self, products: list[Product], release_id: int
    ) -> None:
        if not products:
            return
        repo = StorefrontMappingRepository(self.session)
        resolutions = await repo.get_product_resolutions_map(
            release_id,
            [product.id for product in products],
        )
        for product in products:
            status = admin_nav_status_from_resolution(
                product,
                resolutions.get(product.id),
            )
            setattr(product, "storefront_mapping_status", status)

    # Возвращает число товаров в срезе (Redis-кэш, отдельно от /products).
    async def get_catalog_product_count(
        self,
        top_category: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        exclude_hidden_brands: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> int:
        price_min_str = str(price_min) if price_min is not None else None
        price_max_str = str(price_max) if price_max is not None else None
        cache_key = await build_count_cache_key(
            top_category=top_category,
            category=category,
            categories=categories,
            category_l3=category_l3,
            brands=brands,
            genders=genders,
            colors=colors,
            sizes=sizes,
            price_min=price_min_str,
            price_max=price_max_str,
            q=q,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_hidden_brands=exclude_hidden_brands,
            max_goods_eur=(
                str(max_supplier_goods_eur()) if exclude_over_supplier_unit_cap else ""
            ),
            require_complete=require_complete,
            mapping_release_id=mapping_release_id,
            chip_node_ids=chip_node_ids,
        )
        ttl = settings.CATALOG_COUNT_CACHE_TTL_SECONDS

        async def load_count() -> int:
            hidden = await self._hidden_brands_for_read(exclude_hidden_brands)
            total = await self.product_crud.count_catalog_products(
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
                require_complete=require_complete,
                hidden_brands_to_exclude=hidden,
                mapping_release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
            )
            if ttl > 0:
                await set_cached_count(cache_key, total, ttl)
            return total

        if ttl > 0:
            cached = await get_cached_count(cache_key)
            if cached is not None:
                return cached
            return await single_flight(f"catalog:count:{cache_key}", load_count)
        return await load_count()

    # Возвращает taxonomy active release для mapping mode.
    async def get_catalog_taxonomy_mapping(self) -> dict:
        release_id = await require_active_release_id(self.session)
        cache_key = f"catalog:taxonomy:{release_id}"
        cached = get_reference_ttl_cache(cache_key)
        if cached is not None:
            return cached
        data = await StorefrontCatalogReadService(self.session).build_taxonomy(
            release_id
        )
        set_reference_ttl_cache(cache_key, data)
        return data

    # Считает товары по top-категориям через placements active release.
    async def get_top_category_product_counts_mapping(
        self,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> dict[str, int]:
        release_id = await require_active_release_id(self.session)
        read_svc = StorefrontCatalogReadService(self.session)
        availability = read_svc._availability_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        counts: dict[str, int] = {}
        for top in CATALOG_TOP_ORDER:
            chip_ids = await read_svc.repo.descendant_chip_ids(release_id, top)
            counts[top] = await read_svc.repo.count_distinct_products_for_chips(
                release_id,
                chip_ids,
                availability,
            )
        return counts

    # Возвращает список категорий каталога.
    async def get_catalog_categories(
        self,
        top_category: str | None = None,
        categories: list[str] | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[str]:
        return await self.product_crud.get_catalog_categories(
            top_category=top_category,
            categories=categories,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )

    # Возвращает список подкатегорий каталога.
    async def get_catalog_subcategories(
        self,
        top_category: str,
        sub_slug: str | None = None,
        locale: str = "ru",
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        exclude_hidden_brands: bool = False,
        mapping_release_id: int | None = None,
    ) -> list[CatalogSubCategorySchema]:
        top = normalize_storefront_top_category(top_category) or top_category
        if top == CATALOG_ALL_TOP_CATEGORY:
            return []

        stock_filters: CatalogStockFilters = {
            "include_out_of_stock": include_out_of_stock,
            "zero_stock_only": zero_stock_only,
            "inactive_only": inactive_only,
            "exclude_over_supplier_unit_cap": exclude_over_supplier_unit_cap,
            "require_complete": require_complete,
        }

        release_id = mapping_release_id or await require_active_release_id(self.session)
        read_svc = StorefrontCatalogReadService(self.session)
        sub = (sub_slug or "").strip()
        if not sub:
            return await read_svc.build_subcategories(
                release_id,
                top,
                None,
                **stock_filters,
            )
        cache_key = await build_subcategories_cache_key(
            top_category=top,
            sub_slug=sub,
            locale=locale,
            mapping_release_id=release_id,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_hidden_brands=exclude_hidden_brands,
            max_goods_eur=(
                str(max_supplier_goods_eur()) if exclude_over_supplier_unit_cap else ""
            ),
            require_complete=require_complete,
        )
        ttl = settings.CATALOG_SUBCATEGORIES_CACHE_TTL_SECONDS

        async def load_subcategories() -> list[CatalogSubCategorySchema]:
            rows = await read_svc.build_subcategories(
                release_id,
                top,
                sub,
                **stock_filters,
            )
            if len(rows) == 1 and ttl > 0:
                await set_cached_subcategories(cache_key, rows[0], ttl)
            return rows

        if ttl > 0:
            cached = await get_cached_subcategories(cache_key)
            if cached is not None:
                return [_refresh_subcategory_type_labels(cached)]
            return await single_flight(
                f"catalog:subcategories:{cache_key}",
                load_subcategories,
            )
        return await load_subcategories()

    # Возвращает top-категории каталога.
    async def get_catalog_top_categories(
        self,
        preferred_order: tuple[str, ...] = ("Tennis", "Running", "Padel"),
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[str]:
        return await self.product_crud.get_top_categories_with_catalog_products(
            preferred_order=preferred_order,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )

    # Возвращает список брендов каталога.
    async def get_catalog_brands(
        self,
        top_category: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        exclude_hidden_brands: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> list[str]:
        hidden = await self._hidden_brands_for_read(exclude_hidden_brands)
        return await self.product_crud.get_catalog_brands(
            top_category=top_category,
            category=category,
            categories=categories,
            category_l3=category_l3,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
            hidden_brands_to_exclude=hidden,
            mapping_release_id=mapping_release_id,
            chip_node_ids=chip_node_ids,
        )

    # Возвращает reconciliation-сводку админ-каталога (top + category_l2).
    async def get_catalog_admin_summary(
        self,
        top_category: str | None = None,
        category: str | None = None,
        hidden_brands: frozenset[str] | None = None,
        mapping_release_id: int | None = None,
    ) -> dict[str, int]:
        release_id = mapping_release_id or await require_active_release_id(self.session)
        hidden = (
            hidden_brands
            if hidden_brands is not None
            else await self.get_hidden_brands_set()
        )
        return await self.product_crud.get_catalog_admin_summary(
            top_category,
            category=category,
            hidden_brands=hidden,
            mapping_release_id=release_id,
        )

    # Возвращает фасеты (бренды, типы, размеры) для среза каталога.
    async def get_catalog_facets(
        self,
        top_category: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        include: str = "all",
        exclude_hidden_brands: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> CatalogFacetsSchema:
        include_key = (include or "all").strip().lower() or "all"
        price_min_str = str(price_min) if price_min is not None else None
        price_max_str = str(price_max) if price_max is not None else None
        ttl = settings.CATALOG_FACETS_CACHE_TTL_SECONDS
        cache_key: str | None = None
        if ttl > 0:
            cache_key = await build_facets_cache_key(
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min_str,
                price_max=price_max_str,
                q=q,
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                include=include_key,
                exclude_hidden_brands=exclude_hidden_brands,
                max_goods_eur=(
                    str(max_supplier_goods_eur())
                    if exclude_over_supplier_unit_cap
                    else ""
                ),
                require_complete=require_complete,
                mapping_release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
            )

        async def load_facets() -> CatalogFacetsSchema:
            hidden = await self._hidden_brands_for_read(exclude_hidden_brands)
            raw = await self.product_crud.get_catalog_facets(
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
                require_complete=require_complete,
                include=include_key,
                hidden_brands_to_exclude=hidden,
                mapping_release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
            )
            result = CatalogFacetsSchema(
                brands=[
                    CatalogFacetOptionSchema(
                        value=str(row["value"]),
                        label_ru=str(row["value"]),
                        count=int(row["count"]),
                    )
                    for row in raw["brands"]
                ],
                genders=[
                    CatalogFacetOptionSchema(
                        value=str(row["value"]),
                        label_ru=translate_gender(str(row["value"])),
                        count=int(row["count"]),
                    )
                    for row in raw["genders"]
                ],
                colors=[
                    CatalogFacetOptionSchema(
                        value=str(row["value"]),
                        label_ru=translate_color_value(str(row["value"])),
                        count=int(row["count"]),
                    )
                    for row in raw["colors"]
                ],
                sizes=[
                    CatalogFacetOptionSchema(
                        value=str(row["value"]),
                        label_ru=str(row["value"]),
                        count=int(row["count"]),
                    )
                    for row in raw["sizes"]
                ],
                price_min=raw["price_min"],
                price_max=raw["price_max"],
            )
            if cache_key is not None:
                await set_cached_facets(cache_key, result, ttl)
            return result

        if cache_key is not None:
            cached = await get_cached_facets(cache_key)
            if cached is not None:
                return cached
            return await single_flight(f"catalog:facets:{cache_key}", load_facets)
        return await load_facets()

    async def get_catalog_product_meta(
        self,
        top_category: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        include: str = "all",
        exclude_hidden_brands: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> CatalogProductMetaSchema:
        total, facets = await asyncio.gather(
            self.get_catalog_product_count(
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
                require_complete=require_complete,
                exclude_hidden_brands=exclude_hidden_brands,
                mapping_release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
            ),
            self.get_catalog_facets(
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                include=include,
                exclude_hidden_brands=exclude_hidden_brands,
                exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
                require_complete=require_complete,
                mapping_release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
            ),
        )
        return CatalogProductMetaSchema(total=total, facets=facets)

    # Возвращает navigation payload для resolved scope витрины.
    async def get_catalog_navigation(
        self,
        top_category: str | None = None,
        section: str | None = None,
        node: str | None = None,
        sub: str | None = None,
        category_type: str | None = None,
        legacy_type: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> CatalogNavigationSchema:
        return await build_catalog_navigation(
            self.session,
            top_category=top_category,
            section=section,
            node=node,
            sub=sub,
            category_type=category_type,
            legacy_type=legacy_type,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )

    # Решает выбранную top-категорию.
    @staticmethod
    def resolve_selected_top(
        top: str,
        top_categories: list[str],
        preferred_order: tuple[str, ...] = CATALOG_TOP_ORDER,
    ) -> str:
        if top in preferred_order:
            return top
        if top in top_categories:
            return top
        if top_categories:
            return top_categories[0]
        return preferred_order[0]

    # Решает фильтры каталога.
    async def _resolve_catalog_filters(
        self,
        top: str,
        category: str | None,
        brand: str | None,
        scope: CatalogScope,
        preferred_order: tuple[str, ...],
        gender: str | None = None,
        color: str | None = None,
        size: str | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
    ) -> CatalogFilterSelection:
        list_filters = scope.list_filter_kwargs()
        top_categories = await self.get_catalog_top_categories(
            preferred_order=preferred_order,
            **list_filters,
        )
        top = normalize_storefront_top_category(top) or top
        if top == CATALOG_ALL_TOP_CATEGORY:
            selected_top = CATALOG_ALL_TOP_CATEGORY
        else:
            selected_top = self.resolve_selected_top(
                top, top_categories, preferred_order=preferred_order
            )
        categories = await self.get_catalog_categories(
            top_category=selected_top,
            include_out_of_stock=list_filters["include_out_of_stock"],
            zero_stock_only=list_filters["zero_stock_only"],
            inactive_only=list_filters["inactive_only"],
            exclude_over_supplier_unit_cap=list_filters[
                "exclude_over_supplier_unit_cap"
            ],
            require_complete=list_filters["require_complete"],
        )
        selected_category = category if category in categories else None
        brands: list[str] = []
        stock_filters: CatalogStockFilters = {
            "include_out_of_stock": list_filters["include_out_of_stock"],
            "zero_stock_only": list_filters["zero_stock_only"],
            "inactive_only": list_filters["inactive_only"],
            "exclude_over_supplier_unit_cap": list_filters[
                "exclude_over_supplier_unit_cap"
            ],
            "require_complete": require_complete_from_stock_filters(
                list_filters, scope
            ),
        }
        if selected_category:
            brands = await self.get_catalog_brands(
                top_category=selected_top,
                category=selected_category,
                include_out_of_stock=stock_filters["include_out_of_stock"],
                zero_stock_only=stock_filters["zero_stock_only"],
                inactive_only=stock_filters["inactive_only"],
                exclude_over_supplier_unit_cap=stock_filters[
                    "exclude_over_supplier_unit_cap"
                ],
                require_complete=require_complete_from_stock_filters(
                    stock_filters, scope
                ),
            )
        elif selected_top == CATALOG_ALL_TOP_CATEGORY:
            brands = await self.get_catalog_brands(
                top_category=CATALOG_ALL_TOP_CATEGORY,
                include_out_of_stock=stock_filters["include_out_of_stock"],
                zero_stock_only=stock_filters["zero_stock_only"],
                inactive_only=stock_filters["inactive_only"],
                exclude_over_supplier_unit_cap=stock_filters[
                    "exclude_over_supplier_unit_cap"
                ],
                require_complete=require_complete_from_stock_filters(
                    stock_filters, scope
                ),
            )
        if brand and brand.strip():
            cleaned_brand = brand.strip()
            selected_brand = (
                cleaned_brand if not brands or cleaned_brand in brands else None
            )
        else:
            selected_brand = None
        selected_gender = normalize_gender(gender) if gender else None
        selected_color = color.strip() if color and color.strip() else None
        selected_size = size.strip() if size and size.strip() else None
        return CatalogFilterSelection(
            top_categories=top_categories,
            selected_top=selected_top,
            categories=categories,
            selected_category=selected_category,
            brands=brands,
            selected_brand=selected_brand,
            selected_gender=selected_gender,
            selected_color=selected_color,
            selected_size=selected_size,
            price_min=price_min,
            price_max=price_max,
        )

    # Возвращает список товаров с пагинацией.
    async def _paginate_catalog_items(
        self,
        page: int,
        page_size: int,
        filters: CatalogFilterSelection,
        scope: CatalogScope,
        sort_price: str | None = None,
        admin_sort: CatalogAdminSort | None = None,
        q: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        storefront_mapping_status: str | None = None,
        admin_tree: AdminCatalogTree | None = None,
        admin_tree_release_id: int | None = None,
        admin_tree_hidden_brands: frozenset[str] | None = None,
    ) -> tuple[list[ProductPublicCardSchema], int]:
        admin_mapping_release_id = None
        status = (storefront_mapping_status or "").strip() or "all"
        if admin_tree is None and status != "all":
            admin_mapping_release_id = await require_active_release_id(self.session)
        items, total, _has_more = await self.get_products_list(
            page=page,
            page_size=page_size,
            category=filters.selected_category,
            categories=categories,
            category_l3=category_l3,
            top_category=filters.selected_top,
            brands=[filters.selected_brand] if filters.selected_brand else None,
            genders=[filters.selected_gender] if filters.selected_gender else None,
            colors=[filters.selected_color] if filters.selected_color else None,
            sizes=[filters.selected_size] if filters.selected_size else None,
            price_min=filters.price_min,
            price_max=filters.price_max,
            sort_price=sort_price,
            admin_sort=admin_sort,
            q=q,
            storefront_mapping_status=storefront_mapping_status,
            admin_mapping_release_id=admin_mapping_release_id,
            admin_tree=admin_tree,
            admin_tree_release_id=admin_tree_release_id,
            admin_tree_hidden_brands=admin_tree_hidden_brands,
            **scope.list_filter_kwargs(),
        )
        public_items = [ProductPublicCardSchema.model_validate(row) for row in items]
        return public_items, int(total or 0)

    # Возвращает состояние страницы каталога.
    @staticmethod
    def _catalog_page_state(
        page: int,
        page_size: int,
        filters: CatalogFilterSelection,
        scope: CatalogScope,
        items: list[ProductPublicCardSchema],
        total: int,
        catalog_summary: dict[str, int] | None,
    ) -> CatalogPageState:
        return CatalogPageState(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            top_categories=filters.top_categories,
            categories=filters.categories,
            brands=filters.brands,
            selected_top=filters.selected_top,
            selected_category=filters.selected_category,
            selected_brand=filters.selected_brand,
            selected_gender=filters.selected_gender,
            selected_color=filters.selected_color,
            selected_size=filters.selected_size,
            price_min=filters.price_min,
            price_max=filters.price_max,
            catalog_summary=catalog_summary,
            show_out_of_stock=scope.include_out_of_stock,
            show_zero_stock=scope.zero_stock_only,
            show_removed=scope.inactive_only,
        )

    # Возвращает состояние страницы каталога.
    async def build_catalog_page_state(
        self,
        page: int,
        page_size: int,
        top: str = "Padel",
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        brand: str | None = None,
        gender: str | None = None,
        color: str | None = None,
        size: str | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        sort_price: str | None = None,
        sort: str | None = None,
        q: str | None = None,
        scope: CatalogScope | None = None,
        preferred_order: tuple[str, ...] = CATALOG_TOP_ORDER,
        include_admin_summary: bool = False,
        storefront_mapping_status: str | None = None,
        admin_tree: AdminCatalogTree | None = None,
    ) -> CatalogPageState:
        catalog_scope = scope or CatalogScope.storefront_public()
        admin_sort = normalize_admin_sort(sort, sort_price)
        storefront_sort = normalize_sort_price(sort_price) if not admin_sort else None
        filters = await self._resolve_catalog_filters(
            top=top,
            category=category,
            brand=brand,
            gender=gender,
            color=color,
            size=size,
            price_min=price_min,
            price_max=price_max,
            scope=catalog_scope,
            preferred_order=preferred_order,
        )
        tree_release_id = None
        tree_hidden = None
        if admin_tree is not None:
            tree_release_id = await require_active_release_id(self.session)
            tree_hidden = await self.get_hidden_brands_set()
        items, total = await self._paginate_catalog_items(
            page=page,
            page_size=page_size,
            filters=filters,
            scope=catalog_scope,
            sort_price=storefront_sort,
            admin_sort=admin_sort,
            q=q.strip() if q and q.strip() else None,
            categories=categories,
            category_l3=category_l3,
            storefront_mapping_status=(
                None if admin_tree is not None else storefront_mapping_status
            ),
            admin_tree=admin_tree,
            admin_tree_release_id=tree_release_id,
            admin_tree_hidden_brands=tree_hidden,
        )
        catalog_summary = None
        if include_admin_summary:
            catalog_summary = await self.get_catalog_admin_summary(
                top_category=filters.selected_top,
                category=filters.selected_category,
                hidden_brands=tree_hidden,
                mapping_release_id=tree_release_id,
            )
        return self._catalog_page_state(
            page=page,
            page_size=page_size,
            filters=filters,
            scope=catalog_scope,
            items=items,
            total=total,
            catalog_summary=catalog_summary,
        )

    # Дополняет товары доступным остатком.
    async def _attach_available_stock(self, products: list[Product]) -> None:
        if not products:
            return
        product_ids = [product.id for product in products]
        reserved_map = await self.order_crud.get_reserved_quantities(product_ids)
        variants_by_product: dict[int, list[ProductVariant]] = defaultdict(list)
        variant_ids: list[int] = []
        if product_ids:
            rows = await self.session.scalars(
                select(ProductVariant).where(ProductVariant.product_id.in_(product_ids))
            )
            for variant in rows.all():
                variants_by_product[variant.product_id].append(variant)
                variant_ids.append(variant.id)
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        for product in products:
            product_variants = variants_by_product.get(product.id, [])
            for variant in product_variants:
                net = variant_available_qty(
                    int(variant.inventory_quantity or 0),
                    variant_reserved_map.get(variant.id, 0),
                    available=bool(variant.available),
                )
                setattr(variant, "available_quantity", net)
            qty = product_display_available_stock(
                product,
                reserved_map.get(product.id, 0),
                variants_by_product.get(product.id, []),
                variant_reserved_map,
            )
            setattr(product, "available_stock", qty)

    # Cover URL из колонок БД: /media, иначе CDN. Без Storage.exists.
    @staticmethod
    def _resolve_display_images(products: list[Product]) -> None:
        for product in products:
            product.image_url = resolve_product_cover_url(
                product.image_url, product.images
            )
