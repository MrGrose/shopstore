import httpx
import pytest

from src.main import app


@pytest.mark.asyncio
async def test_storefront_shoe_size_guide_nike() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get("/storefront/shoe-size-guide/Nike")
    assert response.status_code == 200
    assert "Nike" in response.text
    assert "Стопа, см" in response.text


@pytest.mark.asyncio
async def test_storefront_shoe_size_guide_unknown_brand() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get("/storefront/shoe-size-guide/___no_such_brand___")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_storefront_shoe_size_guide_available_nike() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/storefront/shoe-size-guide-available", params={"brand": "Nike"}
        )
    assert response.status_code == 200
    assert response.json() == {"available": True}


@pytest.mark.asyncio
async def test_storefront_shoe_size_guide_available_unknown() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/storefront/shoe-size-guide-available",
            params={"brand": "___no_such_brand___"},
        )
    assert response.status_code == 200
    assert response.json() == {"available": False}
