from dataclasses import dataclass, field

from src.services.catalog.importing.catalog_match import (
    canonical_product_url,
    normalize_external_id,
)
from src.utils.labels import normalize_sport_type


@dataclass
class ScrapeCatalogSnapshot:
    # Накопленный снимок товаров за полный цикл парсинга (все коллекции).

    # Внешние идентификаторы товаров.
    external_ids: set[str] = field(default_factory=set)
    # URL товаров.
    urls: set[str] = field(default_factory=set)
    # Top-категории товаров.
    top_categories: set[str] = field(default_factory=set)
    # GraphQL-пагинация прошла до конца (без max_products и без обрыва).
    complete: bool = True
    # Сколько карточек товаров попало в снимок (до дедупа по external_id).
    products_fetched: int = 0

    def absorb_chunk(self, chunk: list[dict]) -> None:
        self.products_fetched += len(chunk)
        for product in chunk:
            gtm = product.get("gtm") or {}
            external_id = product.get("item_id") or gtm.get("item_id")
            if external_id:
                self.external_ids.add(normalize_external_id(str(external_id)))
            product_url = product.get("product_url")
            if product_url:
                self.urls.add(canonical_product_url(str(product_url)))
            sport_type = normalize_sport_type(gtm.get("item_sport_type"))
            if sport_type:
                self.top_categories.add(sport_type)

    @property
    def has_catalog_data(self) -> bool:
        return bool(self.external_ids or self.urls)


async def fetch_live_graphql_snapshot(
    env,
    collection_urls: list[str],
) -> ScrapeCatalogSnapshot:
    # Свежий снимок для finalize. complete=True — «дошли до hasNextPage=false»,
    # не «число товаров совпало с витриной»; API может отдать меньше карточек.
    import asyncio

    from src.scraper.sources.graphql_catalog import fetch_collection_products_page

    snapshot = ScrapeCatalogSnapshot()
    for collection_url in collection_urls:
        cursor: str | None = None
        has_next = True
        while has_next:
            products_page, cursor, has_next = await asyncio.to_thread(
                fetch_collection_products_page,
                endpoint=env.storefront_graphql_endpoint,
                token=env.storefront_access_token,
                collection_url=collection_url,
                cursor=cursor,
                base_url=env.base_url,
                user_agent=env.user_agent,
                timeout_seconds=env.graphql_timeout_seconds,
            )
            snapshot.absorb_chunk(products_page)
            if env.max_products and snapshot.products_fetched >= env.max_products:
                snapshot.complete = False
                return snapshot
    return snapshot
