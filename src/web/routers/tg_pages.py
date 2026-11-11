from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from src.web.storefront_spa import storefront_spa_response

router = APIRouter(tags=["web"])


# React SPA для Telegram Mini App.
@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def mini_app_page() -> Response:
    return storefront_spa_response()


# Nested /app/* — client-side routing React Router.
@router.get(
    "/app/{spa_path:path}", response_class=HTMLResponse, include_in_schema=False
)
async def mini_app_spa_nested(spa_path: str) -> Response:
    return storefront_spa_response()
