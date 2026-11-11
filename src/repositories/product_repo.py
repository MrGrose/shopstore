import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import (
    String,
    and_,
    cast,
    delete,
    exists,
    false,
    func,
    not_,
    or_,
    select,
    true,
    union,
    update,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from src.constants.storefront_mapping import (
    NODE_TYPE_CHIP,
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_MAPPING_ERROR,
    RESOLUTION_UNMAPPED,
    STOREFRONT_NAV_STATUS_EXCLUDED,
    STOREFRONT_NAV_STATUS_NOT_SELLABLE,
    STOREFRONT_NAV_STATUS_ORPHAN,
    STOREFRONT_NAV_STATUS_VISIBLE,
)
from src.core.order_limits import max_supplier_goods_eur
from src.core.stock_display import variant_buyable_sql_clause
from src.models.product import (
    CatalogHiddenBrand,
    Product,
    ProductFeature,
    ProductImage,
    ProductVariant,
)
from src.models.storefront_mapping import (
    ProductStorefrontPlacement,
    ProductStorefrontResolution,
    StorefrontNode,
)
from src.repositories.base_repo import CRUDBase
from src.repositories.session import async_session_maker
from src.services.catalog.importing.product_complete import (
    default_dom_max_attempts,
    enrichment_hold_sql_criterion,
)
from src.services.catalog.read.scope import (
    CATALOG_ALL_TOP_CATEGORY,
    CATALOG_TOP_ORDER,
    AdminCatalogTree,
    normalize_storefront_top_category,
)
from src.services.catalog.read.sort import CatalogAdminSort
from src.utils.datetime_fmt import utc_now_naive

_SKIP_VARIANT_OPTIONS = frozenset({"default title", "nosize"})
_COLOR_FEATURE_NAMES = ("Colour", "Color")


_CATALOG_SUBCATEGORY_NO_L3_TYPE = "_no_l3_"
# Максимальное значение для PostgreSQL INTEGER
_PG_INT_MAX = 2_147_483_647


@dataclass(frozen=True)
class _CatalogFacetCtx:
    filters: tuple[Any, ...]
    product_ids: Any


# Один facet-запрос в отдельной read-only сессии.
async def _run_catalog_facet_query(
    ctx: _CatalogFacetCtx,
    fetcher: Callable[["CrudProduct", _CatalogFacetCtx], Awaitable[Any]],
) -> Any:
    async with async_session_maker() as session:
        crud = CrudProduct(session=session, model=Product)
        return await fetcher(crud, ctx)


# Считает distinct product_id на raw color value через rows variant/feature.
def aggregate_product_color_facet_counts(
    rows: Iterable[tuple[int, str]],
) -> dict[str, int]:
    by_color: dict[str, set[int]] = {}
    for product_id, raw_value in rows:
        key = str(raw_value or "").strip()
        if not key:
            continue
        by_color.setdefault(key, set()).add(int(product_id))
    return {key: len(product_ids) for key, product_ids in by_color.items()}


# Нормализует строку поиска (обрезка, опциональный # перед id).
def normalize_product_search_query(q: str | None) -> str | None:
    if not q:
        return None
    text = q.strip().lstrip("#")
    return text or None


# id в PostgreSQL INTEGER — только положительные значения в int32.
def _parse_bounded_product_id(text: str) -> int | None:
    try:
        value = int(text)
    except ValueError:
        return None
    if value < 1 or value > _PG_INT_MAX:
        return None
    return value


# Точный поиск по числовому id (без фильтра спорта/категории).
def parse_product_id_query(q: str | None) -> int | None:
    text = normalize_product_search_query(q)
    if not text or not text.isdigit():
        return None
    return _parse_bounded_product_id(text)


# Штрихкод / external_id / SKU: цифры, но не id товара в PostgreSQL.
def is_product_external_code_query(q: str | None) -> bool:
    text = normalize_product_search_query(q)
    if not text or not text.isdigit():
        return False
    return _parse_bounded_product_id(text) is None


def product_external_code_filter(product: type[Product], q: str) -> ColumnElement[bool]:
    text = normalize_product_search_query(q)
    if not text:
        raise ValueError("empty search query")
    return or_(
        product.external_id == text,
        exists(
            select(1)
            .select_from(ProductVariant)
            .where(
                ProductVariant.product_id == product.id,
                ProductVariant.sku == text,
            )
        ),
    )


# Фильтр по title, brand, id и SKU вариантов (EXISTS — без дублей строк).
def product_search_filter(product: type[Product], q: str) -> ColumnElement[bool]:
    text = normalize_product_search_query(q)
    if not text:
        raise ValueError("Нет текста для поиска")
    term = f"%{text}%"
    clauses: list[ColumnElement[bool]] = [
        product.title.ilike(term),
        product.brand.ilike(term),
        product.external_id.ilike(term),
        cast(product.id, String).ilike(term),
        exists(
            select(1)
            .select_from(ProductVariant)
            .where(
                ProductVariant.product_id == product.id,
                ProductVariant.sku.is_not(None),
                ProductVariant.sku.ilike(term),
            )
        ),
    ]
    if text.isdigit():
        product_id = _parse_bounded_product_id(text)
        if product_id is not None:
            clauses.append(product.id == product_id)
    return or_(*clauses)


class CrudProduct(CRUDBase):
    # Инициализирует репозиторий продуктов.
    def __init__(self, session, model) -> None:
        self.model = model
        self.session = session

    # Собирает SQL-фильтры витрины: active, stock, кап TP и опционально NOT HOLD.
    def _catalog_base_filters(
        self,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list:
        if inactive_only:
            filters = [self.model.is_active.is_(False)]
        elif zero_stock_only:
            filters = [
                self.model.is_active.is_(True),
                self.model.catalog_in_stock.is_(False),
            ]
        else:
            filters = [self.model.is_active.is_(True)]
            if not include_out_of_stock:
                filters.append(self.model.catalog_in_stock.is_(True))
        self._append_supplier_unit_cap_filter(
            filters,
            exclude_over_supplier_unit_cap,
        )
        if require_complete:
            filters.append(
                not_(enrichment_hold_sql_criterion(default_dom_max_attempts()))
            )
        return filters

    # Скрывает на витрине unit дороже лимита товаров Supplier-Demo.
    def _append_supplier_unit_cap_filter(
        self,
        filters: list,
        exclude_over_supplier_unit_cap: bool,
    ) -> None:
        if not exclude_over_supplier_unit_cap:
            return
        cap = max_supplier_goods_eur()
        filters.append(
            or_(
                self.model.supplier_price_eur.is_(None),
                self.model.supplier_price_eur <= cap,
            )
        )

    # Бренд не в catalog_hidden_brands (пустой бренд проходит).
    def _brand_not_hidden_clause(self, hidden_brands: frozenset[str] | None):
        if not hidden_brands:
            return true()
        names = list(hidden_brands)
        return or_(
            self.model.brand.is_(None),
            func.trim(self.model.brand) == "",
            self.model.brand.notin_(names),
        )

    # Бренд явно скрыт catalog_hidden_brands.
    def _brand_hidden_clause(self, hidden_brands: frozenset[str] | None):
        if not hidden_brands:
            return false()
        names = list(hidden_brands)
        return and_(
            self.model.brand.is_not(None),
            func.trim(self.model.brand) != "",
            self.model.brand.in_(names),
        )

    # INCLUDED: is_active и бренд не скрыт.
    def _admin_included_clause(self, hidden_brands: frozenset[str] | None):
        return and_(
            self.model.is_active.is_(True),
            self._brand_not_hidden_clause(hidden_brands),
        )

    # EXCLUDED: снят или скрытый бренд.
    def _admin_excluded_clause(self, hidden_brands: frozenset[str] | None):
        return or_(
            self.model.is_active.is_(False),
            self._brand_hidden_clause(hidden_brands),
        )

    # Unit проходит Phase 1 cap (NULL закупка = 0, разрешена).
    def _supplier_cap_ok_clause(self):
        cap = max_supplier_goods_eur()
        return or_(
            self.model.supplier_price_eur.is_(None),
            self.model.supplier_price_eur <= cap,
        )

    # Unit дороже лимита TP.
    def _supplier_over_cap_clause(self):
        return self.model.supplier_price_eur > max_supplier_goods_eur()

    # Есть placement на active chip active release — тот же predicate, что listing.
    def _active_chip_placement_exists(self, release_id: int):
        return exists(
            select(1)
            .select_from(ProductStorefrontPlacement)
            .join(
                StorefrontNode,
                and_(
                    StorefrontNode.id == ProductStorefrontPlacement.storefront_node_id,
                    StorefrontNode.release_id == ProductStorefrontPlacement.release_id,
                ),
            )
            .where(
                ProductStorefrontPlacement.release_id == release_id,
                ProductStorefrontPlacement.product_id == self.model.id,
                StorefrontNode.node_type == NODE_TYPE_CHIP,
                StorefrontNode.active.is_(True),
            )
        )

    # Остаток + cap + placement (без inclusion).
    def _storefront_visible_rest_clause(self, release_id: int):
        return and_(
            self.model.catalog_in_stock.is_(True),
            self._supplier_cap_ok_clause(),
            self._active_chip_placement_exists(release_id),
        )

    # Реальный storefront predicate: INCLUDED + stock + cap + placement.
    def _storefront_visible_clause(
        self,
        hidden_brands: frozenset[str] | None,
        release_id: int,
    ):
        return and_(
            self._admin_included_clause(hidden_brands),
            self._storefront_visible_rest_clause(release_id),
        )

    # EXISTS resolution excluded в active release.
    def _resolution_status_exists(self, release_id: int, statuses: tuple[str, ...]):
        return exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == self.model.id,
                ProductStorefrontResolution.status.in_(statuses),
            )
        )

    # Есть любая resolution строка.
    def _resolution_exists(self, release_id: int):
        return exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == self.model.id,
            )
        )

    # SQL orphan listing/summary: same semantic as admin_product_tree_status.
    def _admin_orphan_clause(self, release_id: int):
        mapping_excluded = self._resolution_status_exists(
            release_id, (RESOLUTION_EXCLUDED,)
        )
        return and_(
            not_(mapping_excluded),
            or_(
                ~self._resolution_exists(release_id),
                self._resolution_status_exists(
                    release_id,
                    (RESOLUTION_UNMAPPED, RESOLUTION_MAPPING_ERROR),
                ),
                ~self._active_chip_placement_exists(release_id),
            ),
        )

    # Фильтры admin tree: inclusion / site / diagnostic reason.
    def _append_admin_tree_filters(
        self,
        filters: list,
        tree: AdminCatalogTree,
        hidden_brands: frozenset[str] | None,
        release_id: int,
    ) -> None:
        included = self._admin_included_clause(hidden_brands)
        excluded = self._admin_excluded_clause(hidden_brands)
        visible_rest = self._storefront_visible_rest_clause(release_id)
        if tree.inclusion == "excluded":
            filters.append(excluded)
            return
        needs_included = (
            tree.inclusion == "included"
            or tree.site in ("visible", "not_visible")
            or tree.reason != "all"
        )
        if needs_included:
            filters.append(included)
        if tree.site == "visible":
            filters.append(visible_rest)
            return
        if tree.site == "not_visible":
            filters.append(not_(visible_rest))
        if tree.reason == "supplier_limit":
            filters.append(self._supplier_over_cap_clause())
        elif tree.reason == "zero_stock":
            filters.append(self.model.catalog_in_stock.is_(False))
        elif tree.reason == "mapping_excluded":
            filters.append(
                self._resolution_status_exists(release_id, (RESOLUTION_EXCLUDED,))
            )
        elif tree.reason == "orphan":
            filters.append(self._admin_orphan_clause(release_id))

    @staticmethod
    def _append_hidden_brands_filter(
        filters: list,
        model: type[Product],
        hidden_brands: frozenset[str] | None,
    ) -> None:
        if not hidden_brands:
            return
        names = list(hidden_brands)
        filters.append(
            or_(
                model.brand.is_(None),
                func.trim(model.brand) == "",
                model.brand.notin_(names),
            )
        )

    # ORDER BY для admin sort или storefront sort_price.
    def _catalog_order_clause(
        self,
        sort_price: str | None = None,
        admin_sort: CatalogAdminSort | None = None,
    ):
        if admin_sort == "price_asc":
            return self.model.sale_price.asc().nulls_last()
        if admin_sort == "price_desc":
            return self.model.sale_price.desc().nulls_last()
        if admin_sort == "stock_asc":
            return self.model.available_qty.asc()
        if admin_sort == "stock_desc":
            return self.model.available_qty.desc()
        if admin_sort == "synced_asc":
            return self.model.catalog_synced_at.asc().nulls_last()
        if admin_sort == "synced_desc":
            return self.model.catalog_synced_at.desc().nulls_last()
        if admin_sort == "id_asc":
            return self.model.id.asc()
        if admin_sort == "id_desc":
            return self.model.id.desc()
        if sort_price == "asc":
            return self.model.sale_price.asc().nulls_last()
        if sort_price == "desc":
            return self.model.sale_price.desc().nulls_last()
        return self.model.id.desc()

    @staticmethod
    def _append_top_category_filter(
        filters: list,
        model: type[Product],
        top_category: str | None,
    ) -> None:
        top_category = normalize_storefront_top_category(top_category)
        if top_category == CATALOG_ALL_TOP_CATEGORY:
            # Витрина: только виды спорта из навигации (без Accessories / Training / …).
            filters.append(model.sport_type.in_(CATALOG_TOP_ORDER))
            return
        if top_category:
            filters.append(model.sport_type == top_category)

    def _color_exists_filter(self, color_key: str) -> ColumnElement[bool]:
        variant_color = exists(
            select(1)
            .select_from(ProductVariant)
            .where(
                ProductVariant.product_id == self.model.id,
                ProductVariant.option1.is_not(None),
                func.lower(ProductVariant.option1) == color_key,
                func.lower(ProductVariant.option1).notin_(_SKIP_VARIANT_OPTIONS),
                variant_buyable_sql_clause(ProductVariant),
            )
        )
        feature_color = exists(
            select(1)
            .select_from(ProductFeature)
            .where(
                ProductFeature.product_id == self.model.id,
                ProductFeature.name.in_(_COLOR_FEATURE_NAMES),
                func.lower(ProductFeature.value) == color_key,
            )
        )
        return or_(variant_color, feature_color)

    def _size_exists_filter(self, size_key: str) -> ColumnElement[bool]:
        size_on_option2 = func.lower(ProductVariant.option2) == size_key
        size_on_option1 = and_(
            or_(
                ProductVariant.option2.is_(None),
                func.trim(ProductVariant.option2) == "",
                func.lower(ProductVariant.option2).in_(_SKIP_VARIANT_OPTIONS),
            ),
            func.lower(ProductVariant.option1) == size_key,
            func.lower(ProductVariant.option1).notin_(_SKIP_VARIANT_OPTIONS),
        )
        return exists(
            select(1)
            .select_from(ProductVariant)
            .where(
                ProductVariant.product_id == self.model.id,
                or_(size_on_option2, size_on_option1),
                variant_buyable_sql_clause(ProductVariant),
            )
        )

    def _append_catalog_slice_filters(
        self,
        filters: list,
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
    ) -> None:
        product_id = parse_product_id_query(q)
        if product_id is not None:
            filters.append(self.model.id == product_id)
            return
        if is_product_external_code_query(q):
            search_q = normalize_product_search_query(q)
            if search_q:
                filters.append(product_external_code_filter(self.model, search_q))
            return
        self._append_top_category_filter(filters, self.model, top_category)
        search_q = normalize_product_search_query(q)
        if search_q:
            filters.append(product_search_filter(self.model, search_q))
        if category:
            filters.append(self.model.category_l2 == category)
        elif categories:
            filters.append(self.model.category_l2.in_(categories))
        if category_l3 == _CATALOG_SUBCATEGORY_NO_L3_TYPE:
            filters.append(
                or_(self.model.category_l3.is_(None), self.model.category_l3 == "")
            )
        elif category_l3:
            filters.append(self.model.category_l3 == category_l3)
        if brands:
            filters.append(self.model.brand.in_(brands))
        if genders:
            filters.append(self.model.gender.in_(genders))
        if price_min is not None:
            filters.append(self.model.sale_price >= price_min)
        if price_max is not None:
            filters.append(self.model.sale_price <= price_max)
        if colors:
            color_clauses = [
                self._color_exists_filter(color.strip().lower())
                for color in colors
                if color and color.strip()
            ]
            if color_clauses:
                filters.append(or_(*color_clauses))
        if sizes:
            size_clauses = [
                self._size_exists_filter(size.strip().lower())
                for size in sizes
                if size and size.strip()
            ]
            if size_clauses:
                filters.append(or_(*size_clauses))

    # Фильтр каталога через active release placements (chip nodes).
    def _append_storefront_placement_filters(
        self,
        filters: list,
        release_id: int,
        chip_node_ids: tuple[int, ...] | None,
        top_category: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        q: str | None = None,
    ) -> None:
        self._append_top_category_filter(filters, self.model, top_category)
        if chip_node_ids is None:
            filters.append(
                exists(
                    select(1)
                    .select_from(ProductStorefrontPlacement)
                    .join(
                        StorefrontNode,
                        and_(
                            StorefrontNode.id
                            == ProductStorefrontPlacement.storefront_node_id,
                            StorefrontNode.release_id
                            == ProductStorefrontPlacement.release_id,
                        ),
                    )
                    .where(
                        ProductStorefrontPlacement.release_id == release_id,
                        ProductStorefrontPlacement.product_id == self.model.id,
                        StorefrontNode.node_type == NODE_TYPE_CHIP,
                        StorefrontNode.active.is_(True),
                    )
                )
            )
        elif chip_node_ids:
            filters.append(
                exists(
                    select(1).where(
                        ProductStorefrontPlacement.release_id == release_id,
                        ProductStorefrontPlacement.product_id == self.model.id,
                        ProductStorefrontPlacement.storefront_node_id.in_(
                            chip_node_ids
                        ),
                    )
                )
            )
        else:
            filters.append(self.model.id == -1)
        product_id = parse_product_id_query(q)
        if product_id is not None:
            filters.append(self.model.id == product_id)
            return
        if is_product_external_code_query(q):
            search_q = normalize_product_search_query(q)
            if search_q:
                filters.append(product_external_code_filter(self.model, search_q))
            return
        search_q = normalize_product_search_query(q)
        if search_q:
            filters.append(product_search_filter(self.model, search_q))
        if brands:
            filters.append(self.model.brand.in_(brands))
        if genders:
            filters.append(self.model.gender.in_(genders))
        if price_min is not None:
            filters.append(self.model.sale_price >= price_min)
        if price_max is not None:
            filters.append(self.model.sale_price <= price_max)
        if colors:
            color_clauses = [
                self._color_exists_filter(color.strip().lower())
                for color in colors
                if color and color.strip()
            ]
            if color_clauses:
                filters.append(or_(*color_clauses))
        if sizes:
            size_clauses = [
                self._size_exists_filter(size.strip().lower())
                for size in sizes
                if size and size.strip()
            ]
            if size_clauses:
                filters.append(or_(*size_clauses))

    # Добавляет фильтр admin nav pills через resolutions active release.
    @staticmethod
    def _append_admin_mapping_nav_status_filter(
        filters: list,
        model: type[Product],
        release_id: int,
        nav_status: str | None,
    ) -> None:
        status = (nav_status or "").strip()
        if not status or status == "all":
            return
        resolution_exists = exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == model.id,
            )
        )
        mapped_exists = exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == model.id,
                ProductStorefrontResolution.status == RESOLUTION_MAPPED,
            )
        )
        excluded_exists = exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == model.id,
                ProductStorefrontResolution.status == RESOLUTION_EXCLUDED,
            )
        )
        orphan_exists = exists(
            select(1).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == model.id,
                ProductStorefrontResolution.status.in_(
                    (RESOLUTION_UNMAPPED, RESOLUTION_MAPPING_ERROR)
                ),
            )
        )
        if status == STOREFRONT_NAV_STATUS_VISIBLE:
            filters.append(mapped_exists)
            return
        if status == STOREFRONT_NAV_STATUS_EXCLUDED:
            filters.append(excluded_exists)
            return
        if status == STOREFRONT_NAV_STATUS_ORPHAN:
            filters.append(
                or_(
                    orphan_exists,
                    and_(~resolution_exists, model.is_active.is_(True)),
                )
            )
            return
        if status == STOREFRONT_NAV_STATUS_NOT_SELLABLE:
            filters.append(
                or_(model.is_active.is_(False), model.catalog_in_stock.is_(False))
            )

    # Возвращает страницу активных товаров и общее количество.
    async def paginate_products(
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
        hidden_brands_to_exclude: frozenset[str] | None = None,
        storefront_mapping_status: str | None = None,
        count_total: bool = True,
        load_product_images: bool = True,
        load_cover_image: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
        admin_mapping_release_id: int | None = None,
        admin_tree: AdminCatalogTree | None = None,
        admin_tree_release_id: int | None = None,
        admin_tree_hidden_brands: frozenset[str] | None = None,
    ) -> tuple[list, int | None, bool]:
        # Для витрины отдаем только товары с доступным остатком (stock − резерв),
        # чтобы пагинация совпадала с «В корзину» / «Нет в наличии» в карточках.
        if admin_tree is not None:
            if admin_tree_release_id is None:
                raise ValueError("admin_tree_release_id обязателен для admin tree")
            filters: list = []
            self._append_admin_tree_filters(
                filters,
                admin_tree,
                admin_tree_hidden_brands,
                admin_tree_release_id,
            )
        else:
            filters = self._catalog_base_filters(
                include_out_of_stock=include_out_of_stock,
                zero_stock_only=zero_stock_only,
                inactive_only=inactive_only,
                exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
                require_complete=require_complete,
            )
            self._append_hidden_brands_filter(
                filters, self.model, hidden_brands_to_exclude
            )
        if mapping_release_id is not None:
            self._append_storefront_placement_filters(
                filters,
                release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
                top_category=top_category,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
            )
        else:
            self._append_catalog_slice_filters(
                filters,
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
            )
        if admin_mapping_release_id is not None and admin_tree is None:
            self._append_admin_mapping_nav_status_filter(
                filters,
                self.model,
                admin_mapping_release_id,
                storefront_mapping_status,
            )
        order = self._catalog_order_clause(sort_price=sort_price, admin_sort=admin_sort)
        tie_break = (
            self.model.id.asc() if admin_sort == "id_asc" else self.model.id.desc()
        )
        fetch_limit = page_size if count_total else page_size + 1
        stmt = select(self.model).where(*filters).order_by(order, tie_break)
        if load_product_images:
            stmt = stmt.options(selectinload(self.model.images))
        elif load_cover_image:
            stmt = stmt.options(
                selectinload(self.model.images.and_(ProductImage.position == 0))
            )
        stmt = stmt.offset((page - 1) * page_size).limit(fetch_limit)

        items = list((await self.session.scalars(stmt)).all())
        if count_total:
            total = int(
                await self.session.scalar(
                    select(func.count(self.model.id)).where(*filters)
                )
                or 0
            )
            has_more = page * page_size < total
            return items, total, has_more

        has_more = len(items) > page_size
        return items[:page_size], None, has_more

    # Считает товары в срезе каталога (тот же фильтр, что у paginate_products).
    async def count_catalog_products(
        self,
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
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        hidden_brands_to_exclude: frozenset[str] | None = None,
        storefront_mapping_status: str | None = None,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> int:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        self._append_hidden_brands_filter(filters, self.model, hidden_brands_to_exclude)
        if mapping_release_id is not None:
            self._append_storefront_placement_filters(
                filters,
                release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
                top_category=top_category,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
            )
        else:
            self._append_catalog_slice_filters(
                filters,
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
            )
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(*filters)
        )
        return int(total or 0)

    # Возвращает список категорий второго уровня для фильтра каталога.
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
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(self.model.category_l2.is_not(None))
        self._append_top_category_filter(filters, self.model, top_category)
        if categories:
            filters.append(self.model.category_l2.in_(categories))
        stmt = (
            select(self.model.category_l2)
            .where(*filters)
            .distinct()
            .order_by(self.model.category_l2.asc())
        )
        rows = (await self.session.scalars(stmt)).all()
        return [str(row) for row in rows if row]

    # Возвращает список типов категорий для фильтра каталога.
    async def get_catalog_category_type_counts(
        self,
        top_category: str | None = None,
        categories: list[str] | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[dict[str, object]]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(self.model.category_l2.is_not(None))
        self._append_top_category_filter(filters, self.model, top_category)
        if categories:
            filters.append(self.model.category_l2.in_(categories))
        stmt = (
            select(self.model.category_l2, func.count(self.model.id))
            .where(*filters)
            .group_by(self.model.category_l2)
            .order_by(self.model.category_l2.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"value": str(row[0]), "count": int(row[1])} for row in rows if row[0]]

    # Возвращает список подтипов категорий для фильтра каталога.
    async def get_catalog_category_l3_counts(
        self,
        top_category: str | None = None,
        categories: list[str] | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[dict[str, object]]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(self.model.category_l3.is_not(None))
        filters.append(self.model.category_l3 != "")
        self._append_top_category_filter(filters, self.model, top_category)
        if categories:
            filters.append(self.model.category_l2.in_(categories))
        stmt = (
            select(self.model.category_l3, func.count(self.model.id))
            .where(*filters)
            .group_by(self.model.category_l3)
            .order_by(self.model.category_l3.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"value": str(row[0]), "count": int(row[1])} for row in rows if row[0]]

    # Возвращает counts по парам category_l2 + category_l3.
    async def get_catalog_category_l2_l3_counts(
        self,
        top_category: str | None = None,
        categories: list[str] | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[dict[str, object]]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(self.model.category_l2.is_not(None))
        filters.append(self.model.category_l3.is_not(None))
        filters.append(self.model.category_l3 != "")
        self._append_top_category_filter(filters, self.model, top_category)
        if categories:
            filters.append(self.model.category_l2.in_(categories))
        stmt = (
            select(
                self.model.category_l2,
                self.model.category_l3,
                func.count(self.model.id),
            )
            .where(*filters)
            .group_by(self.model.category_l2, self.model.category_l3)
            .order_by(self.model.category_l2.asc(), self.model.category_l3.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "category_l2": str(row[0]),
                "category_l3": str(row[1]),
                "count": int(row[2]),
            }
            for row in rows
            if row[0] and row[1]
        ]

    # Считает товары без category_l3, сгруппированные по category_l2.
    async def get_catalog_null_l3_counts_by_l2(
        self,
        top_category: str | None = None,
        categories: list[str] | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[dict[str, object]]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(
            or_(self.model.category_l3.is_(None), self.model.category_l3 == "")
        )
        self._append_top_category_filter(filters, self.model, top_category)
        if categories:
            filters.append(self.model.category_l2.in_(categories))
        stmt = (
            select(self.model.category_l2, func.count(self.model.id))
            .where(*filters)
            .group_by(self.model.category_l2)
            .order_by(func.count(self.model.id).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"value": str(row[0]), "count": int(row[1])} for row in rows if row[0]]

    # Возвращает top-категории (sport_type) с хотя бы одним товаром на витрине.
    async def get_top_categories_with_catalog_products(
        self,
        preferred_order: tuple[str, ...],
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[str]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        filters.append(self.model.sport_type.is_not(None))
        stmt = select(self.model.sport_type).where(*filters).distinct()
        rows = (await self.session.scalars(stmt)).all()
        present = {str(r) for r in rows if r}
        return [name for name in preferred_order if name in present]

    # Возвращает список брендов для текущего среза каталога.
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
        hidden_brands_to_exclude: frozenset[str] | None = None,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> list[str]:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        self._append_hidden_brands_filter(filters, self.model, hidden_brands_to_exclude)
        filters.append(self.model.brand.is_not(None))
        if mapping_release_id is not None:
            self._append_storefront_placement_filters(
                filters,
                release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
                top_category=top_category,
            )
        else:
            self._append_catalog_slice_filters(
                filters,
                top_category=top_category,
                category=category,
                categories=categories,
                category_l3=category_l3,
            )
        stmt = (
            select(self.model.brand)
            .where(*filters)
            .distinct()
            .order_by(self.model.brand.asc())
        )
        rows = (await self.session.scalars(stmt)).all()
        return [str(row) for row in rows if row]

    # Собирает общий контекст фильтров для параллельных facet-запросов.
    def _build_catalog_facet_context(
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
        hidden_brands_to_exclude: frozenset[str] | None = None,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> _CatalogFacetCtx:
        filters = self._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )
        if mapping_release_id is not None:
            self._append_storefront_placement_filters(
                filters,
                release_id=mapping_release_id,
                chip_node_ids=chip_node_ids,
                top_category=top_category,
                brands=brands,
                genders=genders,
                colors=colors,
                sizes=sizes,
                price_min=price_min,
                price_max=price_max,
                q=q,
            )
        else:
            self._append_catalog_slice_filters(
                filters,
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
            )
        self._append_hidden_brands_filter(filters, self.model, hidden_brands_to_exclude)
        filter_tuple = tuple(filters)
        product_ids = select(self.model.id).where(*filters).subquery()
        return _CatalogFacetCtx(filters=filter_tuple, product_ids=product_ids)

    def _build_catalog_price_bounds_context(
        self,
        *,
        top_category: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        category_l3: str | None = None,
        brands: list[str] | None = None,
        genders: list[str] | None = None,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
        q: str | None = None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> _CatalogFacetCtx:
        return self._build_catalog_facet_context(
            top_category=top_category,
            category=category,
            categories=categories,
            category_l3=category_l3,
            brands=brands,
            genders=genders,
            colors=colors,
            sizes=sizes,
            price_min=None,
            price_max=None,
            q=q,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
            mapping_release_id=mapping_release_id,
            chip_node_ids=chip_node_ids,
        )

    # Фасет: пол.
    async def _fetch_facet_genders(
        self,
        ctx: _CatalogFacetCtx,
    ) -> list[dict[str, Any]]:
        gender_rows = await self.session.execute(
            select(self.model.gender, func.count(self.model.id))
            .where(*ctx.filters, self.model.gender.is_not(None))
            .group_by(self.model.gender)
            .order_by(self.model.gender.asc())
        )
        return [
            {"value": str(row[0]), "count": int(row[1])}
            for row in gender_rows.all()
            if row[0]
        ]

    # Фасет: цвета из вариантов.
    async def _fetch_facet_colors(self, ctx: _CatalogFacetCtx) -> dict[str, int]:
        variant_rows = (
            select(
                Product.id.label("product_id"),
                func.trim(ProductVariant.option1).label("color_value"),
            )
            .select_from(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                Product.id.in_(select(ctx.product_ids.c.id)),
                ProductVariant.option1.is_not(None),
                func.trim(ProductVariant.option1) != "",
                func.lower(ProductVariant.option1).notin_(_SKIP_VARIANT_OPTIONS),
                variant_buyable_sql_clause(ProductVariant),
            )
            .distinct()
        )
        feature_rows = (
            select(
                Product.id.label("product_id"),
                func.trim(ProductFeature.value).label("color_value"),
            )
            .select_from(ProductFeature)
            .join(Product, Product.id == ProductFeature.product_id)
            .where(
                Product.id.in_(select(ctx.product_ids.c.id)),
                ProductFeature.name.in_(_COLOR_FEATURE_NAMES),
                ProductFeature.value.is_not(None),
                func.trim(ProductFeature.value) != "",
            )
            .distinct()
        )
        color_sources = union(variant_rows, feature_rows).subquery()
        color_rows = await self.session.execute(
            select(
                color_sources.c.color_value,
                func.count(func.distinct(color_sources.c.product_id)),
            )
            .group_by(color_sources.c.color_value)
            .order_by(color_sources.c.color_value.asc())
        )
        colors: dict[str, int] = {}
        for value, count in color_rows.all():
            key = str(value or "").strip()
            if not key:
                continue
            colors[key] = int(count)
        return colors

    # Фасет: размеры.
    async def _fetch_facet_sizes(self, ctx: _CatalogFacetCtx) -> list[dict[str, Any]]:
        size_rows = await self.session.execute(
            select(ProductVariant.option2, func.count(func.distinct(Product.id)))
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                Product.id.in_(select(ctx.product_ids.c.id)),
                ProductVariant.option2.is_not(None),
                func.trim(ProductVariant.option2) != "",
                func.lower(ProductVariant.option2).notin_(_SKIP_VARIANT_OPTIONS),
                variant_buyable_sql_clause(ProductVariant),
            )
            .group_by(ProductVariant.option2)
            .order_by(ProductVariant.option2.asc())
        )
        return [
            {"value": str(row[0]).strip(), "count": int(row[1])}
            for row in size_rows.all()
            if row[0] and str(row[0]).strip()
        ]

    # Фасет: бренды.
    async def _fetch_facet_brands(self, ctx: _CatalogFacetCtx) -> list[dict[str, Any]]:
        brand_rows = await self.session.execute(
            select(self.model.brand, func.count(self.model.id))
            .where(
                *ctx.filters,
                self.model.brand.is_not(None),
                func.trim(self.model.brand) != "",
            )
            .group_by(self.model.brand)
            .order_by(self.model.brand.asc())
        )
        return [
            {"value": str(row[0]).strip(), "count": int(row[1])}
            for row in brand_rows.all()
            if row[0] and str(row[0]).strip()
        ]

    # Фасет: диапазон цен.
    async def _fetch_facet_prices(self, ctx: _CatalogFacetCtx) -> tuple[Any, Any]:
        price_row = await self.session.execute(
            select(
                func.min(self.model.sale_price),
                func.max(self.model.sale_price),
            ).where(*ctx.filters, self.model.sale_price > 0)
        )
        return price_row.one()

    # Возвращает фасеты каталога (пол, цвет, размер, цена) для текущего среза.
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
        hidden_brands_to_exclude: frozenset[str] | None = None,
        mapping_release_id: int | None = None,
        chip_node_ids: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        ctx = self._build_catalog_facet_context(
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
            hidden_brands_to_exclude=hidden_brands_to_exclude,
            mapping_release_id=mapping_release_id,
            chip_node_ids=chip_node_ids,
        )
        include_key = (include or "all").strip().lower() or "all"
        want_all = include_key == "all"
        want_genders = want_all or "genders" in include_key
        want_prices = want_all or "prices" in include_key
        want_brands = want_all or "brands" in include_key
        want_colors = want_all or "colors" in include_key
        want_sizes = want_all or "sizes" in include_key

        genders_out: list[dict[str, Any]] = []
        merged_colors: dict[str, int] = {}
        sizes_out: list[dict[str, Any]] = []
        brands_out: list[dict[str, Any]] = []
        price_bounds: tuple[Any, Any] = (None, None)

        tasks: list[tuple[str, Awaitable[Any]]] = []
        if want_genders:
            tasks.append(
                (
                    "genders",
                    _run_catalog_facet_query(ctx, CrudProduct._fetch_facet_genders),
                )
            )
        if want_colors:
            tasks.append(
                (
                    "colors",
                    _run_catalog_facet_query(ctx, CrudProduct._fetch_facet_colors),
                )
            )
        if want_sizes:
            tasks.append(
                ("sizes", _run_catalog_facet_query(ctx, CrudProduct._fetch_facet_sizes))
            )
        if want_brands:
            tasks.append(
                (
                    "brands",
                    _run_catalog_facet_query(ctx, CrudProduct._fetch_facet_brands),
                )
            )
        if want_prices:
            # Slider bounds: same catalog slice, but without own price filter.
            price_bounds_ctx = (
                self._build_catalog_price_bounds_context(
                    top_category=top_category,
                    category=category,
                    categories=categories,
                    category_l3=category_l3,
                    brands=brands,
                    genders=genders,
                    colors=colors,
                    sizes=sizes,
                    q=q,
                    include_out_of_stock=include_out_of_stock,
                    zero_stock_only=zero_stock_only,
                    inactive_only=inactive_only,
                    mapping_release_id=mapping_release_id,
                    chip_node_ids=chip_node_ids,
                )
                if price_min is not None or price_max is not None
                else ctx
            )
            tasks.append(
                (
                    "prices",
                    _run_catalog_facet_query(
                        price_bounds_ctx, CrudProduct._fetch_facet_prices
                    ),
                )
            )

        if tasks:
            results = await asyncio.gather(*[coro for _, coro in tasks])
            for (name, _), value in zip(tasks, results, strict=True):
                if name == "genders":
                    genders_out = value
                elif name == "colors":
                    merged_colors = value
                elif name == "sizes":
                    sizes_out = value
                elif name == "brands":
                    brands_out = value
                elif name == "prices":
                    price_bounds = value

        price_min_val, price_max_val = price_bounds

        return {
            "brands": brands_out,
            "genders": genders_out,
            "colors": [
                {"value": key, "count": count}
                for key, count in sorted(
                    merged_colors.items(), key=lambda item: item[0].lower()
                )
            ],
            "sizes": sizes_out,
            "price_min": price_min_val,
            "price_max": price_max_val,
        }

    # Reconciliation + diagnostics админ-каталога: один SELECT / FILTER.
    async def get_catalog_admin_summary(
        self,
        top_category: str | None = None,
        category: str | None = None,
        hidden_brands: frozenset[str] | None = None,
        mapping_release_id: int | None = None,
    ) -> dict[str, int]:
        if mapping_release_id is None:
            raise ValueError("mapping_release_id обязателен для admin tree summary")
        scope: list = []
        self._append_top_category_filter(scope, self.model, top_category)
        cat = (category or "").strip()
        if cat:
            scope.append(self.model.category_l2 == cat)
        included = self._admin_included_clause(hidden_brands)
        excluded = self._admin_excluded_clause(hidden_brands)
        visible = self._storefront_visible_clause(hidden_brands, mapping_release_id)
        visible_rest = self._storefront_visible_rest_clause(mapping_release_id)
        not_visible = and_(included, not_(visible_rest))
        over_cap = self._supplier_over_cap_clause()
        mapping_excluded = self._resolution_status_exists(
            mapping_release_id, (RESOLUTION_EXCLUDED,)
        )
        orphan = self._admin_orphan_clause(mapping_release_id)
        stmt = select(
            func.count().label("total"),
            func.count().filter(included).label("included"),
            func.count().filter(excluded).label("excluded"),
            func.count().filter(visible).label("visible"),
            func.count().filter(not_visible).label("not_visible"),
            func.count()
            .filter(and_(included, over_cap))
            .label("reason_supplier_limit"),
            func.count()
            .filter(and_(included, self.model.catalog_in_stock.is_(False)))
            .label("reason_zero_stock"),
            func.count()
            .filter(and_(included, mapping_excluded))
            .label("reason_mapping_excluded"),
            func.count().filter(and_(included, orphan)).label("reason_orphan"),
        ).select_from(self.model)
        if scope:
            stmt = stmt.where(*scope)
        row = (await self.session.execute(stmt)).one()
        return {
            "total": int(row.total or 0),
            "included": int(row.included or 0),
            "excluded": int(row.excluded or 0),
            "visible": int(row.visible or 0),
            "not_visible": int(row.not_visible or 0),
            "reason_supplier_limit": int(row.reason_supplier_limit or 0),
            "reason_zero_stock": int(row.reason_zero_stock or 0),
            "reason_mapping_excluded": int(row.reason_mapping_excluded or 0),
            "reason_orphan": int(row.reason_orphan or 0),
        }

    # Product ids страницы, у которых есть active chip placement.
    async def product_ids_with_storefront_placement(
        self, release_id: int, product_ids: list[int]
    ) -> set[int]:
        if not product_ids:
            return set()
        stmt = (
            select(ProductStorefrontPlacement.product_id)
            .join(
                StorefrontNode,
                and_(
                    StorefrontNode.id == ProductStorefrontPlacement.storefront_node_id,
                    StorefrontNode.release_id == ProductStorefrontPlacement.release_id,
                ),
            )
            .where(
                ProductStorefrontPlacement.release_id == release_id,
                ProductStorefrontPlacement.product_id.in_(product_ids),
                StorefrontNode.node_type == NODE_TYPE_CHIP,
                StorefrontNode.active.is_(True),
            )
            .distinct()
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {int(pid) for pid in rows}

    # Массово включает/выключает товары по sport_type и опционально category_l2.
    async def bulk_set_active_by_top_category(
        self,
        top_category: str,
        is_active: bool,
        category_l2: str | None = None,
    ) -> list[int]:
        top = normalize_storefront_top_category(top_category) or top_category
        filters: list = [self.model.is_active.is_(not is_active)]
        if top and top != CATALOG_ALL_TOP_CATEGORY:
            filters.append(self.model.sport_type == top)
        cat = (category_l2 or "").strip()
        if cat:
            filters.append(self.model.category_l2 == cat)
        values: dict[str, object] = {"is_active": is_active}
        if is_active:
            values["deactivated_at"] = None
        else:
            values["deactivated_at"] = utc_now_naive()
        stmt = (
            update(self.model).where(*filters).values(**values).returning(self.model.id)
        )
        result = await self.session.scalars(stmt)
        affected_ids = [int(pid) for pid in result.all()]
        if affected_ids:
            await self.session.commit()
        return affected_ids

    # Считает товары по виду спорта и category_l2 (для превью массовых действий).
    async def count_by_top_category(
        self,
        top_category: str,
        category_l2: str | None = None,
        is_active: bool | None = None,
    ) -> int:
        top = normalize_storefront_top_category(top_category) or top_category
        filters: list = []
        if top and top != CATALOG_ALL_TOP_CATEGORY:
            filters.append(self.model.sport_type == top)
        cat = (category_l2 or "").strip()
        if cat:
            filters.append(self.model.category_l2 == cat)
        if is_active is not None:
            filters.append(self.model.is_active.is_(is_active))
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(*filters)
        )
        return int(total or 0)

    # Ищет товар по product_url.
    async def get_by_url(self, url: str) -> Product:
        result = await self.session.scalars(
            select(self.model).where(self.model.product_url == url)
        )
        return result.first()

    # Ищет товар по external_id.
    async def get_by_external_id(self, external_id: str) -> Product | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.external_id == external_id)
        )
        return result.first()

    # Возвращает товары по списку идентификаторов.
    async def get_by_ids(self, ids: list[int]) -> list[Product]:
        if not ids:
            return []
        result = await self.session.scalars(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result.all())

    # Возвращает товар по id вместе со связанными данными карточки.
    async def get_by_id_with_related(self, product_id: int) -> Product | None:
        stmt = (
            select(self.model)
            .where(self.model.id == product_id)
            .options(
                selectinload(self.model.images),
                selectinload(self.model.features),
                selectinload(self.model.variants),
            )
        )
        result = await self.session.scalars(stmt)
        return result.first()

    # Ищет товар по product_url вместе со связанными данными карточки.
    async def get_by_url_with_related(self, url: str) -> Product | None:
        stmt = (
            select(self.model)
            .where(self.model.product_url == url)
            .options(
                selectinload(self.model.images),
                selectinload(self.model.features),
                selectinload(self.model.variants),
            )
        )
        result = await self.session.scalars(stmt)
        return result.first()

    # Ищет товар по external_id вместе со связанными данными карточки.
    async def get_by_external_id_with_related(self, external_id: str) -> Product | None:
        stmt = (
            select(self.model)
            .where(self.model.external_id == external_id)
            .options(
                selectinload(self.model.images),
                selectinload(self.model.features),
                selectinload(self.model.variants),
            )
        )
        result = await self.session.scalars(stmt)
        return result.first()

    # Возвращает активные товары выбранных top-категорий.
    async def list_active_by_top_categories(
        self, top_categories: set[str]
    ) -> list[Product]:
        if not top_categories:
            return []
        result = await self.session.scalars(
            select(self.model).where(
                self.model.is_active.is_(True),
                self.model.sport_type.in_(sorted(top_categories)),
            )
        )
        return list(result.all())

    # Список брендов с количеством SKU (для админ-вкладки).
    async def list_distinct_brands_with_counts(self) -> list[tuple[str, int]]:
        stmt = (
            select(self.model.brand, func.count(self.model.id))
            .where(
                self.model.brand.is_not(None),
                func.trim(self.model.brand) != "",
            )
            .group_by(self.model.brand)
            .order_by(self.model.brand.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(str(row[0]), int(row[1])) for row in rows if row[0]]

    # Имена брендов, скрытых с витрины.
    async def get_hidden_brand_names(self) -> list[str]:
        result = await self.session.scalars(
            select(CatalogHiddenBrand.brand).order_by(CatalogHiddenBrand.brand.asc())
        )
        return [str(row) for row in result.all() if row]

    # Показывает или скрывает бренд на витрине.
    async def set_brand_hidden(self, brand: str, hidden: bool) -> None:
        name = brand.strip()
        if not name:
            raise ValueError("Укажите бренд")
        if hidden:
            existing = await self.session.scalar(
                select(CatalogHiddenBrand.brand).where(CatalogHiddenBrand.brand == name)
            )
            if existing:
                return
            self.session.add(
                CatalogHiddenBrand(brand=name, created_at=datetime.now(UTC))
            )
            return
        await self.session.execute(
            delete(CatalogHiddenBrand).where(CatalogHiddenBrand.brand == name)
        )
