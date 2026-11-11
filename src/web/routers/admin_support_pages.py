import json

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi import status as http_status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.support_texts import SUPPORT_TOPIC_LABELS, list_support_reply_templates
from src.core.config import settings
from src.deps import get_db
from src.models.user import User
from src.services.support import SupportService
from src.utils.pagination import pagination_page_window
from src.web.admin_context import admin_page_context
from src.web.deps import require_admin_user_page
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-support"],
    dependencies=[Depends(require_admin_user_page)],
)

SUPPORT_STATUS_LABELS = {
    "waiting_staff": "Ожидает ответа",
    "waiting_customer": "Ответ отправлен",
    "closed": "Закрыто",
}


# Нормализует status-фильтр списка обращений.
def _normalize_support_status_filter(status: str | None) -> str | None:
    if not status or not str(status).strip():
        return None
    normalized = str(status).strip()
    if normalized not in SUPPORT_STATUS_LABELS:
        return None
    return normalized


# Редирект на страницу поддержки после POST.
def _support_redirect(
    ticket_id: int | None = None,
    order_id: int | None = None,
    page: int | None = None,
    status: str | None = None,
    success: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params: list[str] = []
    if ticket_id is not None:
        params.append(f"id={ticket_id}")
    if order_id is not None:
        params.append(f"order_id={order_id}")
    if status:
        params.append(f"status={status}")
    if page is not None and page > 1:
        params.append(f"page={page}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={error}")
    query = "&".join(params)
    url = "/internal/admin/support"
    if query:
        url = f"{url}?{query}"
    return RedirectResponse(url=url, status_code=http_status.HTTP_303_SEE_OTHER)


# Собирает байты фото из admin form; клиентское имя отбрасывается.
async def _admin_upload_tuples(files: list[UploadFile]) -> list[tuple[bytes, str]]:
    uploads: list[tuple[bytes, str]] = []
    for item in files:
        if not (item.filename or "").strip():
            continue
        uploads.append((await item.read(), item.content_type or ""))
    return uploads


# Страница обращений в поддержку.
@router.get(
    "/internal/admin/support",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_support_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    selected_id: int | None = Query(default=None, alias="id"),
    order_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=0, ge=0),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    service = SupportService(db)
    status_filter = _normalize_support_status_filter(status)
    detail = None
    customer = None
    reply_templates: list[dict[str, str]] = []
    reply_templates_json = "{}"
    tickets: list = []
    listed_total = 0
    listed_page = page
    listed_page_size = page_size or settings.SUPPORT_ADMIN_TICKETS_PAGE_SIZE_DEFAULT
    total_pages = 1
    support_status_counts: dict[str, int] = {}

    if selected_id:
        ctx = await service.get_admin_ticket_context(selected_id)
        if ctx:
            detail = ctx.get("ticket")
            customer = ctx.get("customer")
            topic = getattr(detail, "topic", None) if detail is not None else None
            reply_templates = list_support_reply_templates(topic)
            reply_templates_json = json.dumps(
                {row["id"]: row["body"] for row in reply_templates},
                ensure_ascii=False,
            )
    else:
        support_status_counts = await service.get_admin_status_counts(order_id=order_id)
        listed = await service.list_tickets_admin(
            order_id=order_id,
            status=status_filter,
            page=page,
            page_size=listed_page_size,
        )
        tickets = listed.items
        listed_total = listed.total
        listed_page = listed.page
        listed_page_size = listed.page_size
        total_pages = listed.total_pages

    return templates.TemplateResponse(
        request=request,
        name="site/admin/support.html",
        context=admin_page_context(
            request,
            admin_user,
            tickets=tickets,
            total=listed_total,
            page=listed_page,
            page_size=listed_page_size,
            total_pages=total_pages,
            pagination_pages=pagination_page_window(listed_page, total_pages),
            selected_id=selected_id,
            order_id_filter=order_id,
            status_filter=status_filter or "",
            support_status_counts=support_status_counts,
            detail=detail,
            customer=customer,
            topic_labels=SUPPORT_TOPIC_LABELS,
            status_labels=SUPPORT_STATUS_LABELS,
            reply_templates=reply_templates,
            reply_templates_json=reply_templates_json,
            success=success,
            error=error,
        ),
    )


# POST: ответ сотрудника клиенту.
@router.post(
    "/internal/admin/support/{ticket_id}/reply",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_support_reply_submit(
    ticket_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    page: int = Form(default=1),
) -> HTMLResponse:
    try:
        uploads = await _admin_upload_tuples(files)
        _detail, tg_ok = await SupportService(db).add_staff_reply(
            ticket_id=ticket_id,
            staff_user=admin_user,
            body=message,
            uploads=uploads or None,
        )
        if tg_ok is False:
            return _support_redirect(
                ticket_id=ticket_id,
                page=page,
                error="Ответ сохранён в ЛК, но Telegram клиенту не доставлен",
            )
        if tg_ok is None:
            return _support_redirect(
                ticket_id=ticket_id,
                page=page,
                success="Ответ сохранён и поставлен на отправку",
            )
        return _support_redirect(
            ticket_id=ticket_id,
            page=page,
            success="Ответ отправлен",
        )
    except ValueError as exc:
        return _support_redirect(ticket_id=ticket_id, page=page, error=str(exc))


# POST: закрытие обращения сотрудником.
@router.post(
    "/internal/admin/support/{ticket_id}/close",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_support_close_submit(
    ticket_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    page: int = Form(default=1),
) -> HTMLResponse:
    try:
        await SupportService(db).close_ticket(
            ticket_id=ticket_id,
            actor_user_id=admin_user.id,
            closed_by="staff",
            is_staff=True,
        )
        return _support_redirect(
            ticket_id=ticket_id,
            page=page,
            success="Обращение закрыто",
        )
    except ValueError as exc:
        return _support_redirect(ticket_id=ticket_id, page=page, error=str(exc))


# POST: безвозвратно удалить выбранные обращения.
@router.post(
    "/internal/admin/support/delete-selected",
    response_class=JSONResponse,
    include_in_schema=False,
)
async def admin_support_delete_selected(
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    ticket_ids: list[int] = Form(default=[]),
) -> JSONResponse:
    _ = admin_user
    try:
        deleted = await SupportService(db).admin_delete_tickets_by_ids(ticket_ids)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(
        {"deleted": deleted, "message": f"Удалено обращений: {deleted}"}
    )
