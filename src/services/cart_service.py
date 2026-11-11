from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.guest_cart import CartIdentity
from src.core.order_limits import (
    calculate_supplier_cost_eur,
    estimate_supplier_orders,
    is_supplier_unit_storefront_allowed,
    live_supplier_lines,
)
from src.models.cart import CartItem
from src.models.order import Order
from src.models.product import Product, ProductVariant
from src.repositories.cart_repo import CrudCart
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.schemas.cart import CartItemSchema, CartSchema
from src.services.cart_variant_resolve import resolve_cart_variant_id
from src.services.pricing_service import PricingService
from src.services.user_service import UserService
from src.utils.images import public_product_media_url
from src.utils.product_availability import pick_buyable_variant_id


class CartService:
    LEGACY_CENTS_THRESHOLD = Decimal("100000")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cart_crud = CrudCart(session=session, model=CartItem)
        self.product_crud = CrudProduct(session=session, model=Product)
        self.order_crud = CrudOrder(session=session, model=Order)
        self.pricing_service = PricingService(session=session)
        self.user_service = UserService(session=session)

    # Получает корзину пользователя.
    async def get_cart(self, user_id: int) -> CartSchema:
        return await self.get_cart_for_identity(CartIdentity(user_id=user_id))

    # Получает корзину для идентификатора.
    async def get_cart_for_identity(self, identity: CartIdentity) -> CartSchema:
        if identity.user_id is not None:
            await self.user_service.ensure_user(user_id=identity.user_id)
            items = await self.cart_crud.get_user_cart(user_id=identity.user_id)
        elif identity.guest_cart_id:
            items = await self.cart_crud.get_guest_cart(
                guest_cart_id=identity.guest_cart_id
            )
        else:
            items = []
        return await self._build_cart_schema(items)

    # Добавляет или обновляет позицию.
    async def add_or_update_item(
        self,
        user_id: int,
        product_id: int,
        quantity: int,
        variant_id: int | None = None,
    ) -> CartSchema:
        return await self.add_or_update_item_for_identity(
            CartIdentity(user_id=user_id),
            product_id=product_id,
            quantity=quantity,
            variant_id=variant_id,
        )

    # Добавляет или обновляет позицию для идентификатора.
    async def add_or_update_item_for_identity(
        self,
        identity: CartIdentity,
        product_id: int,
        quantity: int,
        variant_id: int | None = None,
    ) -> CartSchema:
        if identity.user_id is not None:
            await self.user_service.ensure_user(user_id=identity.user_id)
        product = await self.product_crud.get_by_id_with_related(product_id)
        if not product or not product.is_active:
            raise ValueError("Товар не найден или неактивен")
        if not is_supplier_unit_storefront_allowed(product.supplier_price_eur):
            raise ValueError("Товар не найден или неактивен")
        variant_id = resolve_cart_variant_id(product, variant_id)
        if product.variants:
            variant_ids = [variant.id for variant in product.variants]
            variant_reserved_map = (
                await self.order_crud.get_reserved_quantities_by_variant(variant_ids)
            )
            variant_id = pick_buyable_variant_id(
                list(product.variants),
                variant_reserved_map,
                variant_id,
            )
            if variant_id is None:
                raise ValueError("Недостаточно товара на складе")
        product, price_snapshot, available = await self._resolve_product_availability(
            product_id=product_id,
            variant_id=variant_id,
        )
        if quantity > available:
            raise ValueError("Недостаточно товара на складе")

        if identity.user_id is not None:
            await self.cart_crud.upsert_user_item(
                user_id=identity.user_id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                price_snapshot=price_snapshot,
            )
        elif identity.guest_cart_id:
            await self.cart_crud.upsert_guest_item(
                guest_cart_id=identity.guest_cart_id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                price_snapshot=price_snapshot,
            )
        else:
            raise ValueError("Не задана корзина")
        return await self.get_cart_for_identity(identity)

    # Удаляет позицию.
    async def remove_item(
        self, user_id: int, product_id: int, variant_id: int | None = None
    ) -> CartSchema:
        return await self.remove_item_for_identity(
            CartIdentity(user_id=user_id),
            product_id=product_id,
            variant_id=variant_id,
        )

    # Удаляет позицию для идентификатора.
    async def remove_item_for_identity(
        self,
        identity: CartIdentity,
        product_id: int,
        variant_id: int | None = None,
    ) -> CartSchema:
        if identity.user_id is not None:
            await self.cart_crud.remove_user_item(
                user_id=identity.user_id,
                product_id=product_id,
                variant_id=variant_id,
            )
        elif identity.guest_cart_id:
            await self.cart_crud.remove_guest_item(
                guest_cart_id=identity.guest_cart_id,
                product_id=product_id,
                variant_id=variant_id,
            )
        return await self.get_cart_for_identity(identity)

    # Объединяет корзину гостя в корзину пользователя.
    async def merge_guest_cart(self, guest_cart_id: str, user_id: int) -> None:
        guest_items = await self.cart_crud.get_guest_cart(guest_cart_id)
        if not guest_items:
            return
        await self.user_service.ensure_user(user_id=user_id)
        for guest_item in guest_items:
            existing = await self.cart_crud.get_user_item(
                user_id=user_id,
                product_id=guest_item.product_id,
                variant_id=guest_item.variant_id,
            )
            target_qty = guest_item.quantity + (existing.quantity if existing else 0)
            (
                product,
                price_snapshot,
                available,
            ) = await self._resolve_product_availability(
                product_id=guest_item.product_id,
                variant_id=guest_item.variant_id,
            )
            if not product or not product.is_active:
                continue
            if not is_supplier_unit_storefront_allowed(product.supplier_price_eur):
                continue
            capped_qty = min(target_qty, available)
            if capped_qty <= 0:
                if existing:
                    await self.cart_crud.remove_user_item(
                        user_id=user_id,
                        product_id=guest_item.product_id,
                        variant_id=guest_item.variant_id,
                        auto_commit=False,
                    )
                continue
            await self.cart_crud.upsert_user_item(
                user_id=user_id,
                product_id=guest_item.product_id,
                variant_id=guest_item.variant_id,
                quantity=capped_qty,
                price_snapshot=price_snapshot,
                auto_commit=False,
            )
        await self.cart_crud.clear_guest_cart(guest_cart_id, auto_commit=False)
        await self.session.commit()

    # Объединяет корзину другого пользователя в корзину survivor.
    async def merge_user_cart(self, donor_user_id: int, survivor_user_id: int) -> None:
        if donor_user_id == survivor_user_id:
            return
        donor_items = await self.cart_crud.get_user_cart(donor_user_id)
        if not donor_items:
            return
        await self.user_service.ensure_user(user_id=survivor_user_id)
        for donor_item in donor_items:
            existing = await self.cart_crud.get_user_item(
                user_id=survivor_user_id,
                product_id=donor_item.product_id,
                variant_id=donor_item.variant_id,
            )
            target_qty = donor_item.quantity + (existing.quantity if existing else 0)
            (
                product,
                price_snapshot,
                available,
            ) = await self._resolve_product_availability(
                product_id=donor_item.product_id,
                variant_id=donor_item.variant_id,
            )
            if not product or not product.is_active:
                continue
            if not is_supplier_unit_storefront_allowed(product.supplier_price_eur):
                continue
            capped_qty = min(target_qty, available)
            if capped_qty <= 0:
                if existing:
                    await self.cart_crud.remove_user_item(
                        user_id=survivor_user_id,
                        product_id=donor_item.product_id,
                        variant_id=donor_item.variant_id,
                        auto_commit=False,
                    )
                continue
            await self.cart_crud.upsert_user_item(
                user_id=survivor_user_id,
                product_id=donor_item.product_id,
                variant_id=donor_item.variant_id,
                quantity=capped_qty,
                price_snapshot=price_snapshot,
                auto_commit=False,
            )
        await self.cart_crud.clear_user_cart(donor_user_id, auto_commit=False)
        await self.session.commit()

    # Определяет доступность товара.
    async def _resolve_product_availability(
        self,
        product_id: int,
        variant_id: int | None,
    ) -> tuple[Product | None, Decimal, int]:
        product = await self.product_crud.get_by_id_with_related(product_id)
        if not product:
            return None, Decimal("0"), 0
        if variant_id is not None:
            selected_variant = next(
                (v for v in product.variants if v.id == variant_id),
                None,
            )
            if not selected_variant:
                raise ValueError("Вариант товара не найден")
            if not selected_variant.available:
                raise ValueError("Выбранный вариант недоступен")
            reserved = await self.order_crud.get_reserved_quantity(
                product_id=product_id,
                variant_id=variant_id,
            )
            available = max(0, int(selected_variant.inventory_quantity) - reserved)
        else:
            reserved_map = await self.order_crud.get_reserved_quantities([product_id])
            reserved = reserved_map.get(product_id, 0)
            available = max(0, int(product.stock) - reserved)
        return product, Decimal(product.sale_price), available

    # Строит схему корзины.
    async def _build_cart_schema(self, items: list[CartItem]) -> CartSchema:
        products_map = await self._get_products_map(items)
        variants_map = await self._get_variants_map(items)
        reserved_map = await self.order_crud.get_reserved_quantities(
            [item.product_id for item in items]
        )
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            [item.variant_id for item in items if item.variant_id is not None]
        )
        resolved_prices = {
            item.id: self._resolve_item_unit_price(item, products_map, variants_map)
            for item in items
        }
        total_amount = sum(
            [resolved_prices[item.id] * item.quantity for item in items],
            start=Decimal("0"),
        )
        pricing_settings = await self.pricing_service.get_settings()
        supplier_cost_eur = calculate_supplier_cost_eur(items, products_map)
        estimate = estimate_supplier_orders(
            supplier_cost_eur,
            Decimal(pricing_settings.delivery_fee_eur),
            len(items),
            supplier_lines=live_supplier_lines(items, products_map),
        )
        delivery_fee_amount = self.pricing_service.calculate_delivery_rub(
            delivery_fee_eur=estimate.client_shipping_eur,
            eur_rate=Decimal(pricing_settings.eur_rate),
        )
        return CartSchema(
            items=[
                self._build_item_schema(
                    item,
                    products_map,
                    reserved_map,
                    variants_map,
                    variant_reserved_map,
                    resolved_prices[item.id],
                )
                for item in items
            ],
            total_amount=total_amount,
            delivery_fee_amount=delivery_fee_amount,
            total_with_delivery_amount=total_amount + delivery_fee_amount,
            supplier_cost_eur=supplier_cost_eur,
        )

    # Нормализует цену варианта.
    @staticmethod
    def _normalize_variant_unit_price(value: Decimal) -> Decimal:
        if value >= CartService.LEGACY_CENTS_THRESHOLD:
            return value / Decimal("100")
        return value

    # Восстанавливает масштаб snapshot цены.
    @classmethod
    def _restore_snapshot_scale(
        cls, snapshot_price: Decimal, reference_price: Decimal | None
    ) -> Decimal:
        normalized_snapshot = cls._normalize_variant_unit_price(snapshot_price)
        if reference_price is None:
            return normalized_snapshot
        normalized_reference = cls._normalize_variant_unit_price(reference_price)
        maybe_scaled = normalized_snapshot * Decimal("100")
        if (
            normalized_snapshot > 0
            and normalized_snapshot < Decimal("1000")
            and normalized_reference >= Decimal("1000")
            and abs(maybe_scaled - normalized_reference) <= Decimal("1")
        ):
            return maybe_scaled
        return normalized_snapshot

    # Определяет цену позиции.
    def _resolve_item_unit_price(
        self,
        item: CartItem,
        products_map: dict[int, Product],
        variants_map: dict[int, ProductVariant],
    ) -> Decimal:
        product = products_map.get(item.product_id)
        reference_price = Decimal(product.sale_price) if product is not None else None
        if reference_price is not None:
            return self._normalize_variant_unit_price(reference_price)
        return self._restore_snapshot_scale(
            snapshot_price=Decimal(item.price_snapshot),
            reference_price=reference_price,
        )

    # Загружает товары для расчета цены.
    async def _get_products_map(self, items: list[CartItem]) -> dict[int, Product]:
        product_ids = [item.product_id for item in items]
        products = await self.product_crud.get_by_ids(product_ids)
        return {product.id: product for product in products}

    # Загружает варианты для расчета цены.
    async def _get_variants_map(
        self, items: list[CartItem]
    ) -> dict[int, ProductVariant]:
        variant_ids = [item.variant_id for item in items if item.variant_id is not None]
        if not variant_ids:
            return {}
        result = await self.session.scalars(
            select(ProductVariant).where(ProductVariant.id.in_(variant_ids))
        )
        variants = list(result.all())
        return {variant.id: variant for variant in variants}

    # Строит схему позиции корзины.
    def _build_item_schema(
        self,
        item: CartItem,
        products_map: dict[int, Product],
        reserved_map: dict[int, int],
        variants_map: dict[int, ProductVariant],
        variant_reserved_map: dict[int, int],
        resolved_unit_price: Decimal,
    ) -> CartItemSchema:
        product = products_map.get(item.product_id)
        variant = (
            variants_map.get(item.variant_id) if item.variant_id is not None else None
        )
        if variant:
            reserved = variant_reserved_map.get(variant.id, 0)
            available_stock = max(0, int(variant.inventory_quantity) - reserved)
        elif product:
            reserved = reserved_map.get(item.product_id, 0)
            available_stock = max(0, int(product.stock) - reserved)
        else:
            available_stock = 0
        if product is not None and not is_supplier_unit_storefront_allowed(
            product.supplier_price_eur
        ):
            available_stock = 0
        return CartItemSchema(
            id=item.id,
            user_id=item.user_id,
            product_id=item.product_id,
            variant_id=item.variant_id,
            quantity=item.quantity,
            price_snapshot=resolved_unit_price,
            product_title=product.title if product else None,
            product_brand=product.brand if product else None,
            product_image_url=(
                public_product_media_url(product.image_url) if product else None
            ),
            variant_sku=variant.sku if variant else None,
            variant_option1=variant.option1 if variant else None,
            variant_option2=variant.option2 if variant else None,
            variant_option3=variant.option3 if variant else None,
            available_stock=available_stock,
        )
