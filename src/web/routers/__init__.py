from src.web.routers.admin_auth_pages import router as admin_auth_pages_router
from src.web.routers.admin_catalog_pages import router as admin_catalog_pages_router
from src.web.routers.admin_customers_pages import router as admin_customers_pages_router
from src.web.routers.admin_finance_pages import router as admin_finance_pages_router
from src.web.routers.admin_ops_pages import router as admin_ops_pages_router
from src.web.routers.admin_orders_pages import router as admin_orders_pages_router
from src.web.routers.admin_pages import router as admin_pages_router
from src.web.routers.admin_pricing_pages import router as admin_pricing_pages_router
from src.web.routers.admin_support_pages import router as admin_support_pages_router
from src.web.routers.site_pages import router as site_pages_router
from src.web.routers.tg_pages import router as tg_pages_router

__all__ = [
    "admin_auth_pages_router",
    "admin_catalog_pages_router",
    "admin_customers_pages_router",
    "admin_finance_pages_router",
    "admin_ops_pages_router",
    "admin_orders_pages_router",
    "admin_pages_router",
    "admin_pricing_pages_router",
    "admin_support_pages_router",
    "site_pages_router",
    "tg_pages_router",
]
