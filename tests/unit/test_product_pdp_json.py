import json

from src.scraper.parsers.product_pdp import (
    extract_inline_product_json,
    parse_product_json_description,
    parse_product_json_media_gallery,
    parse_product_page_details,
)
from src.services.catalog.importing.product_complete import validate_full_dom_details

_IMPRINT_16878 = (
    "TRADINTER S.L. Transpaderne, 29 4 Izsa., Building Barajas I, "
    "Madrid 28042, Spain www.bullpadel.com"
)
_VALID_929 = (
    "Experience Unmatched Comfort with the Oneda Tank Top for Women. "
    "Designed specifically for the dynamic world of padel, this tank "
    "top delivers breathability, a locked-in fit, and freedom to swing "
    "through every point. Moisture-wicking fabric keeps you dry in long "
    "matches, while a racerback cut stays clear of the shoulder on serves "
    "and overheads. Pair it with a skirt or shorts for training and match "
    "day. Built for club players who want a clean silhouette without extra "
    "bulk. The construction holds shape after washes and stays comfortable "
    "under a warm-up jacket. Oneda Tank Top Women is made for padel first. "
    "Use it for BIDI BADU sessions, HEAD drills, and adidas warm-ups "
    "without treating legal manufacturer copy as the product story. "
    "Keep swinging on clay and indoor courts with the same light feel "
    "from the first game to the last. Extra lines exist only so the "
    "fixture matches a recovered FULL description around nine hundred "
    "characters, not a 98-character TRADINTER imprint block."
)


def _inline_product_data(payload: dict) -> str:
    encoded = json.dumps(json.dumps(payload))
    return f"<script>window.__INITIAL__ = {{ productData: {encoded} }};</script>"


def _accordion(text: str) -> str:
    return f'<div class="tp-product-accordion__description rte"><div>{text}</div></div>'


def _gallery_li(filename: str) -> str:
    return (
        '<li class="product__media-item">'
        f'<img src="//www.supplier-demo.com/cdn/shop/files/{filename}?v=1" alt="">'
        "</li>"
    )


def test_parse_product_json_media_gallery_decodes_json_escaped_urls() -> None:
    base = "\\/\\/www.supplier-demo.com\\/cdn\\/shop\\/files\\/"
    product_json = {
        "images": [
            f"{base}P000000900100200.jpg?v=1785309127",
            f"{base}P000000900100200_2.jpg?v=1785309127",
        ]
    }
    gallery = parse_product_json_media_gallery(product_json)
    assert gallery[0]["url"] == (
        "https://www.supplier-demo.com/cdn/shop/files/P000000900100200.jpg?v=1785309127"
    )
    assert gallery[1]["url"].endswith("P000000900100200_2.jpg?v=1785309127")


def test_extract_inline_product_json_reads_embedded_payload():
    payload = {
        "title": "Oneda Tank Top Women - white",
        "description": "<p>Designed specifically for padel.</p>",
        "images": ["//www.supplier-demo.com/cdn/shop/files/main.jpg?v=1"],
    }
    html = _inline_product_data(payload)
    parsed = extract_inline_product_json(html)
    assert parsed["title"] == payload["title"]
    assert "Designed specifically" in parse_product_json_description(parsed)


def test_parse_product_page_details_prefers_json_description_over_accordion():
    payload = {
        "description": (
            "<h2>Experience Unmatched Comfort</h2>"
            "<p>Designed specifically for the dynamic world of padel.</p>"
        ),
        "images": [
            "//www.supplier-demo.com/cdn/shop/files/P000000595100100.jpg?v=1787639775"
        ],
    }
    html = _inline_product_data(payload)
    html += _accordion("TRADINTER S.L. Madrid www.bullpadel.com")
    html += _gallery_li("stale.jpg")
    details = parse_product_page_details(html)
    assert details["description"].startswith("Experience Unmatched Comfort")
    assert "TRADINTER" not in details["description"]
    assert details["media_gallery"][0]["url"].endswith(
        "P000000595100100.jpg?v=1787639775"
    )


def test_16878_accordion_imprint_falls_back_to_json_description() -> None:
    assert len(_IMPRINT_16878) < 150
    payload = {
        "description": f"<p>{_VALID_929}</p>",
        "images": ["//www.supplier-demo.com/cdn/shop/files/16878.jpg?v=1"],
    }
    html = _inline_product_data(payload) + _accordion(_IMPRINT_16878)
    html += _gallery_li("stale.jpg")
    details = parse_product_page_details(html)
    assert "TRADINTER" not in details["description"]
    assert 900 <= len(details["description"]) <= 980
    assert validate_full_dom_details(details) is None


def test_accordion_only_valid_description_is_accepted() -> None:
    html = _accordion(_VALID_929) + _gallery_li("bidi-badu.jpg")
    details = parse_product_page_details(html)
    assert details["description"].startswith("Experience Unmatched Comfort")
    assert validate_full_dom_details(details) is None


def test_imprint_accordion_without_json_is_invalid_description() -> None:
    html = _accordion(_IMPRINT_16878) + _gallery_li("head.jpg")
    details = parse_product_page_details(html)
    assert details["description"] == ""
    assert validate_full_dom_details(details) == "invalid_description"


def test_json_imprint_only_is_invalid_description() -> None:
    payload = {
        "description": f"<p>{_IMPRINT_16878}</p>",
        "images": ["//www.supplier-demo.com/cdn/shop/files/adidas.jpg?v=1"],
    }
    html = _inline_product_data(payload)
    details = parse_product_page_details(html)
    assert details["description"] == ""
    assert validate_full_dom_details(details) == "invalid_description"
