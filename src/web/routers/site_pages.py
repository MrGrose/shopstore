from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.core.config import settings
from src.core.stock_display import stock_display_client_dict
from src.schemas.catalog_labels import CatalogLabelsDictSchema
from src.services.catalog.shoe_size_guide import (
    brand_has_size_chart,
    get_brand_size_chart,
)
from src.utils.labels import catalog_labels_client_dict
from src.utils.urls import storefront_telegram_open_url, storefront_web_catalog_url
from src.web.storefront_legal import legal_fragment_context
from src.web.storefront_spa import storefront_spa_response
from src.web.templating import templates

_STOREFRONT_LEGAL_TEMPLATES: dict[str, str] = {
    "privacy": "site/legal/privacy.html",
    "terms": "site/legal/terms.html",
    "consent": "site/legal/consent.html",
    "returns": "site/legal/returns.html",
    "referral-rules": "site/legal/referral_rules.html",
}

router = APIRouter(tags=["web"])


@router.get("/", include_in_schema=False)
async def site_home() -> Response:
    return storefront_spa_response()


@router.get("/login", include_in_schema=False)
async def login_page() -> Response:
    return storefront_spa_response()


@router.get("/support", include_in_schema=False)
async def support_page() -> Response:
    return storefront_spa_response()


@router.get("/catalog", include_in_schema=False)
async def catalog_page() -> Response:
    return storefront_spa_response()


# Редирект короткой реферальной ссылки на главную с ?ref=.
@router.get("/ref/{alias}", include_in_schema=False)
async def referral_alias_redirect(alias: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/?ref={quote(alias)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/cart", include_in_schema=False)
async def site_cart_page() -> Response:
    return storefront_spa_response()


@router.get("/orders", include_in_schema=False)
async def site_orders_page() -> Response:
    return storefront_spa_response()


@router.get("/account", include_in_schema=False)
async def site_account_page() -> Response:
    return storefront_spa_response()


@router.get("/checkout", include_in_schema=False)
async def site_checkout_page() -> Response:
    return storefront_spa_response()


@router.get("/catalog/product/{product_id}", include_in_schema=False)
async def catalog_product_page(product_id: int) -> Response:
    return storefront_spa_response()


@router.get("/catalog/{spa_path:path}", include_in_schema=False)
async def catalog_spa_nested(spa_path: str) -> Response:
    return storefront_spa_response()


@router.get("/privacy", include_in_schema=False)
async def privacy_page() -> Response:
    return storefront_spa_response()


@router.get("/terms", include_in_schema=False)
async def terms_page() -> Response:
    return storefront_spa_response()


@router.get("/returns", include_in_schema=False)
async def returns_page() -> Response:
    return storefront_spa_response()


@router.get("/consent", include_in_schema=False)
async def consent_page() -> Response:
    return storefront_spa_response()


@router.get("/referral-rules", include_in_schema=False)
async def referral_rules_page() -> Response:
    return storefront_spa_response()


# HTML-фрагмент юр. документа для модалки React (контент из Jinja).
@router.get(
    "/storefront/legal/{slug}", response_class=HTMLResponse, include_in_schema=False
)
async def storefront_legal_fragment(request: Request, slug: str) -> HTMLResponse:
    template_name = _STOREFRONT_LEGAL_TEMPLATES.get(slug)
    if not template_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ctx = legal_fragment_context()
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=ctx,
    )


# HTML-фрагмент таблицы размеров обуви по бренду для модалки React.
@router.get(
    "/storefront/shoe-size-guide/{brand:path}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def storefront_shoe_size_guide_fragment(
    request: Request, brand: str
) -> HTMLResponse:
    chart = get_brand_size_chart(brand)
    if not chart:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return templates.TemplateResponse(
        request=request,
        name="site/size/base_size.html",
        context=chart,
    )


# Проверяет наличие таблицы размеров для бренда (каталог / PDP).
@router.get("/storefront/shoe-size-guide-available", include_in_schema=False)
async def storefront_shoe_size_guide_available(brand: str) -> dict[str, bool]:
    return {"available": brand_has_size_chart(brand)}


@router.get("/storefront/catalog-labels", include_in_schema=False)
async def storefront_catalog_labels() -> CatalogLabelsDictSchema:
    return CatalogLabelsDictSchema.model_validate(catalog_labels_client_dict())


@router.get("/storefront/stock-display", include_in_schema=False)
async def storefront_stock_display() -> dict[str, object]:
    payload = stock_display_client_dict(
        ok_from_qty=settings.STOCK_OK_FROM_QTY,
        low_min_qty=settings.STOCK_LOW_MIN_QTY,
        label_in_stock=settings.STOCK_LABEL_IN_STOCK,
        label_low=settings.STOCK_LABEL_LOW,
        label_last=settings.STOCK_LABEL_LAST,
        label_out=settings.STOCK_LABEL_OUT,
    )
    payload["shippingEstimateFallback"] = settings.SHIPPING_ESTIMATE_FALLBACK
    return payload


@router.get("/storefront/social", include_in_schema=False)
async def storefront_social_links() -> dict[str, str | bool]:
    bot = settings.TG_BOT_USERNAME.strip().lstrip("@")
    telegram_url = storefront_telegram_open_url(
        mini_app_url=settings.TG_MINI_APP_URL,
        bot_username=bot,
    )
    return {
        "telegram_url": telegram_url,
        "bot_username": bot,
        "vk_url": settings.PUBLIC_VK_URL.strip(),
        "web_catalog_url": storefront_web_catalog_url(settings.PUBLIC_SITE_URL),
        "phone_verification_code_enabled": settings.PHONE_VERIFICATION_CODE_ENABLED,
    }
