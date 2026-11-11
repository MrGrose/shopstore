from typing import Any

__all__ = [
    "AdminNotificationService",
    "CartService",
    "CatalogService",
    "CustomerNotificationService",
    "OrderService",
    "ProductImportService",
    "ProductService",
    "UserService",
]


def __getattr__(name: str) -> Any:
    if name == "AdminNotificationService":
        from src.services.admin_notification_service import AdminNotificationService

        return AdminNotificationService
    if name == "CartService":
        from src.services.cart_service import CartService

        return CartService
    if name == "CatalogService":
        from src.services.catalog import CatalogService

        return CatalogService
    if name == "CustomerNotificationService":
        from src.services.customer_notification_service import (
            CustomerNotificationService,
        )

        return CustomerNotificationService
    if name == "OrderService":
        from src.services.orders.order_service import OrderService

        return OrderService
    if name == "ProductImportService":
        from src.services.catalog import ProductImportService

        return ProductImportService
    if name == "ProductService":
        from src.services.product_service import ProductService

        return ProductService
    if name == "UserService":
        from src.services.user_service import UserService

        return UserService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
