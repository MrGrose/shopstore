from pathlib import Path

from src.services.orders.supplier_availability.client import (
    build_variant_snapshot,
    parse_member_price_eur,
    parse_supplier_variant_offline,
)
from src.services.orders.supplier_availability.service import (
    VERDICT_MANUAL,
    compute_item_verdict,
    compute_order_verdict,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "supplier_availability"


def test_parse_member_price_from_fixture() -> None:
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    assert parse_member_price_eur(html) == "119.90"


def test_offline_check_prefers_variant_id_over_wrong_sku() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/spike-demo",
        product_json_text=product_json,
        html=html,
        variant_id="910001",
        sku="WRONG-SKU",
    )
    assert result.found is True
    assert result.snapshot is not None
    assert result.snapshot.variant_id == "910001"


def test_offline_check_does_not_fallback_to_sku_when_variant_id_missing() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/spike-demo",
        product_json_text=product_json,
        html=html,
        variant_id="999999",
        sku="SPIKE-SKU-OK",
    )
    assert result.found is False


def test_offline_check_finds_variant_by_sku() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/spike-demo",
        product_json_text=product_json,
        html=html,
        sku="SPIKE-SKU-OK",
    )
    assert result.found is True
    assert result.html_validation is None
    assert result.snapshot is not None
    assert result.snapshot.available is True
    assert result.snapshot.inventory_quantity == 4
    assert result.snapshot.current_price_eur == "129.90"
    assert result.snapshot.member_price_eur == "119.90"


def test_offline_check_missing_variant() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/spike-demo",
        product_json_text=product_json,
        html=html,
        sku="UNKNOWN",
    )
    assert result.found is False


def test_build_variant_snapshot_from_json_price() -> None:
    variant = {
        "id": 1,
        "sku": "X",
        "available": True,
        "inventory_quantity": 2,
        "price": "9999",
    }
    snapshot = build_variant_snapshot(variant)
    assert snapshot.current_price_eur == "99.99"


# CAPTCHA только по widget-token, не по слову captcha.
def test_captcha_without_session_requires_manual_review() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    check = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/demo",
        product_json_text=product_json,
        html='<html><body><div class="cf-turnstile"></div></body></html>',
        variant_id="910001",
    )
    row = compute_item_verdict(1, check, captured_price_eur=None)

    assert check.challenge == "captcha"
    assert compute_order_verdict([row]) == VERDICT_MANUAL


def test_invalid_html_without_session_requires_manual_review() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    check = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/demo",
        product_json_text=product_json,
        html="<html><body>unexpected page</body></html>",
        variant_id="910001",
    )
    row = compute_item_verdict(1, check, captured_price_eur=None)

    assert check.html_validation == "no_product_data"
    assert compute_order_verdict([row]) == VERDICT_MANUAL


def test_login_link_on_valid_pdp_does_not_invalidate_session() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    html_with_login_link = html.replace(
        "</body>",
        '<a href="/account/login">Login</a></body>',
    )
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/spike-demo",
        product_json_text=product_json,
        html=html_with_login_link,
        variant_id="910001",
    )

    assert result.found is True
    assert result.html_validation is None
    assert result.challenge is None
    assert result.session_valid is True
