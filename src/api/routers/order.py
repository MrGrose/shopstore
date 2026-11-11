from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_admin_user, resolve_request_user_id
from src.deps import get_db
from src.models.user import User
from src.schemas.order import (
    CheckoutCreate,
    CheckoutPreviewRequest,
    CheckoutPreviewSchema,
    OrderSchema,
    PaymentInitSchema,
    PaymentStatusSchema,
    SupplierTrackingPublicSchema,
)
from src.services.orders.order_service import OrderService, TelegramRequiredError
from src.services.orders.supplier_tracking import SupplierTrackingService
from src.services.payment_service import PaymentService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=status.HTTP_410_GONE, include_in_schema=False)
# Legacy POST /orders закрыт; оформление — POST /orders/checkout.
async def create_order_legacy_removed() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Используйте POST /orders/checkout",
    )


# Оформляет заказ из корзины текущего пользователя.
@router.post(
    "/checkout/preview",
    response_model=CheckoutPreviewSchema,
    status_code=status.HTTP_200_OK,
    summary="Предпросмотр итогов checkout с промокодом",
)
async def preview_checkout(
    request: Request,
    payload: CheckoutPreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> CheckoutPreviewSchema:
    order_service = OrderService(db)
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    try:
        return await order_service.preview_checkout(
            user_id=resolved_user_id,
            promo_code=payload.promo_code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
            or "Промокод недействителен или не подходит к текущей корзине",
        ) from exc


@router.post(
    "/checkout",
    response_model=OrderSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Оформить заказ из корзины пользователя",
)
async def checkout_my_order(
    request: Request,
    payload: CheckoutCreate,
    db: AsyncSession = Depends(get_db),
) -> OrderSchema:
    order_service = OrderService(db)
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    try:
        order = await order_service.create_order(
            user_id=resolved_user_id,
            idempotency_key=None,
            delivery_payload=payload.delivery.model_dump(),
            promo_code=payload.promo_code,
            notification_channels=payload.notification_channels,
            notification_email=payload.notification_email,
        )
        return order
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except TelegramRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# Возвращает историю заказов текущего пользователя.
@router.get("/my", response_model=list[OrderSchema], summary="Мои заказы")
async def list_my_orders(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[OrderSchema]:
    order_service = OrderService(db)
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    return await order_service.list_orders(
        user_id=resolved_user_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{order_id}/tracking",
    response_model=SupplierTrackingPublicSchema,
    summary="Движение моего заказа",
)
async def get_my_order_tracking(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> SupplierTrackingPublicSchema:
    user_id = await resolve_request_user_id(db=db, request=request)
    try:
        return await SupplierTrackingService(db).public_tracking(order_id, user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


# Возвращает список заказов всех пользователей.
@router.get("/all", response_model=list[OrderSchema], summary="Все заказы")
async def list_all_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> list[OrderSchema]:
    order_service = OrderService(db)
    return await order_service.list_all_orders(page=page, page_size=page_size)


@router.post(
    "/{order_id}/payment/init",
    response_model=PaymentInitSchema,
    status_code=status.HTTP_200_OK,
    summary="Инициализировать оплату заказа и получить QR",
)
async def init_order_payment(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> PaymentInitSchema:
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    service = PaymentService(db)
    try:
        return await service.init_payment(order_id=order_id, user_id=resolved_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{order_id}/payment/status",
    response_model=PaymentStatusSchema,
    status_code=status.HTTP_200_OK,
    summary="Получить актуальный статус оплаты заказа",
)
async def get_order_payment_status(
    request: Request,
    order_id: int,
    payment_attempt_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusSchema:
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    service = PaymentService(db)
    try:
        return await service.get_payment_status(
            order_id=order_id,
            user_id=resolved_user_id,
            payment_attempt_id=payment_attempt_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{order_id}/cancel",
    response_model=OrderSchema,
    status_code=status.HTTP_200_OK,
    summary="Отменить свой неоплаченный заказ",
)
async def cancel_my_order(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> OrderSchema:
    order_service = OrderService(db)
    resolved_user_id = await resolve_request_user_id(db=db, request=request)
    try:
        return await order_service.cancel_order_by_customer(
            order_id=order_id,
            user_id=resolved_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
