# Пересчитывает catalog_in_stock и available_qty для всех товаров.
import asyncio

from src.repositories.session import async_session_maker
from src.services.catalog.read.caches import invalidate_if_catalog_boundary_changed
from src.services.catalog.stock.service import CatalogStockService


async def main() -> None:
    async with async_session_maker() as session:
        result = await CatalogStockService(session).refresh_all()
        await session.commit()
    invalidate_if_catalog_boundary_changed(
        result.boundary_flipped_ids,
        reason="admin_stock_boundary",
    )
    print(
        f"refreshed={result.refreshed} "
        f"boundary_flipped={len(result.boundary_flipped_ids)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
