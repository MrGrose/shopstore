import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_admin_user, resolve_cart_identity
from src.core.guest_cart import apply_guest_cart_cookie
from src.deps import get_db
from src.models.user import User
from src.schemas.cart import CartItemCreate, CartItemUpdate, CartSchema
from src.services.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["cart"])
logger = logging.getLogger(__name__)


@router.get(
    "/by-user/{user_id}",
    response_model=CartSchema,
    summary="Получить корзину пользователя",
)
# Возвращает текущее состояние корзины пользователя.
async def get_cart(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> CartSchema:
    cart_service = CartService(db)
    return await cart_service.get_cart(user_id=user_id)


@router.post(
    "/by-user/{user_id}/items",
    response_model=CartSchema,
    status_code=status.HTTP_200_OK,
    summary="Добавить товар в корзину",
)
# Добавляет товар в корзину или обновляет количество.
async def add_item(
    user_id: int,
    payload: CartItemCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> CartSchema:
    cart_service = CartService(db)
    try:
        return await cart_service.add_or_update_item(
            user_id=user_id,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            quantity=payload.quantity,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при изменении корзины",
        )


@router.put(
    "/by-user/{user_id}/items/{product_id}",
    response_model=CartSchema,
    summary="Изменить количество товара в корзине",
)
# Изменяет количество товара в корзине.
async def update_item(
    user_id: int,
    product_id: int,
    payload: CartItemUpdate,
    variant_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> CartSchema:
    cart_service = CartService(db)
    if payload.quantity == 0:
        return await cart_service.remove_item(
            user_id=user_id,
            product_id=product_id,
            variant_id=variant_id,
        )
    try:
        return await cart_service.add_or_update_item(
            user_id=user_id,
            product_id=product_id,
            variant_id=variant_id,
            quantity=payload.quantity,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при изменении корзины",
        )


@router.delete(
    "/by-user/{user_id}/items/{product_id}",
    response_model=CartSchema,
    summary="Удалить товар из корзины",
)
# Удаляет товар из корзины пользователя.
async def delete_item(
    user_id: int,
    product_id: int,
    variant_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> CartSchema:
    cart_service = CartService(db)
    return await cart_service.remove_item(
        user_id=user_id,
        product_id=product_id,
        variant_id=variant_id,
    )


# Возвращает корзину текущего пользователя или гостя (cookie guest_cart_id).
@router.get("/me", response_model=CartSchema, summary="Получить мою корзину")
async def get_my_cart(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    identity, new_guest_id = await resolve_cart_identity(
        db=db,
        request=request,
    )
    apply_guest_cart_cookie(response, new_guest_id)
    return await CartService(db).get_cart_for_identity(identity)


# Добавляет товар в корзину текущего пользователя.
@router.post(
    "/me/items",
    response_model=CartSchema,
    summary="Добавить товар в мою корзину",
)
async def add_my_item(
    request: Request,
    response: Response,
    payload: CartItemCreate,
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    identity, new_guest_id = await resolve_cart_identity(
        db=db,
        request=request,
    )
    apply_guest_cart_cookie(response, new_guest_id)
    cart_service = CartService(db)
    try:
        return await cart_service.add_or_update_item_for_identity(
            identity=identity,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            quantity=payload.quantity,
        )
    except ValueError as exc:
        logger.warning(
            "Failed add to cart identity=%s product_id=%s qty=%s reason=%s",
            identity,
            payload.product_id,
            payload.quantity,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "Ошибка при изменении корзины",
        ) from exc


# Меняет количество товара в корзине текущего пользователя.
@router.put(
    "/me/items/{product_id}",
    response_model=CartSchema,
    summary="Изменить товар в моей корзине",
)
async def update_my_item(
    request: Request,
    response: Response,
    product_id: int,
    payload: CartItemUpdate,
    variant_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    identity, new_guest_id = await resolve_cart_identity(
        db=db,
        request=request,
    )
    apply_guest_cart_cookie(response, new_guest_id)
    cart_service = CartService(db)
    if payload.quantity == 0:
        return await cart_service.remove_item_for_identity(
            identity=identity,
            product_id=product_id,
            variant_id=variant_id,
        )
    try:
        return await cart_service.add_or_update_item_for_identity(
            identity=identity,
            product_id=product_id,
            variant_id=variant_id,
            quantity=payload.quantity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "Ошибка при изменении корзины",
        ) from exc


# Удаляет товар из корзины текущего пользователя.
@router.delete(
    "/me/items/{product_id}",
    response_model=CartSchema,
    summary="Удалить товар из моей корзины",
)
async def delete_my_item(
    request: Request,
    response: Response,
    product_id: int,
    variant_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    identity, new_guest_id = await resolve_cart_identity(
        db=db,
        request=request,
    )
    apply_guest_cart_cookie(response, new_guest_id)
    return await CartService(db).remove_item_for_identity(
        identity=identity,
        product_id=product_id,
        variant_id=variant_id,
    )
