from typing import Any

__all__ = ["CatalogService"]


# Отложенный импорт CatalogService (цикл с product_repo).
def __getattr__(name: str) -> Any:
    if name == "CatalogService":
        from src.services.catalog.read.service import CatalogService

        return CatalogService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
