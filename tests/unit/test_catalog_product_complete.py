import json
from pathlib import Path

import pytest

from src.models.product import Product, ProductFeature, ProductImage
from src.services.catalog.importing.product_complete import is_product_complete
from src.utils.datetime_fmt import utc_now_naive

_GOLDEN_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / ".01_hlam/docs/samples/graphql_catalog_sample.json"
)


@pytest.mark.parametrize(
    "features,dom_full_at,description_raw,expected",
    [
        ([], None, "Description", False),
        (
            [ProductFeature(name="Color", value="Red", position=0)],
            None,
            "Description",
            True,
        ),
        ([], utc_now_naive(), "Description", True),
        ([], utc_now_naive(), "TRADINTER S.L. Madrid www.bullpadel.com", False),
    ],
)
def test_is_product_complete_features_or_dom_full_at(
    features, dom_full_at, description_raw, expected
):
    product = Product(
        title="Racket",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=1,
        external_id="p1",
        product_url="https://example.com/p1",
        description_raw=description_raw,
        dom_full_at=dom_full_at,
    )
    product.images = [ProductImage(url="https://example.com/i.jpg", position=0)]
    product.features = features
    assert is_product_complete(product) is expected


def test_golden_samples_declare_storefront_pipeline():
    if not _GOLDEN_SAMPLE.is_file():
        pytest.skip("golden sample missing")
    payload = json.loads(_GOLDEN_SAMPLE.read_text(encoding="utf-8"))
    samples = payload.get("samples") or []
    assert samples, "expected non-empty golden samples"
    for row in samples:
        if not row.get("supplier_snapshot_for_db"):
            continue
        assert row.get("storefront_after_pipeline")
