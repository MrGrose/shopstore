import json
import re
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from src.utils.html_text import (
    is_manufacturer_imprint_description,
    strip_html_plaintext,
    strip_manufacturer_imprint_from_description,
)

from .pdp_support import clean_text, extract_first, normalize_url


def extract_selected_variant_json(html: str) -> dict:
    match = re.search(
        r"<script[^>]*data-selected-variant[^>]*>\s*(\{.*?\})\s*</script>",
        html,
        re.S,
    )
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def extract_json_script(html, script_id):
    match = re.search(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>\s*(\{{.*?\}})\s*</script>',
        html,
        re.S,
    )
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def extract_product_data_json(html: str) -> dict:
    return extract_json_script(html, "product-data")


def product_json_url(product_url: str) -> str:
    parts = urlsplit(product_url)
    path = parts.path if parts.path.endswith(".js") else f"{parts.path.rstrip('/')}.js"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def parse_product_json(text: str) -> dict:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def merge_product_data_variant_skus(product_data: dict, product_json: dict) -> dict:
    variants = product_data.get("variants")
    product_json_variants = product_json.get("variants")
    if not isinstance(variants, list) or not isinstance(product_json_variants, list):
        return product_data

    sku_by_id = {
        item.get("id"): item.get("sku")
        for item in product_json_variants
        if isinstance(item, dict) and item.get("id") is not None and item.get("sku")
    }
    if not sku_by_id:
        return product_data

    merged = dict(product_data)
    merged["variants"] = [
        (
            {**item, "sku": sku_by_id.get(item.get("id"), item.get("sku"))}
            if isinstance(item, dict)
            else item
        )
        for item in variants
    ]
    return merged


def extract_inline_product_json(html: str) -> dict:
    match = re.search(r'productData:\s*"', html)
    if not match:
        return {}
    start = match.end()
    chunks: list[str] = []
    idx = start
    while idx < len(html):
        char = html[idx]
        if char == '"':
            break
        if char == "\\" and idx + 1 < len(html):
            chunks.append(html[idx : idx + 2])
            idx += 2
            continue
        chunks.append(char)
        idx += 1
    if idx >= len(html):
        return {}
    try:
        inner = bytes("".join(chunks), "utf-8").decode("unicode_escape")
        payload = json.loads(inner)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _gallery_item(url: str, alt: str = "") -> dict[str, str]:
    full_src = normalize_url("https://www.supplier-demo.com", unescape(url))
    if not full_src:
        return {}
    return {"url": full_src, "alt": clean_text(alt)}


def parse_product_json_media_gallery(product_json: dict) -> list[dict]:
    gallery: list[dict] = []
    seen: set[str] = set()
    for raw_url in product_json.get("images") or []:
        item = _gallery_item(str(raw_url))
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        gallery.append(item)
    for media in product_json.get("media") or []:
        if not isinstance(media, dict):
            continue
        preview = media.get("preview_image") or {}
        raw_url = media.get("src") or preview.get("src") or ""
        item = _gallery_item(str(raw_url), str(media.get("alt") or ""))
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        gallery.append(item)
    featured = product_json.get("featured_image")
    if featured:
        item = _gallery_item(str(featured))
        url = item.get("url")
        if url and url not in seen:
            gallery.insert(0, item)
    return gallery


def parse_product_json_description(product_json: dict) -> str:
    for key in ("description", "content"):
        raw_html = product_json.get(key)
        if not raw_html:
            continue
        text = strip_html_plaintext(str(raw_html)) or ""
        cleaned = strip_manufacturer_imprint_from_description(text)
        if cleaned and not is_manufacturer_imprint_description(cleaned):
            return cleaned
    return ""


def _merge_media_galleries(*galleries: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for gallery in galleries:
        for item in gallery:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged


def parse_product_page_details(html: str) -> dict:
    product_json = extract_inline_product_json(html)
    html_gallery = parse_product_page_media_gallery(html)
    json_gallery = parse_product_json_media_gallery(product_json)
    media_gallery = json_gallery or html_gallery
    if json_gallery and html_gallery:
        media_gallery = _merge_media_galleries(json_gallery, html_gallery)
    json_description = parse_product_json_description(product_json)
    accordion_description = strip_manufacturer_imprint_from_description(
        parse_product_page_description(html)
    )
    if json_description:
        description = json_description
    elif accordion_description:
        description = accordion_description
    else:
        description = ""
    return {
        "media_gallery": media_gallery,
        "description": description,
        "features": parse_product_page_features(html),
        "pdp_meta": parse_product_page_meta(html),
        "prices": parse_product_page_prices(html),
        "selected_variant": extract_selected_variant_json(html),
        "product_data": extract_product_data_json(html),
    }


def slice_html_near_features(html):
    for marker in ("tp-product-accordion__content", "product-features-grid"):
        idx = html.find(marker)
        if idx != -1:
            end = idx + 800_000
            return html[idx:end]
    return html


def extract_balanced_div(html, start):
    if start < 0 or start >= len(html) or not html[start:].startswith("<div"):
        return None
    depth = 1
    pos = start + 4
    while depth > 0 and pos < len(html):
        next_open = html.find("<div", pos)
        next_close = html.find("</div>", pos)
        if next_close == -1:
            return None
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 4
        else:
            depth -= 1
            pos = next_close + 6
    return html[start:pos]


def parse_product_page_features(html):
    segment = slice_html_near_features(html)
    items = []
    for match in re.finditer(
        r'<div class="tp-product-features__item"[^>]*>\s*'
        r"(<img[^>]+>)?\s*"
        r'<div class="tp-product-features__item-content">\s*'
        r'<h3[^>]*class="tp-product-features__item-title"[^>]*>(.*?)</h3>\s*'
        r'<p[^>]*class="tp-product-features__item-description"[^>]*>\s*(.*?)\s*</p>',
        segment,
        re.S | re.I,
    ):
        img_tag = match.group(1) or ""
        icon_src = extract_first(r'src="([^"]+)"', img_tag) if img_tag else ""
        items.append(
            {
                "icon_url": (
                    normalize_url("https://www.supplier-demo.com", icon_src)
                    if icon_src
                    else ""
                ),
                "title": clean_text(match.group(2)),
                "description": clean_text(match.group(3)),
            }
        )
    if not items:
        for match in re.finditer(
            r"<h3[^>]*tp-product-features__item-title[^>]*>(.*?)</h3>\s*"
            r"<p[^>]*tp-product-features__item-description[^>]*>\s*(.*?)\s*</p>",
            segment,
            re.S | re.I,
        ):
            items.append(
                {
                    "icon_url": "",
                    "title": clean_text(match.group(1)),
                    "description": clean_text(match.group(2)),
                }
            )
    return items


def parse_product_page_media_gallery(html):
    gallery = []
    seen = set()
    gallery_item_re = (
        r'<li[^>]*class="[^"]*product__media-item[^"]*"[^>]*>'
        r'.*?<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"'
    )
    for src, alt in re.findall(gallery_item_re, html, re.S | re.I):
        full_src = normalize_url("https://www.supplier-demo.com", unescape(src))
        if not full_src or full_src in seen:
            continue
        seen.add(full_src)
        gallery.append({"url": full_src, "alt": clean_text(alt)})
    return gallery


def parse_product_page_description(html):
    desc_open = re.search(
        r'<div[^>]*class="[^"]*tp-product-accordion__description[^"]*"[^>]*>',
        html,
        re.S | re.I,
    )
    if not desc_open:
        return ""
    block = extract_balanced_div(html, desc_open.start())
    if not block:
        return ""
    inner = re.sub(r"^<div[^>]*>", "", block, flags=re.S | re.I)
    inner = re.sub(r"</div>$", "", inner, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", inner)
    return clean_text(text)


def _normalize_price_value(value: str) -> str:
    cleaned = clean_text(value)
    cleaned = cleaned.replace("€", "").replace("\xa0", "").strip()
    cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    return cleaned


def parse_product_page_prices(html: str) -> dict[str, str]:
    price_open = re.search(
        r'<div[^>]*id="price-[^"]*"[^>]*class="[^"]*tp-price__wrapper[^"]*"[^>]*>',
        html,
        re.S | re.I,
    )
    segment = html
    if price_open:
        segment = extract_balanced_div(html, price_open.start()) or html
    current = extract_first(
        r'<span[^>]*class="[^"]*tp-price-item--current[^"]*"[^>]*'
        r'data-tp-gtm-final-price="([^"]+)"',
        segment,
    )
    if not current:
        current = extract_first(
            r'<span[^>]*class="[^"]*tp-price-item--current[^"]*"[^>]*>(.*?)</span>',
            segment,
        )
    regular = extract_first(
        r'<span[^>]*class="[^"]*tp-price-item--compare[^"]*"[^>]*>'
        r"\s*<s>\s*(.*?)\s*</s>",
        segment,
    )
    current = _normalize_price_value(current)
    regular = _normalize_price_value(regular)
    return {
        "sale_price": current,
        "regular_price": regular or current,
    }


def parse_product_page_meta(html):
    wishlist_tag = extract_first(
        r'(<button[^>]*class="[^"]*swym-add-to-wishlist-view-product[^"]*"[^>]*>)',
        html,
    )
    stock_status = extract_first(
        r'<p[^>]*class="[^"]*tp-product-stock-message[^"]*"[^>]*>\s*(.*?)\s*</p>',
        html,
    )
    return {
        "sku": extract_first(r'<p class="product__sku"[^>]*>.*?SKU\s*([^<\n]+)', html),
        "stock_status": stock_status,
        "tax_info": extract_first(
            r'<div class="product__tax[^"]*">\s*(.*?)\s*</div>', html
        ),
        "product_id": extract_first(r'data-product-id="([^"]+)"', wishlist_tag),
        "variant_id": extract_first(r'data-variant-id="([^"]+)"', wishlist_tag),
        "item_size": extract_first(
            r'name="properties\[_item-size\]" value="([^"]*)"', html
        ),
        "gender": extract_first(r'name="properties\[_gender\]" value="([^"]*)"', html),
        "sport_type": extract_first(
            r'name="properties\[_sport-type\]" value="([^"]*)"', html
        ),
        "trade_group": extract_first(
            r'name="properties\[_trade-group\]" value="([^"]*)"', html
        ),
        "global_category": extract_first(
            r'name="properties\[_global-category\]" value="([^"]*)"', html
        ),
        "item_category": extract_first(
            r'name="properties\[_item-category\]" value="([^"]*)"', html
        ),
        "item_category2": extract_first(
            r'name="properties\[_item-category-2\]" value="([^"]*)"', html
        ),
        "item_category3": extract_first(
            r'name="properties\[_item-category-3\]" value="([^"]*)"', html
        ),
    }
