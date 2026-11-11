from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_admin_user
from src.deps import get_db
from src.models.user import User
from src.schemas.order import (
    AdminOrderItemsUpdate,
    AdminOrderListSchema,
    AdminOrderStatusUpdate,
    AdminOrderUpdate,
    OrderEventSchema,
    OrderSchema,
)
from src.services.orders.order_service import OrderService

router = APIRouter(
    prefix="/admin/orders",
    tags=["admin-orders"],
    dependencies=[Depends(require_admin_user)],
)


@router.get(
    "",
    response_model=AdminOrderListSchema,
    summary="Список заказов для админки",
)
async def list_admin_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> AdminOrderListSchema:
    service = OrderService(db)
    result = await service.list_admin_orders(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    return AdminOrderListSchema.model_validate(result)


@router.get(
    "/{order_id}",
    response_model=OrderSchema,
    summary="Детали заказа для админки",
)
async def get_admin_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> OrderSchema:
    service = OrderService(db)
    try:
        return await service.get_order(order_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заказ не найден",
        ) from exc


@router.get(
    "/{order_id}/events",
    response_model=list[OrderEventSchema],
    summary="История изменений заказа",
)
async def list_admin_order_events(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[OrderEventSchema]:
    service = OrderService(db)
    try:
        return await service.get_order_events(order_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заказ не найден",
        ) from exc


@router.post(
    "/{order_id}/status",
    response_model=OrderSchema,
    summary="Изменить статус заказа",
)
async def update_admin_order_status(
    order_id: int,
    payload: AdminOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin_user),
) -> OrderSchema:
    service = OrderService(db)
    try:
        order = await service.update_order_status(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
        return order
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{order_id}",
    response_model=OrderSchema,
    summary="Редактировать поля доставки заказа",
)
async def update_admin_order(
    order_id: int,
    payload: AdminOrderUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin_user),
) -> OrderSchema:
    service = OrderService(db)
    try:
        return await service.update_order_delivery(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{order_id}/items",
    response_model=OrderSchema,
    summary="Редактировать позиции заказа",
)
async def update_admin_order_items(
    order_id: int,
    payload: AdminOrderItemsUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin_user),
) -> OrderSchema:
    service = OrderService(db)
    try:
        return await service.update_order_items(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
