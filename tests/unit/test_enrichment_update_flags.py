from decimal import Decimal

from src.models.product import Product, ProductImage
from src.services.catalog.importing.enrichment_writer import compute_update_flags
from src.utils.datetime_fmt import utc_now_naive


def _base_flags_kwargs(existing: Product):
    return {
        "existing": existing,
        "sale_price": Decimal(existing.supplier_price_eur or 0),
        "regular_price": Decimal(existing.regular_price or 0),
        "stock": int(existing.stock or 0),
        "incoming_variant_signature": (),
        "current_variant_signature": (),
        "incoming_gallery_layout": ((None, 0),),
        "current_gallery_layout": ((None, 0),),
        "incoming_gallery_url_signature": (
            "https://www.supplier-demo.com/cdn/shop/files/new.jpg",
        ),
        "current_gallery_url_signature": (
            "https://www.supplier-demo.com/cdn/shop/files/old.jpg",
        ),
        "incoming_feature_signature": (),
        "current_feature_signature": (),
        "incoming_description": (
            "Fresh product description long enough to pass imprint checks."
        ),
        "is_dom_full": True,
        "is_dom_import": True,
        "incoming_has_features": False,
        "catalog": {
            "category_l1": existing.category_l1,
            "category_l2": existing.category_l2,
            "category_l3": existing.category_l3,
            "gender": existing.gender,
        },
        "category_l2": existing.category_l2,
        "sport_type": existing.sport_type,
        "trade_group": existing.trade_group,
        "write_categories": False,
    }


def test_compute_update_flags_marks_description_and_urls_as_changes():
    existing = Product(
        title="Oneda Tank Top",
        brand="Bullpadel",
        sale_price=Decimal("47.95"),
        regular_price=Decimal("47.99"),
        supplier_price_eur=Decimal("47.95"),
        stock=1,
        external_id="p0000005951001",
        product_url="https://example.com/p1",
        description_raw="TRADINTER S.L. Madrid www.bullpadel.com",
        description_hash="old-hash",
    )
    existing.images = [
        ProductImage(
            url="https://www.supplier-demo.com/cdn/shop/files/old.jpg?v=1",
            position=0,
        )
    ]
    flags = compute_update_flags(**_base_flags_kwargs(existing))
    assert flags.has_changes is True
    assert flags.refresh_media is True


def test_compute_update_flags_skips_dom_lite_details():
    existing = Product(
        title="Oneda Tank Top",
        brand="Bullpadel",
        sale_price=Decimal("47.95"),
        regular_price=Decimal("47.99"),
        supplier_price_eur=Decimal("47.95"),
        stock=1,
        external_id="p0000005951001",
        product_url="https://example.com/p1",
        description_raw="TRADINTER S.L. Madrid www.bullpadel.com",
        description_hash="old-hash",
        dom_full_at=utc_now_naive(),
    )
    existing.images = [
        ProductImage(
            url="https://www.supplier-demo.com/cdn/shop/files/old.jpg?v=1",
            position=0,
        )
    ]
    kwargs = _base_flags_kwargs(existing)
    kwargs["is_dom_full"] = False
    flags = compute_update_flags(**kwargs)
    assert flags.has_changes is True
    assert flags.refresh_media is False
