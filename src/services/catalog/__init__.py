from typing import Any

__all__ = ["CatalogService", "CatalogStockService", "ProductImportService"]


# Отложенные импорты — без циклов с product_repo / order_service.
def __getattr__(name: str) -> Any:
    if name == "CatalogService":
        from src.services.catalog.read.service import CatalogService

        return CatalogService
    if name == "CatalogStockService":
        from src.services.catalog.stock.service import CatalogStockService

        return CatalogStockService
    if name == "ProductImportService":
        from src.services.catalog.importing.coordinator import ProductImportService

        return ProductImportService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
