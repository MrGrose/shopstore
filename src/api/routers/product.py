from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from src.api.deps import require_admin_user
from src.api.http_cache import build_product_etag
from src.core.cache import get_reference_ttl_cache, set_reference_ttl_cache
from src.deps import get_db
from src.jobs.queue import get_scraper_run_status
from src.models.user import User
from src.schemas.catalog import (
    CatalogFacetsSchema,
    CatalogProductCountSchema,
    CatalogProductMetaSchema,
)
from src.schemas.catalog_labels import (
    CatalogLabelSchema,
    CatalogLabelsDictSchema,
    CatalogNavigationSchema,
    CatalogSubCategorySchema,
    CatalogTaxonomySchema,
)
from src.schemas.product import (
    ProductCreate,
    ProductPublicCardSchema,
    ProductPublicListSchema,
    ProductPublicSchema,
    ProductSchema,
    ProductUpdate,
)
from src.schemas.scraper_status import ScraperRunStatusSchema
from src.services.catalog import CatalogService
from src.services.catalog.display.compat_params import StorefrontCompatParamError
from src.services.catalog.display.runtime import (
    CatalogQueryContext,
    require_active_release_id,
    resolve_catalog_query_context,
)
from src.services.catalog.read.scope import (
    CatalogReadFilters,
    CatalogScope,
    CatalogStockFilters,
    normalize_storefront_top_category,
    parse_facet_query_param,
)
from src.services.catalog.read.sort import normalize_sort_price
from src.services.product_service import ProductService
from src.utils.labels import (
    catalog_labels_client_dict,
    translate_category_l2,
    translate_sport_type,
)

router = APIRouter(tags=["products"])


def _storefront_stock_filters() -> CatalogStockFilters:
    # Stock-фильтры витрины (без exclude_hidden_brands).
    return CatalogScope.storefront_public().list_filter_kwargs()


def _storefront_catalog_read_filters() -> CatalogReadFilters:
    # Read-фильтры витрины: stock + exclude catalog_hidden_brands.
    return CatalogScope.storefront_public().catalog_read_kwargs()


# Преобразует ключи категорий в русские подписи.
def _to_catalog_labels(keys: list[str], translate) -> list[CatalogLabelSchema]:
    return [CatalogLabelSchema(key=key, label_ru=translate(key)) for key in keys if key]


# Разбирает параметр категорий.
def _parse_categories_param(categories: str | None) -> list[str] | None:
    if not categories or not categories.strip():
        return None
    parts = [part.strip() for part in categories.split(",") if part.strip()]
    return parts or None


# Разбирает параметр типа категории.
def _parse_category_type_param(
    category_type: str | None,
    legacy_type: str | None = None,
) -> str | None:
    value = (category_type or legacy_type or "").strip()
    return value or None


# Разбирает multi-value фильтры фасетов из query string.
def _parse_catalog_facet_filters(
    brand: list[str] | None,
    gender: list[str] | None,
    color: list[str] | None,
    size: list[str] | None,
) -> tuple[list[str] | None, list[str] | None, list[str] | None, list[str] | None]:
    return (
        parse_facet_query_param(brand, facet_key="brand"),
        parse_facet_query_param(gender, facet_key="gender"),
        parse_facet_query_param(color, facet_key="color"),
        parse_facet_query_param(size, facet_key="size"),
    )


# Разбирает include=core|options|all для частичной загрузки фасетов.
def _parse_facet_include(raw: str | None) -> str:
    value = (raw or "all").strip().lower()
    if not value or value == "all":
        return "all"
    parts = sorted({part.strip().lower() for part in value.split(",") if part.strip()})
    if not parts or parts == ["all"]:
        return "all"
    allowed = {"core", "options", "genders", "prices", "brands", "colors", "sizes"}
    normalized: set[str] = set()
    for part in parts:
        if part not in allowed:
            continue
        if part == "core":
            normalized.update(("genders", "prices"))
        elif part == "options":
            normalized.update(("brands", "colors", "sizes"))
        else:
            normalized.add(part)
    if not normalized:
        return "all"
    if normalized >= {"genders", "prices", "brands", "colors", "sizes"}:
        return "all"
    return "+".join(sorted(normalized))


# Единый резолвер catalog query для public endpoints.
async def _resolve_catalog_query(
    db: AsyncSession,
    top_category: str | None,
    section: str | None = None,
    node: str | None = None,
    sub: str | None = None,
    category_type: str | None = None,
    legacy_type: str | None = None,
    category: str | None = None,
    categories: str | None = None,
    category_l3: str | None = None,
) -> CatalogQueryContext:
    return await resolve_catalog_query_context(
        db,
        top_category=top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=legacy_type,
        category=category,
        categories=_parse_categories_param(categories),
        category_l3=category_l3,
    )


@router.get(
    "/products/catalog/import/status",
    response_model=ScraperRunStatusSchema,
    summary="Статус очередей scraper pipeline (import/finalize/dom)",
)
# Admin: фаза pipeline и счётчики очередей catalog_import/dom/finalize.
async def get_catalog_import_status(
    _admin: User = Depends(require_admin_user),
) -> ScraperRunStatusSchema:
    return ScraperRunStatusSchema.model_validate(get_scraper_run_status())


@router.get(
    "/catalog/labels",
    response_model=CatalogLabelsDictSchema,
    summary="Словари русских подписей категорий каталога",
)
async def get_catalog_labels() -> CatalogLabelsDictSchema:
    cached = get_reference_ttl_cache("catalog:labels")
    if cached is None:
        cached = catalog_labels_client_dict()
        set_reference_ttl_cache("catalog:labels", cached)
    return CatalogLabelsDictSchema.model_validate(cached)


@router.get(
    "/catalog/taxonomy",
    response_model=CatalogTaxonomySchema,
    summary="Статическая таксономия витрины (спорт → подкатегории → category_l2)",
)
async def get_catalog_taxonomy(
    db: AsyncSession = Depends(get_db),
) -> CatalogTaxonomySchema:
    data = await CatalogService(db).get_catalog_taxonomy_mapping()
    return CatalogTaxonomySchema.model_validate(data)


@router.get(
    "/catalog/navigation",
    response_model=CatalogNavigationSchema,
    summary="Навигация каталога: scope, крошки, подкатегории и canonical URL params",
)
# Возвращает resolved scope каталога, breadcrumbs и subcategories для витрины.
async def get_catalog_navigation(
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Slug section-узла mapping release"),
    node: str | None = Query(None, description="display_key или slug chip-узла"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (legacy, rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    db: AsyncSession = Depends(get_db),
) -> CatalogNavigationSchema:
    try:
        return await CatalogService(db).get_catalog_navigation(
            top_category=normalize_storefront_top_category(top_category)
            or top_category,
            section=section,
            node=node,
            sub=sub,
            category_type=category_type,
            legacy_type=type,
            **_storefront_stock_filters(),
        )
    except StorefrontCompatParamError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/products/top-categories",
    response_model=list[CatalogLabelSchema],
    summary="Получить top-категории каталога с товарами на витрине",
)
async def get_product_top_categories(
    db: AsyncSession = Depends(get_db),
) -> list[CatalogLabelSchema]:
    keys = await CatalogService(db).get_catalog_top_categories(
        **_storefront_stock_filters(),
    )
    return _to_catalog_labels(keys, translate_sport_type)


@router.get(
    "/products/top-category-counts",
    response_model=dict[str, int],
    summary="Число товаров в наличии по виду спорта (без подмены top)",
)
async def get_top_category_product_counts(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    return await CatalogService(db).get_top_category_product_counts_mapping(
        **_storefront_stock_filters(),
    )


@router.get(
    "/products/categories",
    response_model=list[CatalogLabelSchema],
    summary="Получить категории каталога",
)
async def get_product_categories(
    top_category: str = Query("Padel"),
    categories: str | None = Query(
        None, description="Ограничить category_l2 ключами группы (через запятую)"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CatalogLabelSchema]:
    keys = await CatalogService(db).get_catalog_categories(
        top_category=normalize_storefront_top_category(top_category) or top_category,
        categories=_parse_categories_param(categories),
        **_storefront_stock_filters(),
    )
    return _to_catalog_labels(keys, translate_category_l2)


@router.get(
    "/products/subcategories",
    response_model=list[CatalogSubCategorySchema],
    summary="Подкатегории витрины с типами товаров из каталога",
)
async def get_product_subcategories(
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Section node slug"),
    sub: str | None = Query(
        None,
        description="Подкатегория (rackets, apparel, …); без sub — только slug/label",
    ),
    locale: str = Query("ru", description="Локаль подписей (ключ кэша)"),
    db: AsyncSession = Depends(get_db),
) -> list[CatalogSubCategorySchema]:
    query = await _resolve_catalog_query(
        db,
        normalize_storefront_top_category(top_category) or top_category,
        section=section,
        sub=sub,
    )
    return await CatalogService(db).get_catalog_subcategories(
        query.top_category,
        sub_slug=sub or section,
        locale=locale,
        mapping_release_id=query.mapping_release_id,
        **_storefront_catalog_read_filters(),
    )


@router.get(
    "/products/count",
    response_model=CatalogProductCountSchema,
    summary="Число товаров в текущем срезе каталога (кэш Redis)",
)
async def get_product_count(
    response: Response,
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Section node slug"),
    node: str | None = Query(None, description="Chip display_key or slug"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    category: str | None = Query(None),
    categories: str | None = Query(
        None, description="Группа category_l2 через запятую (приоритет у category)"
    ),
    category_l3: str | None = Query(
        None, description="Подтип в category_l3 (напр. Beginner rackets для падела)"
    ),
    brand: list[str] | None = Query(None),
    gender: list[str] | None = Query(None),
    color: list[str] | None = Query(None),
    size: list[str] | None = Query(None),
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    q: str | None = Query(
        None, description="Поиск по названию, бренду, ID и SKU варианта"
    ),
    db: AsyncSession = Depends(get_db),
) -> CatalogProductCountSchema:
    query = await _resolve_catalog_query(
        db,
        normalize_storefront_top_category(top_category) or top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=type,
        category=category,
        categories=categories,
        category_l3=category_l3,
    )
    brands, genders, colors, sizes = _parse_catalog_facet_filters(
        brand, gender, color, size
    )
    total = await CatalogService(db).get_catalog_product_count(
        top_category=query.top_category,
        brands=brands,
        genders=genders,
        colors=colors,
        sizes=sizes,
        price_min=price_min,
        price_max=price_max,
        q=q.strip() if q and q.strip() else None,
        mapping_release_id=query.mapping_release_id,
        chip_node_ids=query.chip_node_ids,
        **_storefront_catalog_read_filters(),
    )
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</products/meta>; rel="successor-version"'
    return CatalogProductCountSchema(total=total)


@router.get(
    "/products/facets",
    response_model=CatalogFacetsSchema,
    summary="Фасеты каталога (пол, цвет, размер, цена) для текущего среза",
)
async def get_product_facets(
    response: Response,
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Section node slug"),
    node: str | None = Query(None, description="Chip display_key or slug"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    category: str | None = Query(None),
    categories: str | None = Query(
        None, description="Группа category_l2 через запятую (приоритет у category)"
    ),
    category_l3: str | None = Query(
        None, description="Подтип в category_l3 (напр. Beginner rackets для падела)"
    ),
    brand: list[str] | None = Query(None),
    gender: list[str] | None = Query(None),
    color: list[str] | None = Query(None),
    size: list[str] | None = Query(None),
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    q: str | None = Query(
        None, description="Поиск по названию, бренду, ID и SKU варианта"
    ),
    include: str | None = Query(
        None,
        description="Части фасетов: core (пол+цена), options (бренд/цвет/размер), all",
    ),
    db: AsyncSession = Depends(get_db),
) -> CatalogFacetsSchema:
    query = await _resolve_catalog_query(
        db,
        normalize_storefront_top_category(top_category) or top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=type,
        category=category,
        categories=categories,
        category_l3=category_l3,
    )
    brands, genders, colors, sizes = _parse_catalog_facet_filters(
        brand, gender, color, size
    )
    facets = await CatalogService(db).get_catalog_facets(
        top_category=query.top_category,
        brands=brands,
        genders=genders,
        colors=colors,
        sizes=sizes,
        price_min=price_min,
        price_max=price_max,
        q=q.strip() if q and q.strip() else None,
        include=_parse_facet_include(include),
        mapping_release_id=query.mapping_release_id,
        chip_node_ids=query.chip_node_ids,
        **_storefront_catalog_read_filters(),
    )
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</products/meta>; rel="successor-version"'
    return facets


@router.get(
    "/products/meta",
    response_model=CatalogProductMetaSchema,
    summary="Count и фасеты каталога одним запросом",
)
async def get_product_meta(
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Section node slug"),
    node: str | None = Query(None, description="Chip display_key or slug"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    category: str | None = Query(None),
    categories: str | None = Query(
        None, description="Группа category_l2 через запятую (приоритет у category)"
    ),
    category_l3: str | None = Query(
        None, description="Подтип в category_l3 (напр. Beginner rackets для падела)"
    ),
    brand: list[str] | None = Query(None),
    gender: list[str] | None = Query(None),
    color: list[str] | None = Query(None),
    size: list[str] | None = Query(None),
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    q: str | None = Query(
        None, description="Поиск по названию, бренду, ID и SKU варианта"
    ),
    include: str | None = Query(
        None,
        description="Части фасетов: core (пол+цена), options (бренд/цвет/размер), all",
    ),
    db: AsyncSession = Depends(get_db),
) -> CatalogProductMetaSchema:
    query = await _resolve_catalog_query(
        db,
        normalize_storefront_top_category(top_category) or top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=type,
        category=category,
        categories=categories,
        category_l3=category_l3,
    )
    brands, genders, colors, sizes = _parse_catalog_facet_filters(
        brand, gender, color, size
    )
    return await CatalogService(db).get_catalog_product_meta(
        top_category=query.top_category,
        brands=brands,
        genders=genders,
        colors=colors,
        sizes=sizes,
        price_min=price_min,
        price_max=price_max,
        q=q.strip() if q and q.strip() else None,
        include=_parse_facet_include(include),
        mapping_release_id=query.mapping_release_id,
        chip_node_ids=query.chip_node_ids,
        **_storefront_catalog_read_filters(),
    )


@router.get(
    "/products/brands",
    response_model=list[str],
    summary="Получить бренды каталога",
)
async def get_product_brands(
    top_category: str = Query("Padel"),
    section: str | None = Query(None, description="Section node slug"),
    node: str | None = Query(None, description="Chip display_key or slug"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    category: str | None = Query(None),
    categories: str | None = Query(
        None, description="Группа category_l2 через запятую (приоритет у category)"
    ),
    category_l3: str | None = Query(
        None, description="Подтип в category_l3 (напр. Beginner rackets для падела)"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    query = await _resolve_catalog_query(
        db,
        normalize_storefront_top_category(top_category) or top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=type,
        category=category,
        categories=categories,
        category_l3=category_l3,
    )
    return await CatalogService(db).get_catalog_brands(
        top_category=query.top_category,
        mapping_release_id=query.mapping_release_id,
        chip_node_ids=query.chip_node_ids,
        **_storefront_catalog_read_filters(),
    )


@router.get(
    "/products",
    response_model=ProductPublicListSchema,
    summary="Получение продуктов по странично",
)
async def get_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    section: str | None = Query(None, description="Section node slug"),
    node: str | None = Query(None, description="Chip display_key or slug"),
    sub: str | None = Query(
        None, description="Подкатегория витрины (rackets, apparel, …)"
    ),
    category_type: str | None = Query(None, description="Тип внутри подкатегории"),
    type: str | None = Query(None, include_in_schema=False),
    category: str | None = Query(None),
    categories: str | None = Query(
        None, description="Группа category_l2 через запятую (приоритет у category)"
    ),
    category_l3: str | None = Query(
        None, description="Подтип в category_l3 (напр. Beginner rackets для падела)"
    ),
    brand: list[str] | None = Query(None),
    gender: list[str] | None = Query(None),
    color: list[str] | None = Query(None),
    size: list[str] | None = Query(None),
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    sort_price: Literal["asc", "desc"] | None = Query(
        None,
        description="Сортировка по цене: asc — от минимума, desc — от максимума",
    ),
    q: str | None = Query(
        None, description="Поиск по названию, бренду, ID и SKU варианта"
    ),
    top_category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ProductPublicListSchema:
    # Публичный список всегда витринный: роль, в том числе admin, лимит не снимает.
    scope = CatalogScope.storefront_public()
    catalog_read_kwargs = scope.catalog_read_kwargs()
    # Скрытые бренды не показываем на публичном API даже для admin-сессии.
    catalog_read_kwargs["exclude_hidden_brands"] = True
    brands, genders, colors, sizes = _parse_catalog_facet_filters(
        brand, gender, color, size
    )
    catalog = CatalogService(db)
    query = await _resolve_catalog_query(
        db,
        top_category,
        section=section,
        node=node,
        sub=sub,
        category_type=category_type,
        legacy_type=type,
        category=category,
        categories=categories,
        category_l3=category_l3,
    )
    items, total, has_more = await catalog.get_products_list(
        page=page,
        page_size=page_size,
        top_category=query.top_category,
        brands=brands,
        genders=genders,
        colors=colors,
        sizes=sizes,
        price_min=price_min,
        price_max=price_max,
        sort_price=normalize_sort_price(sort_price),
        q=q.strip() if q and q.strip() else None,
        resolve_local_images=True,
        count_total=False,
        load_product_images=True,
        load_cover_image=True,
        mapping_release_id=query.mapping_release_id,
        chip_node_ids=query.chip_node_ids,
        **catalog_read_kwargs,
    )
    return ProductPublicListSchema(
        items=[ProductPublicCardSchema.model_validate(row) for row in items],
        total=total,
        has_more=has_more,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/product/{id}",
    response_model=ProductPublicSchema,
    summary="Получить продукт по id",
)
async def get_poduct(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ProductPublicSchema | Response:
    product_svc = ProductService(db)
    product = await product_svc.get_product_for_storefront(id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Товар с id={id} не найден"
        )
    release_id = await require_active_release_id(db)
    etag = build_product_etag(product, release_id)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    schema = ProductPublicSchema.model_validate(product)
    return Response(
        content=schema.model_dump_json(),
        media_type="application/json",
        headers={"ETag": etag},
    )


@router.post(
    "/products",
    response_model=ProductSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Создать продукт",
)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> ProductSchema:
    product_svc = ProductService(db)
    try:
        product = await product_svc.create_product(payload)
        return ProductSchema.model_validate(product)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при создании продукта",
        )


@router.patch(
    "/product/{id}",
    response_model=ProductSchema,
    summary="Обновить продукт",
)
async def update_product(
    id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> ProductSchema:
    product_svc = ProductService(db)
    try:
        product = await product_svc.update_product(id, payload)
        return ProductSchema.model_validate(product)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при обновлении продукта",
        )


@router.delete(
    "/product/{id}",
    response_model=ProductSchema,
    summary="Изменить статус продукта на неактивный",
)
async def soft_delete_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> ProductSchema:
    product_svc = ProductService(db)
    try:
        product = await product_svc.soft_delete_product(id)
        return ProductSchema.model_validate(product)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при изменении статуса продукта",
        )


@router.delete(
    "/product/{id}/hard",
    response_model=ProductSchema,
    summary="Удалить продукт",
)
async def hard_delete_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> ProductSchema:
    product_svc = ProductService(db)
    try:
        product = await product_svc.hard_delete_product(id)
        return ProductSchema.model_validate(product)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
