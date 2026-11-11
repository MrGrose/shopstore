from urllib.parse import urlencode

from src.services.catalog.read.sort import normalize_admin_sort, normalize_sort_price


# Извлекает данные из формы для возврата из каталога.
def catalog_return_from_form(form: object) -> dict[str, object]:
    # Получаем метод get из формы.
    get = getattr(form, "get", None)
    if not callable(get):
        return {"view": "in_stock", "top": "All", "page": 1}
    # Получаем категорию, бренд и ID выбранного товара.
    category = str(get("return_category") or "").strip()
    brand = str(get("return_brand") or "").strip()
    search_q = str(get("return_q") or "").strip()
    sort_price = str(get("return_sort_price") or "").strip()
    admin_sort = str(get("return_sort") or "").strip()
    inclusion = str(get("return_inclusion") or "included").strip() or "included"
    site = str(get("return_site") or "visible").strip() or "visible"
    reason = str(get("return_reason") or "all").strip() or "all"
    selected_raw = str(get("return_selected_id") or "").strip()

    try:
        page = max(1, int(get("return_page") or 1))
    except ValueError:
        page = 1

    result: dict[str, object] = {
        "view": str(get("return_view") or "in_stock"),
        "top": str(get("return_top") or "All"),
        "page": page,
        "category": category or None,
        "brand": brand or None,
        "q": search_q or None,
        "sort": normalize_admin_sort(admin_sort or None, sort_price or None),
        "sort_price": normalize_sort_price(sort_price),
        "inclusion": inclusion,
        "site": site,
        "reason": reason,
    }
    tab = str(get("return_tab") or "").strip()
    if tab in ("list", "bulk", "brands"):
        result["tab"] = tab
    if selected_raw.isdigit():
        result["product_id"] = int(selected_raw)
    return result


# Формирует URL списка товаров.
def products_list_url(
    product_id: int | None = None,
    view: str = "in_stock",
    top: str = "All",
    page: int = 1,
    category: str | None = None,
    brand: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    sort_price: str | None = None,
    tab: str | None = None,
    inclusion: str | None = None,
    site: str | None = None,
    reason: str | None = None,
    success: str | None = None,
    error: str | None = None,
) -> str:
    query: dict[str, str] = {
        "view": view,
        "top": top,
        "page": str(max(1, page)),
    }
    if category:
        query["category"] = category
    if brand:
        query["brand"] = brand
    if q:
        query["q"] = q
    normalized_sort = normalize_admin_sort(sort, sort_price)
    if normalized_sort:
        query["sort"] = normalized_sort
    else:
        legacy = normalize_sort_price(sort_price)
        if legacy:
            query["sort_price"] = legacy
    if tab and tab != "list":
        query["tab"] = tab
    if inclusion and inclusion != "included":
        query["inclusion"] = inclusion
    if site and site != "visible":
        query["site"] = site
    if reason and reason != "all":
        query["reason"] = reason
    if product_id is not None:
        query["id"] = str(product_id)
    if success:
        query["success"] = success
    if error:
        query["error"] = error
    return f"/internal/admin/products?{urlencode(query)}"


# Формирует URL списка товаров из данных возврата из каталога.
def products_redirect_from_catalog_return(
    catalog_return: dict[str, object],
    product_id: int | None = None,
    success: str | None = None,
    error: str | None = None,
) -> str:
    cr = dict(catalog_return)
    pid = product_id if product_id is not None else cr.pop("product_id", None)
    cr.pop("selected_id", None)
    return products_list_url(
        product_id=int(pid) if pid is not None else None,  # type: ignore[call-overload]
        view=str(cr.get("view") or "in_stock"),
        top=str(cr.get("top") or "All"),
        page=int(cr.get("page") or 1),  # type: ignore[call-overload]
        category=cr.get("category"),  # type: ignore[arg-type]
        brand=cr.get("brand"),  # type: ignore[arg-type]
        q=cr.get("q"),  # type: ignore[arg-type]
        sort=cr.get("sort"),  # type: ignore[arg-type]
        sort_price=cr.get("sort_price"),  # type: ignore[arg-type]
        tab=str(cr.get("tab") or "") or None,
        inclusion=cr.get("inclusion"),  # type: ignore[arg-type]
        site=cr.get("site"),  # type: ignore[arg-type]
        reason=cr.get("reason"),  # type: ignore[arg-type]
        success=success,
        error=error,
    )


# Извлекает данные из формы для возврата из списка заказов.
def orders_return_from_form(form: object) -> dict[str, object]:
    get = getattr(form, "get", None)
    if not callable(get):
        return {
            "status": None,
            "page": 1,
            "q": None,
            "date_from": None,
            "date_to": None,
        }
    status = str(get("return_status") or "").strip()
    search_q = str(get("return_q") or "").strip()
    date_from = str(get("return_date_from") or "").strip()
    date_to = str(get("return_date_to") or "").strip()
    try:
        page = max(1, int(get("return_page") or 1))
    except ValueError:
        page = 1
    return {
        "status": status or None,
        "page": page,
        "q": search_q or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "paid_from": str(get("return_paid_from") or "").strip() or None,
        "paid_to": str(get("return_paid_to") or "").strip() or None,
    }


# Формирует URL списка заказов.
def orders_list_url(
    order_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    paid_from: str | None = None,
    paid_to: str | None = None,
    success: str | None = None,
    error: str | None = None,
    packing_preview: bool = False,
    packing_manual: bool = False,
    packing_add_to: int | None = None,
    anchor: str | None = None,
) -> str:
    query: dict[str, str] = {"page": str(max(1, page))}
    if q:
        query["q"] = q
    if status:
        query["status"] = status
    if date_from:
        query["date_from"] = date_from
    if date_to:
        query["date_to"] = date_to
    if paid_from:
        query["paid_from"] = paid_from
    if paid_to:
        query["paid_to"] = paid_to
    if order_id is not None:
        query["id"] = str(order_id)
    if success:
        query["success"] = success
    if error:
        query["error"] = error
    if packing_preview:
        query["packing_preview"] = "1"
    elif packing_manual:
        query["packing_manual"] = "1"
    if packing_add_to is not None:
        query["packing_add_to"] = str(int(packing_add_to))
    url = f"/internal/admin/orders?{urlencode(query)}"
    if anchor:
        url = f"{url}#{anchor}"
    return url


# Формирует URL страницы клиентов.
def customers_list_url(
    customer_id: int | None = None,
    page: int = 1,
    q: str | None = None,
    success: str | None = None,
    error: str | None = None,
) -> str:
    query: dict[str, str] = {"page": str(max(1, page))}
    if q:
        query["q"] = q
    if customer_id is not None:
        query["id"] = str(customer_id)
    if success:
        query["success"] = success
    if error:
        query["error"] = error
    return f"/internal/admin/customers?{urlencode(query)}"
