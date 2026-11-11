from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.order import Order
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.services.catalog.stock.boundary import RefreshStockResult, storefront_visible
from src.utils.product_availability import product_display_available_stock

# Лимит bind-параметров asyncpg (32767); IN по product_id батчами.
_REFRESH_PRODUCTS_BATCH = 500


class CatalogStockService:
    # AsyncSession и order CRUD для пересчёта остатков.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)

    # Пересчитывает catalog_in_stock и available_qty для списка товаров.
    async def refresh_products(self, product_ids: list[int]) -> RefreshStockResult:
        ids = sorted({int(pid) for pid in product_ids if pid})
        if not ids:
            return RefreshStockResult()
        result = RefreshStockResult()
        for start in range(0, len(ids), _REFRESH_PRODUCTS_BATCH):
            chunk = ids[start : start + _REFRESH_PRODUCTS_BATCH]
            batch = await self._refresh_products_batch(chunk)
            result.refreshed += batch.refreshed
            result.boundary_flipped_ids.extend(batch.boundary_flipped_ids)
        return result

    # Один батч refresh_products (внутренний, под лимит asyncpg IN).
    async def _refresh_products_batch(self, ids: list[int]) -> RefreshStockResult:
        if not ids:
            return RefreshStockResult()

        rows = await self.session.scalars(
            select(Product)
            .where(Product.id.in_(ids))
            .options(selectinload(Product.variants))
        )
        products = list(rows.all())
        if not products:
            return RefreshStockResult()

        reserved_map = await self.order_crud.get_reserved_quantities(ids)
        variant_ids = [
            int(variant.id)
            for product in products
            for variant in (product.variants or [])
        ]
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )

        updates: list[dict[str, object]] = []
        boundary_flipped_ids: list[int] = []
        for product in products:
            was_visible = storefront_visible(
                bool(product.is_active),
                bool(product.catalog_in_stock),
            )
            variants = list(product.variants or [])
            qty = product_display_available_stock(
                product,
                int(reserved_map.get(product.id, 0)),
                variants,
                variant_reserved_map,
            )
            new_in_stock = qty > 0
            will_be_visible = storefront_visible(bool(product.is_active), new_in_stock)
            if was_visible != will_be_visible:
                boundary_flipped_ids.append(int(product.id))
            updates.append(
                {
                    "id": product.id,
                    "catalog_in_stock": new_in_stock,
                    "available_qty": qty,
                }
            )

        for row in updates:
            await self.session.execute(
                update(Product)
                .where(Product.id == row["id"])
                .values(
                    catalog_in_stock=row["catalog_in_stock"],
                    available_qty=row["available_qty"],
                )
            )
        await self.session.flush()
        return RefreshStockResult(
            refreshed=len(updates),
            boundary_flipped_ids=boundary_flipped_ids,
        )

    # Пересчитывает denorm-поля для всех активных товаров батчами.
    async def refresh_all(self, batch_size: int = 500) -> RefreshStockResult:
        result = RefreshStockResult()
        last_id = 0
        while True:
            ids = (
                await self.session.scalars(
                    select(Product.id)
                    .where(Product.id > last_id)
                    .order_by(Product.id.asc())
                    .limit(batch_size)
                )
            ).all()
            if not ids:
                break
            batch = await self._refresh_products_batch(list(ids))
            result.refreshed += batch.refreshed
            result.boundary_flipped_ids.extend(batch.boundary_flipped_ids)
            last_id = int(ids[-1])
        return result

    # Пересчитывает denorm-поля для товаров из заказа.
    async def refresh_for_order(self, order_id: int) -> RefreshStockResult:
        items = await self.order_crud.get_order_items(order_id)
        product_ids = [int(item.product_id) for item in items if item.product_id]
        return await self.refresh_products(product_ids)
