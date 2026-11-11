from starlette.requests import Request

from src.models.user import User


def normalize_flash_message(value: object | None) -> str | None:
    # Если значение None или не является строкой, возвращаем None.
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def normalize_query_str(value: object | None, default: str | None = None) -> str | None:
    # Если значение является строкой и не пустое, возвращаем его.
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def admin_page_context(
    request: Request,
    admin_user: User,
    *,
    error: object | None = None,
    success: object | None = None,
    **extra: object,
) -> dict:
    # Создаем контекст страницы админки.
    ctx: dict = {
        "request": request,
        "admin_user": admin_user,
        "error": normalize_flash_message(error),
        "success": normalize_flash_message(success),
    }
    nav_orders_action = getattr(request.state, "admin_nav_orders_action", None)
    if nav_orders_action is not None:
        ctx["admin_nav_orders_action"] = nav_orders_action
    nav_support = getattr(request.state, "admin_nav_open_support", None)
    if nav_support is not None:
        ctx["admin_nav_open_support"] = nav_support
    # Обновляем контекст дополнительными данными.
    ctx.update(extra)
    return ctx
