import json
import logging
import re
from decimal import Decimal
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.scraper.sources.graphql_categories import supplier_collections_from_node
from src.utils.html_text import strip_html_plaintext
from src.utils.labels import infer_gender_from_title

logger = logging.getLogger(__name__)

_SPACE_RE = re.compile(r"\s+")
_EXTERNAL_ID_RE = re.compile(r"([a-z]?\d{13,})", re.I)

_PRODUCTS_QUERY = """
query CollectionProducts($handle: String!, $cursor: String)
@inContext(country: US, language: EN) {
  collection(handle: $handle) {
    id
    title
    handle
    products(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          title
          handle
          vendor
          productType
          availableForSale
          descriptionHtml
          onlineStoreUrl
          priceRange {
            minVariantPrice { amount currencyCode }
          }
          compareAtPriceRange {
            minVariantPrice { amount currencyCode }
          }
          images(first: 20) {
            edges { node { url altText } }
          }
          collections(first: 25) {
            edges { node { handle title } }
          }
          variants(first: 100) {
            edges {
              node {
                id
                title
                sku
                availableForSale
                price { amount currencyCode }
                compareAtPrice { amount currencyCode }
                selectedOptions { name value }
              }
            }
          }
        }
      }
    }
  }
}
"""


class StorefrontGraphQLClient:
    def __init__(
        self, endpoint: str, token: str, user_agent: str, timeout_seconds: int
    ):
        self.endpoint = endpoint
        self.token = token
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    # Выполняет GraphQL запрос и возвращает данные.
    def execute(self, query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-shopify-storefront-access-token": self.token,
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("errors"):
            raise RuntimeError(f"Storefront GraphQL errors: {payload['errors']}")
        return payload.get("data") or {}


# Извлекает handle из URL коллекции.
def collection_handle_from_url(collection_url: str) -> str:
    path = urlparse(collection_url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-2] == "collections":
        return parts[-1]
    return parts[-1] if parts else collection_url.strip()


# Определяет тип спорта по URL коллекции.
def collection_sport_type_from_url(collection_url: str) -> str:
    handle = collection_handle_from_url(collection_url).lower()
    if handle.startswith("tennis"):
        return "Tennis"
    if handle.startswith("running"):
        return "Running"
    if handle.startswith("padel"):
        return "Padel"
    return handle.replace("-", " ").title()


# Очищает HTML текст от тегов и пробелов.
def _clean_html(value: str | None) -> str:
    return strip_html_plaintext(value) or ""


# Преобразует цену из GraphQL в строку.
def _money_amount(value: dict | None) -> str:
    if not isinstance(value, dict):
        return "0"
    amount = value.get("amount")
    return str(amount) if amount not in (None, "") else "0"


# Извлекает numeric_id из GraphQL gid.
def _numeric_id(gid: str | None) -> int | None:
    if not gid:
        return None
    tail = str(gid).rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


# Извлекает external_id из продукта.
def _external_id_from_product(node: dict, variants: list[dict]) -> str | None:
    handle = str(node.get("handle") or "")
    match = _EXTERNAL_ID_RE.search(handle)
    if match:
        return match.group(1)
    for variant in variants:
        sku = str(variant.get("sku") or "")
        match = _EXTERNAL_ID_RE.search(sku)
        if match:
            return match.group(1)
    numeric_id = _numeric_id(node.get("id"))
    return str(numeric_id) if numeric_id is not None else None


# Извлекает галерею изображений из продукта.
def _image_gallery(node: dict) -> list[dict]:
    out: list[dict] = []
    for edge in (node.get("images") or {}).get("edges") or []:
        image = edge.get("node") or {}
        url = image.get("url")
        if not url:
            continue
        out.append({"url": str(url), "alt": image.get("altText") or ""})
    return out


# Преобразует вариант продукта в dict.
def _variant_payload(variant: dict) -> dict:
    options = variant.get("selectedOptions") or []
    option_values = [str(item.get("value") or "") for item in options[:3]]
    while len(option_values) < 3:
        option_values.append("")
    available = bool(variant.get("availableForSale"))
    return {
        "id": _numeric_id(variant.get("id")),
        "title": variant.get("title") or "",
        "sku": variant.get("sku") or None,
        "option1": option_values[0] or None,
        "option2": option_values[1] or None,
        "option3": option_values[2] or None,
        "available": available,
        # GraphQL Storefront не даёт qty; 0 не evidence при available=true.
        "inventory_quantity": 0,
        "price": _money_amount(variant.get("price")),
        "compare_at_price": _money_amount(variant.get("compareAtPrice")),
    }


# Преобразует продукт в dict.
def _product_payload(node: dict, base_url: str, sport_type: str) -> dict:
    variants = [
        _variant_payload(edge.get("node") or {})
        for edge in ((node.get("variants") or {}).get("edges") or [])
    ]
    first_available = next(
        (variant for variant in variants if variant["available"]), None
    )
    selected_variant = first_available or (variants[0] if variants else {})
    gallery = _image_gallery(node)
    product_type = str(node.get("productType") or "").strip()
    handle = str(node.get("handle") or "").strip()
    product_url = str(node.get("onlineStoreUrl") or "")
    if not product_url and handle:
        product_url = f"{base_url.rstrip('/')}/products/{handle}"
    sale_price = _money_amount(
        ((node.get("priceRange") or {}).get("minVariantPrice") or {})
    )
    regular_price = _money_amount(
        ((node.get("compareAtPriceRange") or {}).get("minVariantPrice") or {})
    )
    if Decimal(regular_price) <= 0:
        regular_price = sale_price
    stock = sum(int(variant.get("inventory_quantity") or 0) for variant in variants)
    external_id = _external_id_from_product(node, variants)
    title = str(node.get("title") or "")
    gender = infer_gender_from_title(title)
    supplier_collections = supplier_collections_from_node(node)
    pdp_meta = {
        "gender": gender,
        "gender_source": "title" if gender else None,
        "supplier": {
            "import_collection_sport": sport_type,
            "product_type": product_type,
            "collections": supplier_collections,
        },
    }
    return {
        "title": title,
        "brand": node.get("vendor") or "",
        "description": _clean_html(node.get("descriptionHtml")),
        "sale_price": sale_price,
        "sale_price_numeric": sale_price,
        "regular_price": regular_price,
        "product_url": product_url,
        "image_url": gallery[0]["url"] if gallery else "",
        "item_id": external_id,
        "gtm": {
            "item_id": external_id,
            "item_name": node.get("title") or "",
            "item_brand": node.get("vendor") or "",
        },
        "features": [],
        "media_gallery": gallery,
        "product_data": {"variants": variants},
        "selected_variant": selected_variant,
        "pdp_meta": pdp_meta,
        "_import_collection_sport": sport_type,
        "stock": stock,
        "is_active": bool(node.get("availableForSale")),
    }


# Применяет остатки вариантов к продукту.
def apply_variant_stock(
    product: dict,
    product_data: dict,
    selected_variant: dict | None = None,
) -> bool:
    dom_variants = (product_data or {}).get("variants") or []
    if not dom_variants:
        return False

    by_id = {
        str(item.get("id")): item
        for item in dom_variants
        if isinstance(item, dict) and item.get("id") is not None
    }
    by_sku = {
        str(item.get("sku")): item
        for item in dom_variants
        if isinstance(item, dict) and item.get("sku")
    }

    variants = (product.get("product_data") or {}).get("variants") or []
    changed = False
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        dom_variant = by_id.get(str(variant.get("id"))) or by_sku.get(
            str(variant.get("sku") or "")
        )
        if not dom_variant:
            continue
        qty = dom_variant.get("inventory_quantity")
        if isinstance(qty, int):
            variant["inventory_quantity"] = max(0, qty)
            changed = True
        if isinstance(dom_variant.get("available"), bool):
            variant["available"] = dom_variant["available"]

    if not changed:
        return False
    product["stock"] = sum(int(v.get("inventory_quantity") or 0) for v in variants)
    selected_id = str((selected_variant or {}).get("id") or "")
    if selected_id:
        product["selected_variant"] = next(
            (v for v in variants if str(v.get("id")) == selected_id),
            product.get("selected_variant") or {},
        )
    return True


# Извлекает страницу продуктов из коллекции.
def fetch_collection_products_page(
    endpoint: str,
    token: str,
    collection_url: str,
    cursor: str | None,
    base_url: str,
    user_agent: str = "",
    timeout_seconds: int = 60,
) -> tuple[list[dict], str | None, bool]:
    if not token.strip():
        raise ValueError("SCRAPER_STOREFRONT_ACCESS_TOKEN is required for GraphQL mode")
    handle = collection_handle_from_url(collection_url)
    sport_type = collection_sport_type_from_url(collection_url)
    client = StorefrontGraphQLClient(endpoint, token, user_agent, timeout_seconds)
    data = client.execute(
        _PRODUCTS_QUERY,
        {"handle": handle, "cursor": cursor},
    )
    collection = data.get("collection")
    if not collection:
        raise RuntimeError(f"Collection not found: {handle}")
    connection = collection.get("products") or {}
    products = [
        _product_payload(edge.get("node") or {}, base_url, sport_type)
        for edge in connection.get("edges") or []
    ]
    page_info = connection.get("pageInfo") or {}
    return (
        products,
        page_info.get("endCursor"),
        bool(page_info.get("hasNextPage")),
    )
