from urllib.parse import urlsplit, urlunsplit


# Канонический URL товара для сопоставления со snapshot
# (без query/fragment, без trailing slash).
def canonical_product_url(url: str | None) -> str:
    parts = urlsplit(str(url or "").strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


# Нормализует external_id поставщика для сравнения.
def normalize_external_id(external_id: str | None) -> str:
    return str(external_id or "").casefold()


# Проверяет, есть ли товар в incoming snapshot по id или URL.
def product_in_catalog_snapshot(
    external_id: str | None,
    product_url: str | None,
    incoming_external_ids: set[str],
    incoming_urls: set[str],
) -> bool:
    normalized_id = normalize_external_id(external_id)
    if normalized_id and normalized_id in incoming_external_ids:
        return True
    normalized_url = canonical_product_url(product_url)
    if normalized_url and normalized_url in incoming_urls:
        return True
    return False
