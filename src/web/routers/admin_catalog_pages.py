import json
from decimal import Decimal, InvalidOperation
from typing import TypedDict
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models.user import User
from src.schemas.catalog import AdminBrandRow
from src.schemas.product import ProductCreate, ProductUpdate
from src.services.catalog import CatalogService
from src.services.catalog.export import ProductExportService, export_filename
from src.services.catalog.read.scope import (
    ADMIN_TREE_INCLUSION_LABELS_RU,
    ADMIN_TREE_REASON_LABELS_RU,
    ADMIN_TREE_SITE_LABELS_RU,
    CatalogScope,
    normalize_admin_catalog_tree,
)
from src.services.catalog.read.sort import normalize_admin_sort, normalize_sort_price
from src.services.product_service import ProductService
from src.utils.images import save_product_image
from src.utils.labels import translate_category_l2, translate_sport_type
from src.utils.pagination import pagination_page_window
from src.web.admin_context import admin_page_context
from src.web.admin_labels import ORDER_STATUS_LABELS
from src.web.admin_redirect import (
    catalog_return_from_form,
    products_redirect_from_catalog_return,
)
from src.web.deps import require_admin_user_page
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-catalog"],
    dependencies=[Depends(require_admin_user_page)],
)


# Контекст дерева TOTAL / INCLUDED / EXCLUDED / VISIBLE для админ-каталога.
def _admin_tree_context(
    inclusion: str | None,
    site: str | None,
    reason: str | None,
) -> dict[str, object]:
    tree = normalize_admin_catalog_tree(inclusion, site, reason)
    return {
        "admin_tree": tree,
        "inclusion": tree.inclusion,
        "site": tree.site,
        "reason": tree.reason,
        "tree_inclusion_views": {
            key: (ADMIN_TREE_INCLUSION_LABELS_RU[key], key)
            for key in ADMIN_TREE_INCLUSION_LABELS_RU
        },
        "tree_site_views": {
            key: (ADMIN_TREE_SITE_LABELS_RU[key], key)
            for key in ADMIN_TREE_SITE_LABELS_RU
        },
        "tree_reason_views": {
            key: (ADMIN_TREE_REASON_LABELS_RU[key], key)
            for key in ("supplier_limit", "zero_stock", "orphan", "mapping_excluded")
        },
        "tree_reason_labels": ADMIN_TREE_REASON_LABELS_RU,
        "show_tree_site_row": tree.inclusion != "excluded",
        "show_tree_reason_row": tree.inclusion != "excluded" and tree.site != "visible",
    }


def _admin_products_flash_trigger(message: str, *, error: bool = False) -> str:
    return json.dumps(
        {"adminProductsFlash": {"message": message, "error": error}},
        ensure_ascii=True,
    )


# Нормализует фильтр видимости бренда на вкладке «Бренды».
def _normalize_brand_visibility(raw: str | None) -> str:
    value = (raw or "all").strip().lower()
    if value == "visible":
        return "visible"
    if value == "hidden":
        return "hidden"
    return "all"


class AdminBrandsTabContext(TypedDict):
    brand_rows: list[AdminBrandRow]
    brand_total: int
    brand_products_total: int
    brand_summary: dict[str, int]
    brand_visibility: str
    search_q: str
    page: int
    total_pages: int


# Данные для partial/страницы вкладки «Бренды».
async def _admin_brands_tab_context(
    db: AsyncSession,
    q: str | None,
    visibility: str | None,
    page: int = 1,
) -> AdminBrandsTabContext:
    search_q = (q or "").strip()
    brand_visibility = _normalize_brand_visibility(visibility)
    svc = CatalogService(db)
    (
        brand_rows,
        brand_total,
        brand_products_total,
        total_pages,
        safe_page,
    ) = await svc.list_admin_brand_rows(
        q=search_q or None,
        visibility=brand_visibility,
        page=page,
    )
    return {
        "brand_rows": brand_rows,
        "brand_total": brand_total,
        "brand_products_total": brand_products_total,
        "brand_summary": await svc.get_admin_brands_summary(),
        "brand_visibility": brand_visibility,
        "search_q": search_q,
        "page": safe_page,
        "total_pages": total_pages,
    }


# Данные для partial/страницы вкладки «Массовые».
async def _admin_bulk_tab_context(
    db: AsyncSession,
    view: str,
    top: str,
    category: str | None,
) -> dict[str, object]:
    selected_category = (category or "").strip() or None
    scope = CatalogScope.from_admin_mode("in_catalog")
    svc = CatalogService(db)
    state = await svc.build_catalog_page_state(
        page=1,
        page_size=1,
        top=top,
        category=selected_category,
        scope=scope,
        include_admin_summary=False,
    )
    total = await svc.product_crud.count_by_top_category(top, selected_category)
    active = await svc.product_crud.count_by_top_category(
        top, selected_category, is_active=True
    )
    inactive = await svc.product_crud.count_by_top_category(
        top, selected_category, is_active=False
    )
    return {
        "state": state,
        "view": view,
        "bulk_preview": {
            "total": total,
            "active": active,
            "inactive": inactive,
        },
    }


# Извлекает ID товаров из формы.
def _product_ids_from_form(form: object) -> list[int]:
    ids: list[int] = []
    multi_items = getattr(form, "multi_items", None)
    if not callable(multi_items):
        return ids
    for key, value in multi_items():
        if key != "product_ids":
            continue
        try:
            ids.append(int(value))
        except ValueError:
            continue
    return ids


# Извлекает остатки вариантов из формы.
def _variant_stocks_from_form(form: object) -> dict[int, int]:
    stocks: dict[int, int] = {}
    multi_items = getattr(form, "multi_items", None)
    if not callable(multi_items):
        return stocks
    prefix = "variant_stock_"
    for key, value in multi_items():
        if not str(key).startswith(prefix):
            continue
        variant_id = int(str(key).removeprefix(prefix))
        stocks[variant_id] = max(0, int(value))
    return stocks


# Извлекает URL галереи из формы.
def _gallery_urls_from_form(form: object) -> list[str]:
    urls: list[str] = []
    multi_items = getattr(form, "multi_items", None)
    if not callable(multi_items):
        return urls
    for key, value in multi_items():
        if key != "gallery_urls":
            continue
        text = str(value or "").strip()
        if text:
            urls.append(text)
    return urls


# Парсит цену из поля формы админки.
def _optional_decimal(value: str) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Некорректное число: {value}") from exc


# Перенаправляет на страницу списка товаров.
def _catalog_products_redirect(
    catalog_return: dict[str, object],
    product_id: int | None = None,
    success: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return RedirectResponse(
        url=products_redirect_from_catalog_return(
            catalog_return,
            product_id=product_id,
            success=success,
            error=error,
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Отдаёт CSV-выгрузку всех товаров для админки.
@router.get(
    "/internal/admin/products/export.csv",
    include_in_schema=False,
)
async def admin_products_export_csv(
    db: AsyncSession = Depends(get_db),
) -> Response:
    body = await ProductExportService(db).build_csv_bytes()
    filename = export_filename()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Обрабатывает страницу списка товаров.
@router.get(
    "/internal/admin/products",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_products_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    view: str = Query(default="in_stock"),
    top: str = Query(default="All"),
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    sort_price: str | None = Query(default=None),
    tab: str = Query(default="list"),
    page: int = Query(default=1, ge=1),
    selected_id: int | None = Query(default=None, alias="id"),
    inclusion: str = Query(default="included"),
    site: str = Query(default="visible"),
    reason: str = Query(default="all"),
    visibility: str | None = Query(default=None),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    tree_ctx = _admin_tree_context(inclusion, site, reason)
    catalog_summary = await CatalogService(db).get_catalog_admin_summary(
        top_category=top,
        category=category,
    )
    admin_sort = normalize_admin_sort(sort, sort_price)
    brand_rows = None
    bulk_state = None
    bulk_preview = None
    brand_summary = None
    brand_visibility = "all"
    brand_total = 0
    brand_products_total = 0
    brand_total_pages = 1
    if tab == "brands":
        brands_ctx = await _admin_brands_tab_context(db, q, visibility, page)
        brand_rows = brands_ctx["brand_rows"]
        brand_summary = brands_ctx["brand_summary"]
        brand_visibility = brands_ctx["brand_visibility"]
        brand_total = brands_ctx["brand_total"]
        brand_products_total = brands_ctx["brand_products_total"]
        brand_total_pages = brands_ctx["total_pages"]
    elif tab == "bulk":
        bulk_ctx = await _admin_bulk_tab_context(db, view, top, category)
        bulk_state = bulk_ctx["state"]
        bulk_preview = bulk_ctx["bulk_preview"]
    return templates.TemplateResponse(
        request=request,
        name="site/admin/products.html",
        context=admin_page_context(
            request,
            admin_user,
            success=success,
            error=error,
            view=view,
            top=top,
            category=category or "",
            brand=brand or "",
            q=q or "",
            sort=admin_sort or "",
            sort_price=normalize_sort_price(sort_price) or "",
            tab=tab if tab in ("list", "bulk", "brands") else "list",
            page=page,
            selected_id=selected_id,
            catalog_summary=catalog_summary,
            brand_rows=brand_rows,
            brand_summary=brand_summary,
            brand_visibility=brand_visibility,
            brand_total=brand_total,
            brand_products_total=brand_products_total,
            total_pages=brand_total_pages if tab == "brands" else 1,
            bulk_state=bulk_state,
            bulk_preview=bulk_preview,
            state=bulk_state if tab == "bulk" else None,
            search_q=(q or "") if tab == "brands" else "",
            **tree_ctx,
        ),
    )


# Обрабатывает частичную страницу списка товаров.
@router.get(
    "/internal/admin/products/table",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_products_table_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    view: str = Query(default="in_stock"),
    top: str = Query(default="All"),
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    sort_price: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    selected_id: int | None = Query(default=None, alias="id"),
    inclusion: str = Query(default="included"),
    site: str = Query(default="visible"),
    reason: str = Query(default="all"),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    tree_ctx = _admin_tree_context(inclusion, site, reason)
    admin_sort = normalize_admin_sort(sort, sort_price)
    state = await CatalogService(db).build_catalog_page_state(
        page=page,
        page_size=page_size,
        top=top,
        category=category,
        brand=brand,
        q=q,
        sort=sort,
        sort_price=sort_price,
        scope=CatalogScope.from_admin_mode("in_catalog"),
        include_admin_summary=True,
        admin_tree=tree_ctx["admin_tree"],
    )
    total_pages = max(1, (state.total + page_size - 1) // page_size)
    pagination_pages = pagination_page_window(page, total_pages)
    catalog_return = {
        "view": view,
        "top": top,
        "page": page,
        "category": category,
        "brand": brand,
        "q": q,
        "sort": admin_sort,
        "sort_price": normalize_sort_price(sort_price),
        "inclusion": tree_ctx["inclusion"],
        "site": tree_ctx["site"],
        "reason": tree_ctx["reason"],
    }
    if selected_id is not None:
        catalog_return["selected_id"] = selected_id
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/products_table.html",
        context=admin_page_context(
            request,
            admin_user,
            state=state,
            view=view,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            pagination_pages=pagination_pages,
            selected_id=selected_id,
            brand=brand or "",
            search_q=q or "",
            sort=admin_sort or "",
            sort_price=normalize_sort_price(sort_price) or "",
            catalog_return=catalog_return,
            catalog_summary=state.catalog_summary,
            **tree_ctx,
        ),
    )


# HTMX-partial: вкладка массовых действий.
@router.get(
    "/internal/admin/products/bulk",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_products_bulk_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    view: str = Query(default="in_stock"),
    top: str = Query(default="All"),
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    bulk_ctx = await _admin_bulk_tab_context(db, view, top, category)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/products_bulk.html",
        context=admin_page_context(
            request,
            admin_user,
            tab="bulk",
            **bulk_ctx,
        ),
    )


# HTMX-partial: вкладка брендов.
@router.get(
    "/internal/admin/products/brands",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_products_brands_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    brands_ctx = await _admin_brands_tab_context(db, q, visibility, page)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/products_brands.html",
        context=admin_page_context(
            request,
            admin_user,
            tab="brands",
            **brands_ctx,
        ),
    )


# HTMX: переключение видимости бренда на витрине.
@router.post(
    "/internal/admin/products/brands/toggle",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_products_brand_toggle(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    brand: str = Form(""),
    visible: str = Form("false"),
    q: str | None = Form(default=None),
    visibility: str | None = Form(default=None),
    page: int = Form(default=1),
) -> HTMLResponse:
    is_visible = visible.strip().lower() in ("1", "true", "yes", "on")
    try:
        await CatalogService(db).set_brand_storefront_visible(brand, is_visible)
    except ValueError as exc:
        brands_ctx = await _admin_brands_tab_context(db, q, visibility, page)
        response = templates.TemplateResponse(
            request=request,
            name="site/admin/partials/products_brands.html",
            context=admin_page_context(
                request,
                admin_user,
                tab="brands",
                **brands_ctx,
            ),
        )
        response.headers["HX-Trigger"] = _admin_products_flash_trigger(
            str(exc), error=True
        )
        return response
    # После toggle остаёмся на «Все» — строка не пропадает из списка.
    brands_ctx = await _admin_brands_tab_context(db, q, "all", page)
    response = templates.TemplateResponse(
        request=request,
        name="site/admin/partials/products_brands.html",
        context=admin_page_context(
            request,
            admin_user,
            tab="brands",
            **brands_ctx,
        ),
    )
    response.headers["HX-Trigger"] = _admin_products_flash_trigger(
        (
            f"Бренд «{brand.strip()}» на витрине"
            if is_visible
            else f"Бренд «{brand.strip()}» скрыт с витрины"
        )
    )
    return response


# Обрабатывает частичную страницу детальной информации о товаре.
@router.get(
    "/internal/admin/products/{product_id}/detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_product_detail_partial(
    request: Request,
    product_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    view: str = Query(default="in_stock"),
    top: str = Query(default="All"),
    page: int = Query(default=1, ge=1),
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    sort_price: str | None = Query(default=None),
    error: str | None = Query(default=None),
    success: str | None = Query(default=None),
    inclusion: str = Query(default="included"),
    site: str = Query(default="visible"),
    reason: str = Query(default="all"),
) -> HTMLResponse:
    admin_sort = normalize_admin_sort(sort, sort_price)
    tree = normalize_admin_catalog_tree(inclusion, site, reason)
    catalog_return = {
        "view": view,
        "top": top,
        "page": page,
        "category": category,
        "brand": brand,
        "q": q,
        "sort": admin_sort,
        "sort_price": normalize_sort_price(sort_price),
        "inclusion": tree.inclusion,
        "site": tree.site,
        "reason": tree.reason,
    }
    product = await ProductService(db).get_product_admin_schema(product_id)
    if not product:
        return templates.TemplateResponse(
            request=request,
            name="site/admin/partials/product_detail.html",
            context=admin_page_context(
                request,
                admin_user,
                error="Товар не найден",
                product=None,
                catalog_return=catalog_return,
                tree_reason_labels=ADMIN_TREE_REASON_LABELS_RU,
            ),
        )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/product_detail.html",
        context=admin_page_context(
            request,
            admin_user,
            product=product,
            error=error,
            success=success,
            catalog_return=catalog_return,
            tree_reason_labels=ADMIN_TREE_REASON_LABELS_RU,
        ),
    )


# HTMX-partial: история заказов товара (вкладка «Заказы»).
@router.get(
    "/internal/admin/products/{product_id}/orders",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_product_orders_partial(
    request: Request,
    product_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    svc = ProductService(db)
    product = await svc.get_product(product_id)
    if not product:
        return HTMLResponse("Товар не найден", status_code=404)
    (
        order_rows,
        order_total,
        total_pages,
        safe_page,
    ) = await svc.get_product_order_history_page(product_id, page=page)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/product_orders_history.html",
        context=admin_page_context(
            request,
            admin_user,
            product_id=product_id,
            order_rows=order_rows,
            order_total=order_total,
            page=safe_page,
            total_pages=total_pages,
            status_labels=ORDER_STATUS_LABELS,
        ),
    )


# Обрабатывает страницу создания нового товара.
@router.get(
    "/internal/admin/products/new",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_product_new_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="site/admin/product_new.html",
        context=admin_page_context(request, admin_user, error=error),
    )


# Загружает изображение товара для ручного создания.
@router.post(
    "/internal/admin/products/upload-image",
    include_in_schema=False,
)
async def admin_product_upload_image(
    file: UploadFile = File(...),
) -> JSONResponse:
    url = await save_product_image(file)
    return JSONResponse({"url": url})


# Обрабатывает форму создания нового товара.
@router.post(
    "/internal/admin/products/create",
    include_in_schema=False,
)
async def admin_product_create_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(""),
    brand: str = Form(""),
    description: str = Form(""),
    product_url: str = Form(""),
    image_url: str = Form(""),
    sale_price: str = Form("0"),
    regular_price: str = Form("0"),
    stock: int = Form(0),
    is_active: bool = Form(False),
) -> RedirectResponse:
    form = await request.form()
    gallery_urls = _gallery_urls_from_form(form)
    try:
        payload = ProductCreate(
            title=title.strip(),
            brand=brand.strip() or "—",
            description=description.strip() or None,
            product_url=product_url.strip(),
            image_url=image_url.strip() or None,
            sale_price=_optional_decimal(sale_price) or Decimal("0"),
            regular_price=_optional_decimal(regular_price) or Decimal("0"),
            stock=max(0, stock),
            is_active=is_active,
        )
        if not payload.title:
            raise ValueError("Укажите название")
        if not payload.product_url:
            raise ValueError("Укажите ссылку на товар")
        product = await ProductService(db).create_product(
            payload,
            gallery_urls=gallery_urls,
        )
        return RedirectResponse(
            url=f"/internal/admin/products?id={product.id}&success=Товар+создан",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/internal/admin/products/new?error={quote(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


# Обрабатывает форму массового изменения статуса товаров.
@router.post(
    "/internal/admin/products/bulk",
    include_in_schema=False,
)
async def admin_products_bulk_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    action: str = Form(""),
) -> RedirectResponse:
    form = await request.form()
    catalog_return = catalog_return_from_form(form)
    product_ids = _product_ids_from_form(form)

    if action in ("activate_group", "deactivate_group"):
        group_top = str(form.get("group_top") or "All").strip() or "All"
        group_category = str(form.get("group_category") or "").strip() or None
        is_active = action == "activate_group"
        group_label = translate_sport_type(group_top)
        if group_category:
            group_label = f"{group_label} · {translate_category_l2(group_category)}"
        try:
            updated = await ProductService(db).bulk_set_active_by_top_category(
                group_top,
                is_active,
                category_l2=group_category,
            )
            if updated == 0:
                return _catalog_products_redirect(
                    catalog_return, success="Изменений не было"
                )
            verb = "На витрину" if is_active else "Сняты"
            return _catalog_products_redirect(
                catalog_return,
                success=f"{verb}: {updated} товаров ({group_label})",
            )
        except ValueError as exc:
            return _catalog_products_redirect(catalog_return, error=str(exc))

    if action not in ("activate", "deactivate"):
        return _catalog_products_redirect(catalog_return, error="Неизвестное действие")
    if not product_ids:
        return _catalog_products_redirect(
            catalog_return, error="Выберите хотя бы один товар"
        )

    is_active = action == "activate"
    try:
        updated = await ProductService(db).bulk_set_active(
            product_ids, is_active=is_active
        )
        if updated == 0:
            return _catalog_products_redirect(
                catalog_return, success="Изменений не было"
            )
        return _catalog_products_redirect(
            catalog_return, success=f"Обновлено товаров: {updated}"
        )
    except ValueError as exc:
        return _catalog_products_redirect(catalog_return, error=str(exc))


# Обрабатывает форму обновления информации о товаре.
@router.post(
    "/internal/admin/products/{product_id}/update",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_product_update_submit(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
    title: str = Form(""),
    brand: str = Form(""),
    description: str = Form(""),
    product_url: str = Form(""),
    image_url: str = Form(""),
    sale_price: str = Form(""),
    stock: int | None = Form(default=None),
    is_active: bool = Form(False),
) -> HTMLResponse:
    form = await request.form()
    # Извлекаем остатки вариантов из формы.
    variant_stocks = _variant_stocks_from_form(form)
    gallery_urls = _gallery_urls_from_form(form)
    # Извлекаем данные для возврата из каталога.
    catalog_return = catalog_return_from_form(form)

    try:
        payload_data: dict = {
            "title": title.strip() or None,
            "brand": brand.strip() or None,
            "description": description.strip() or None,
            "product_url": product_url.strip() or None,
            "image_url": image_url.strip() or None,
            "is_active": is_active,
        }
        sale_price_decimal = _optional_decimal(sale_price)
        if sale_price_decimal is not None:
            payload_data["sale_price"] = sale_price_decimal
        if variant_stocks:
            pass
        elif stock is not None:
            payload_data["stock"] = stock
        payload = ProductUpdate(**payload_data)
    except ValueError as exc:
        return _catalog_products_redirect(
            catalog_return, product_id=product_id, error=str(exc)
        )

    service = ProductService(db)
    try:
        await service.update_product(
            product_id,
            payload,
            variant_stocks=variant_stocks or None,
            gallery_urls=gallery_urls,
        )
        return _catalog_products_redirect(
            catalog_return, product_id=product_id, success="Сохранено"
        )
    except ValueError as exc:
        return _catalog_products_redirect(
            catalog_return, product_id=product_id, error=str(exc)
        )
