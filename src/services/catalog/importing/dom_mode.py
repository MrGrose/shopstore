from src.models.product import Product
from src.services.catalog.importing.product_complete import is_product_complete


# FULL если товар не COMPLETE, иначе LITE.
def dom_enrichment_mode(product: Product) -> str:
    return "LITE" if is_product_complete(product) else "FULL"


# Режим DOM из payload scheduler (fallback FULL).
def dom_mode_from_payload(product: dict) -> str:
    mode = str(product.get("dom_mode") or "").strip().upper()
    if mode in {"FULL", "LITE"}:
        return mode
    return "FULL"
