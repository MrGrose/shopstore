from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import resolve_request_user_id
from src.core.config import settings
from src.core.redis import async_redis
from src.deps import get_db
from src.models.user import User
from src.schemas.support import (
    SupportLinkableOrderSchema,
    SupportMessageCreateSchema,
    SupportTicketCreateSchema,
    SupportTicketDetailSchema,
    SupportTicketListPageSchema,
)
from src.services.support import SupportRateLimiter, SupportService

router = APIRouter(prefix="/support", tags=["support"])


# Проверяет rate limit и пробрасывает 429 при превышении.
async def _assert_support_rate_limit(user_id: int, action: str) -> None:
    limiter = SupportRateLimiter(async_redis())
    try:
        await limiter.assert_action_allowed(user_id, action)
    except ValueError as exc:
        message = str(exc)
        if "Слишком много" in message or "Подождите" in message:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=message,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from exc


# Учитывает успешное действие в rate limit.
async def _record_support_rate_limit(user_id: int, action: str) -> None:
    await SupportRateLimiter(async_redis()).record_action(user_id, action)


# Собирает байты загруженных файлов; клиентское имя отбрасывается.
async def _read_upload_files(files: list[Any]) -> list[tuple[bytes, str]]:
    uploads: list[tuple[bytes, str]] = []
    for item in files:
        filename = str(getattr(item, "filename", None) or "").strip()
        if not filename:
            continue
        content = await item.read()
        uploads.append((content, str(getattr(item, "content_type", None) or "")))
    return uploads


# Разбирает JSON или multipart (body + files) для создания обращения.
async def _parse_ticket_create(
    request: Request,
) -> tuple[SupportTicketCreateSchema, list[tuple[bytes, str]]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        files = [item for item in form.getlist("files") if hasattr(item, "read")]
        uploads = await _read_upload_files(files)
        order_raw = form.get("order_id")
        order_id: int | None = None
        if order_raw not in (None, ""):
            try:
                order_id = int(str(order_raw))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Некорректный заказ",
                ) from exc
        try:
            payload = SupportTicketCreateSchema(
                topic=str(form.get("topic") or ""),
                body=str(form.get("body") or ""),
                order_id=order_id,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.errors(),
            ) from exc
        return payload, uploads
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный запрос",
        )
    try:
        return SupportTicketCreateSchema.model_validate(data), []
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc


# Разбирает JSON или multipart для нового сообщения.
async def _parse_ticket_message(
    request: Request,
) -> tuple[str, list[tuple[bytes, str]]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        files = [item for item in form.getlist("files") if hasattr(item, "read")]
        uploads = await _read_upload_files(files)
        return str(form.get("body") or ""), uploads
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный запрос",
        )
    try:
        payload = SupportMessageCreateSchema.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    return payload.body, []


# Список обращений текущего клиента.
@router.get("/tickets", response_model=SupportTicketListPageSchema)
async def list_my_support_tickets(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketListPageSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    size = page_size or settings.SUPPORT_TICKETS_PAGE_SIZE_DEFAULT
    return await SupportService(db).list_tickets_for_user(
        user_id,
        page=page,
        page_size=size,
    )


# Создаёт новое обращение (JSON или multipart с фото).
@router.post(
    "/tickets",
    response_model=SupportTicketDetailSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_ticket(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SupportTicketDetailSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    await _assert_support_rate_limit(user_id, "create_ticket")
    payload, uploads = await _parse_ticket_create(request)
    try:
        detail = await SupportService(db).create_ticket(
            user_id, payload, uploads=uploads or None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await _record_support_rate_limit(user_id, "create_ticket")
    return detail


# Детали обращения с историей сообщений.
@router.get("/tickets/{ticket_id}", response_model=SupportTicketDetailSchema)
async def get_support_ticket(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
) -> SupportTicketDetailSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    detail = await SupportService(db).get_ticket_for_user(user_id, ticket_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return detail


# Новое сообщение клиента в обращении.
@router.post("/tickets/{ticket_id}/messages", response_model=SupportTicketDetailSchema)
async def add_support_ticket_message(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
) -> SupportTicketDetailSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    await _assert_support_rate_limit(user_id, "add_message")
    body, uploads = await _parse_ticket_message(request)
    try:
        detail = await SupportService(db).add_customer_message(
            user_id, ticket_id, body, uploads=uploads or None
        )
    except ValueError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "не найдено" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=message) from exc
    await _record_support_rate_limit(user_id, "add_message")
    return detail


# Закрывает обращение клиентом.
@router.post("/tickets/{ticket_id}/close", response_model=SupportTicketDetailSchema)
async def close_support_ticket(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
) -> SupportTicketDetailSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    try:
        return await SupportService(db).close_ticket(
            ticket_id=ticket_id,
            actor_user_id=user_id,
            closed_by="customer",
            is_staff=False,
        )
    except ValueError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "не найдено" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=message) from exc


# Отдаёт файл вложения owner/admin через Storage.read, без public URL.
@router.get("/tickets/{ticket_id}/attachments/{attachment_id}/file")
async def download_support_attachment(
    request: Request,
    ticket_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_id = await resolve_request_user_id(db=db, request=request)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    loaded = await SupportService(db).read_attachment_file(
        user, ticket_id, attachment_id
    )
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    data, media_type = loaded
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
        },
    )


# Заказы для optional-select при создании обращения.
@router.get("/linkable-orders", response_model=list[SupportLinkableOrderSchema])
async def list_linkable_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[SupportLinkableOrderSchema]:
    user_id = await resolve_request_user_id(db=db, request=request)
    return await SupportService(db).list_linkable_orders(user_id)
