import logging
import time
from dataclasses import dataclass, field

from src.scraper.config.config import ParseConfig
from src.scraper.config.settings import Settings
from src.scraper.infrastructure.browser_manager import BrowserManager
from src.services.catalog.importing.catalog_match import canonical_product_url

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CollectionDomProduct:
    visible_variant_ids: set[str] = field(default_factory=set)


# Снимает product links и variant id с listing страницы коллекции.
async def _scrape_collection_page(
    ctx, collection_url: str, env: Settings
) -> list[dict]:
    page = await ctx.new_page()
    try:
        await page.goto(
            collection_url,
            wait_until="domcontentloaded",
            timeout=env.collection_page_timeout_ms,
        )
        await page.wait_for_timeout(env.collection_settle_timeout_ms)
        return await page.evaluate(
            """
            () => {
              const out = [];
              const links = Array.from(document.querySelectorAll('a')).filter(
                (item) => (item.href || '').includes('/products/')
              );
              for (const link of links) {
                const href = link.href || '';
                out.push({
                  href,
                  variantId: new URL(href).searchParams.get('variant') || '',
                });
              }
              return out;
            }
            """
        )
    finally:
        await page.close()


# Listing href ?variant= — видимость в коллекции, не orderability и не stock.
def apply_collection_listing(product: dict, visible_ids: set[str]) -> int:
    if not visible_ids:
        return 0
    listed = 0
    variants = (product.get("product_data") or {}).get("variants") or []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if str(variant.get("id") or "") in visible_ids:
            listed += 1
    return listed


# Собирает dict url → видимые variant id из строк listing.
def _rows_to_products(rows: list[dict]) -> dict[str, CollectionDomProduct]:
    products: dict[str, CollectionDomProduct] = {}
    for row in rows:
        url = canonical_product_url(str(row.get("href") or ""))
        if not url:
            continue
        item = products.setdefault(url, CollectionDomProduct())
        variant_id = str(row.get("variantId") or "").strip()
        if variant_id:
            item.visible_variant_ids.add(variant_id)
    return products


# DOM listing одной коллекции; опционально переиспользует внешний ctx.
async def fetch_collection_dom_products(
    collection_url: str,
    env: Settings,
    *,
    ctx=None,
    manager: BrowserManager | None = None,
) -> dict[str, CollectionDomProduct]:
    owns_browser = ctx is None
    if owns_browser:
        manager = BrowserManager(
            ParseConfig(headless=env.headless, require_storage_state=True)
        )
        ctx = await manager.launch_browser(proxy_pool=[])
    assert ctx is not None

    started = time.monotonic()
    try:
        rows = await _scrape_collection_page(ctx, collection_url, env)
    finally:
        if owns_browser and manager is not None:
            await manager.close_browser()

    products = _rows_to_products(rows)
    visible_variants = sum(len(item.visible_variant_ids) for item in products.values())
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "DOM-листинг коллекции: товаров=%s видимых_вариантов=%s duration_ms=%s для %s",
        len(products),
        visible_variants,
        duration_ms,
        collection_url,
    )
    return products


# Один browser на все collection URLs.
async def fetch_all_collection_dom_products(
    collection_urls: list[str],
    env: Settings,
) -> dict[str, CollectionDomProduct]:
    if not collection_urls:
        return {}

    manager = BrowserManager(
        ParseConfig(headless=env.headless, require_storage_state=True)
    )
    started = time.monotonic()
    merged: dict[str, CollectionDomProduct] = {}
    ctx = await manager.launch_browser(proxy_pool=[])
    try:
        for collection_url in collection_urls:
            rows = await _scrape_collection_page(ctx, collection_url, env)
            chunk = _rows_to_products(rows)
            for url, item in chunk.items():
                target = merged.setdefault(url, CollectionDomProduct())
                target.visible_variant_ids.update(item.visible_variant_ids)
    finally:
        await manager.close_browser()

    duration_ms = int((time.monotonic() - started) * 1000)
    visible_variants = sum(len(item.visible_variant_ids) for item in merged.values())
    logger.info(
        "DOM-листинг коллекций: urls=%s товаров=%s видимых_вариантов=%s duration_ms=%s",
        len(collection_urls),
        len(merged),
        visible_variants,
        duration_ms,
    )
    return merged
