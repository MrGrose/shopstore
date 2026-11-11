from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.middleware.cache_control import setup_cache_control


def test_cache_control_middleware_sets_public_header_on_products() -> None:
    app = FastAPI()
    setup_cache_control(app)

    @app.get("/products")
    async def products() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(app)
    response = client.get("/products")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == (
        "public, max-age=30, stale-while-revalidate=120"
    )


def test_cache_control_middleware_sets_no_store_on_cart() -> None:
    app = FastAPI()
    setup_cache_control(app)

    @app.get("/cart/me")
    async def cart_me() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(app)
    response = client.get("/cart/me")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_cache_control_middleware_preserves_existing_header() -> None:
    app = FastAPI()
    setup_cache_control(app)

    @app.get("/products")
    async def products() -> dict[str, str]:
        from starlette.responses import Response

        return Response(
            content='{"ok":"1"}',
            media_type="application/json",
            headers={"Cache-Control": "private, max-age=10"},
        )

    client = TestClient(app)
    response = client.get("/products")

    assert response.headers["Cache-Control"] == "private, max-age=10"
