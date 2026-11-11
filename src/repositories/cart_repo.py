from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cart import CartItem
from src.repositories.base_repo import CRUDBase


class CrudCart(CRUDBase):
    def __init__(self, session: AsyncSession, model: type[CartItem]) -> None:
        self.model = model
        self.session = session

    # Финализирует транзакцию: commit или flush.
    async def _finalize(self, *, auto_commit: bool) -> None:
        if auto_commit:
            await self.session.commit()
        else:
            await self.session.flush()

    # Получает корзину пользователя.
    async def get_user_cart(self, user_id: int) -> list[CartItem]:
        result = await self.session.scalars(
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.id.asc())
        )
        return list(result.all())

    # Получает корзину гостя.
    async def get_guest_cart(self, guest_cart_id: str) -> list[CartItem]:
        result = await self.session.scalars(
            select(self.model)
            .where(self.model.guest_cart_id == guest_cart_id)
            .order_by(self.model.id.asc())
        )
        return list(result.all())

    # Получает позицию пользователя.
    async def get_user_item(
        self, user_id: int, product_id: int, variant_id: int | None = None
    ) -> CartItem | None:
        filters = [
            self.model.user_id == user_id,
            self.model.product_id == product_id,
            self.model.variant_id == variant_id,
        ]
        result = await self.session.scalars(select(self.model).where(*filters))
        return result.first()

    # Получает позицию гостя.
    async def get_guest_item(
        self,
        guest_cart_id: str,
        product_id: int,
        variant_id: int | None = None,
    ) -> CartItem | None:
        filters = [
            self.model.guest_cart_id == guest_cart_id,
            self.model.product_id == product_id,
            self.model.variant_id == variant_id,
        ]
        result = await self.session.scalars(select(self.model).where(*filters))
        return result.first()

    # Получает позицию.
    async def get_item(
        self, user_id: int, product_id: int, variant_id: int | None = None
    ) -> CartItem | None:
        return await self.get_user_item(user_id, product_id, variant_id)

    # Обновляет или создает позицию пользователя.
    async def upsert_user_item(
        self,
        user_id: int,
        product_id: int,
        quantity: int,
        price_snapshot: Decimal,
        variant_id: int | None = None,
        *,
        auto_commit: bool = True,
    ) -> CartItem:
        item = await self.get_user_item(
            user_id=user_id,
            product_id=product_id,
            variant_id=variant_id,
        )
        if item is not None:
            item.quantity = quantity
            item.price_snapshot = price_snapshot
        else:
            item = self.model(
                user_id=user_id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                price_snapshot=price_snapshot,
            )
            self.session.add(item)
        await self._finalize(auto_commit=auto_commit)
        if auto_commit:
            await self.session.refresh(item)
        return item

    # Обновляет или создает позицию гостя.
    async def upsert_guest_item(
        self,
        guest_cart_id: str,
        product_id: int,
        quantity: int,
        price_snapshot: Decimal,
        variant_id: int | None = None,
        *,
        auto_commit: bool = True,
    ) -> CartItem:
        item = await self.get_guest_item(
            guest_cart_id=guest_cart_id,
            product_id=product_id,
            variant_id=variant_id,
        )
        if item is not None:
            item.quantity = quantity
            item.price_snapshot = price_snapshot
        else:
            item = self.model(
                guest_cart_id=guest_cart_id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                price_snapshot=price_snapshot,
            )
            self.session.add(item)
        await self._finalize(auto_commit=auto_commit)
        if auto_commit:
            await self.session.refresh(item)
        return item

    # Обновляет или создает позицию.
    async def upsert_item(
        self,
        user_id: int,
        product_id: int,
        quantity: int,
        price_snapshot: Decimal,
        variant_id: int | None = None,
    ) -> CartItem:
        return await self.upsert_user_item(
            user_id=user_id,
            product_id=product_id,
            quantity=quantity,
            price_snapshot=price_snapshot,
            variant_id=variant_id,
            auto_commit=True,
        )

    # Удаляет позицию пользователя.
    async def remove_user_item(
        self,
        user_id: int,
        product_id: int,
        variant_id: int | None = None,
        *,
        auto_commit: bool = True,
    ) -> bool:
        item = await self.get_user_item(
            user_id=user_id,
            product_id=product_id,
            variant_id=variant_id,
        )
        if not item:
            return False
        await self.session.delete(item)
        await self._finalize(auto_commit=auto_commit)
        return True

    # Удаляет позицию гостя.
    async def remove_guest_item(
        self,
        guest_cart_id: str,
        product_id: int,
        variant_id: int | None = None,
        *,
        auto_commit: bool = True,
    ) -> bool:
        item = await self.get_guest_item(
            guest_cart_id=guest_cart_id,
            product_id=product_id,
            variant_id=variant_id,
        )
        if not item:
            return False
        await self.session.delete(item)
        await self._finalize(auto_commit=auto_commit)
        return True

    # Удаляет позицию.
    async def remove_item(
        self, user_id: int, product_id: int, variant_id: int | None = None
    ) -> bool:
        return await self.remove_user_item(
            user_id=user_id,
            product_id=product_id,
            variant_id=variant_id,
            auto_commit=True,
        )

    # Очищает корзину пользователя.
    async def clear_user_cart(self, user_id: int, *, auto_commit: bool = True) -> None:
        await self.session.execute(
            delete(self.model).where(self.model.user_id == user_id)
        )
        await self._finalize(auto_commit=auto_commit)

    # Очищает корзину гостя.
    async def clear_guest_cart(
        self, guest_cart_id: str, *, auto_commit: bool = True
    ) -> None:
        await self.session.execute(
            delete(self.model).where(self.model.guest_cart_id == guest_cart_id)
        )
        await self._finalize(auto_commit=auto_commit)
