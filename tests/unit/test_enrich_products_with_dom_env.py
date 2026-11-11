from types import SimpleNamespace

import pytest

from src.scraper.enrichment.product_dom import enrich_products_with_dom


# Минимальный env с полем, которое enrich_products_with_dom читает до enrich loop.
def _minimal_dom_env() -> SimpleNamespace:
    return SimpleNamespace(storefront_stock_workers=1)


@pytest.mark.asyncio
async def test_enrich_products_with_dom_requires_env_parameter() -> None:
    result = await enrich_products_with_dom([], _minimal_dom_env(), object())
    assert result == {
        "total": 0,
        "success": 0,
        "failed": 0,
        "failed_products": [],
    }
