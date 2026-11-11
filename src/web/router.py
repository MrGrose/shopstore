from fastapi import APIRouter

from src.web.routers import (
    admin_auth_pages_router,
    admin_catalog_pages_router,
    admin_customers_pages_router,
    admin_finance_pages_router,
    admin_ops_pages_router,
    admin_orders_pages_router,
    admin_pages_router,
    admin_pricing_pages_router,
    admin_support_pages_router,
    site_pages_router,
    tg_pages_router,
)

router = APIRouter(tags=["web"])

router.include_router(tg_pages_router)
router.include_router(site_pages_router)
router.include_router(admin_auth_pages_router)
router.include_router(admin_ops_pages_router)
router.include_router(admin_orders_pages_router)
router.include_router(admin_finance_pages_router)
router.include_router(admin_catalog_pages_router)
router.include_router(admin_pricing_pages_router)
router.include_router(admin_customers_pages_router)
router.include_router(admin_support_pages_router)
router.include_router(admin_pages_router)
