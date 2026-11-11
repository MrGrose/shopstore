from src.services.catalog.importing.catalog_match import (
    canonical_product_url,
    normalize_external_id,
    product_in_catalog_snapshot,
)


def test_canonical_product_url_strips_query_and_trailing_slash():
    assert (
        canonical_product_url("https://shop.example/p/1/?ref=x#frag")
        == "https://shop.example/p/1"
    )


def test_normalize_external_id_casefold():
    assert normalize_external_id("AbC-123") == "abc-123"


def test_product_in_catalog_snapshot_by_external_id():
    assert product_in_catalog_snapshot(
        external_id="X1",
        product_url=None,
        incoming_external_ids={"x1"},
        incoming_urls=set(),
    )


def test_product_in_catalog_snapshot_by_url():
    url = "https://shop.example/p/42"
    assert product_in_catalog_snapshot(
        external_id=None,
        product_url=url,
        incoming_external_ids=set(),
        incoming_urls={canonical_product_url(url)},
    )
