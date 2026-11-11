from typing import Any

__all__ = ["CatalogStockService"]


# Отложенный импорт CatalogStockService.
def __getattr__(name: str) -> Any:
    if name == "CatalogStockService":
        from src.services.catalog.stock.service import CatalogStockService

        return CatalogStockService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
