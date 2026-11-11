import hashlib
import json
from typing import Any

from src.models.product import Product
from src.services.catalog.text import text_or_none

_TAXONOMY_KEYS = (
    "item_category",
    "item_category2",
    "item_category3",
    "sport_type",
)


# Собирает RAW supplier snapshot из import payload (без category_l* finals).
def build_supplier_snapshot(product: dict[str, Any]) -> dict[str, Any] | None:
    pdp_meta = product.get("pdp_meta") or {}
    supplier = pdp_meta.get("supplier")
    if isinstance(supplier, dict) and supplier.get("product_type"):
        return _normalize_supplier_snapshot(supplier)

    import_sport = text_or_none(
        product.get("_import_collection_sport")
        or pdp_meta.get("import_collection_sport")
    )
    gtm = product.get("gtm") or {}
    product_type = text_or_none(
        pdp_meta.get("product_type") or gtm.get("item_category2")
    )
    collections = pdp_meta.get("collections")
    if not isinstance(collections, list):
        collections = []
    normalized_collections = _normalize_collections(collections)
    if not product_type and not normalized_collections:
        return None
    return _normalize_supplier_snapshot(
        {
            "import_collection_sport": import_sport,
            "product_type": product_type,
            "collections": normalized_collections,
        }
    )


# Собирает supplier_taxonomy из DOM pdp_meta.
def build_supplier_taxonomy_from_pdp_meta(
    pdp_meta: Any,
) -> dict[str, str | None] | None:
    meta = _coerce_pdp_meta_dict(pdp_meta)
    taxonomy = {key: text_or_none(meta.get(key)) for key in _TAXONOMY_KEYS}
    if not any(taxonomy.values()):
        return None
    return taxonomy


# Мержит supplier_taxonomy в persisted snapshot (DOM FULL, non-destructive).
def merge_supplier_taxonomy_from_pdp_meta(
    target: Product,
    pdp_meta: Any,
) -> bool:
    snapshot = target.supplier_snapshot_json
    if not isinstance(snapshot, dict) or not text_or_none(snapshot.get("product_type")):
        return False
    incoming = build_supplier_taxonomy_from_pdp_meta(pdp_meta)
    if not incoming:
        return False
    raw_existing = snapshot.get("supplier_taxonomy")
    existing = raw_existing if isinstance(raw_existing, dict) else {}
    merged = dict(existing)
    changed = False
    for key, value in incoming.items():
        if not value:
            continue
        if merged.get(key) != value:
            merged[key] = value
            changed = True
    if not changed:
        return False
    new_snapshot = _normalize_supplier_snapshot(
        {
            **snapshot,
            "supplier_taxonomy": merged,
        }
    )
    new_hash = supplier_snapshot_hash(new_snapshot)
    if target.supplier_snapshot_hash == new_hash:
        return False
    target.supplier_snapshot_json = new_snapshot
    target.supplier_snapshot_hash = new_hash
    return True


# Стабильный sha256 для сравнения изменений supplier input.
def supplier_snapshot_hash(snapshot: dict[str, Any]) -> str:
    canonical = _canonical_snapshot_for_hash(snapshot)
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Нормализует коллекции.
def _normalize_collections(collections: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in collections:
        if not isinstance(item, dict):
            continue
        handle = text_or_none(item.get("handle"))
        title = text_or_none(item.get("title"))
        if not handle:
            continue
        key = (handle, title or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"handle": handle, "title": title or handle})
    return out


# Нормализует supplier_taxonomy блок.
def _normalize_supplier_taxonomy(raw: Any) -> dict[str, str | None] | None:
    if not isinstance(raw, dict):
        return None
    taxonomy = {key: text_or_none(raw.get(key)) for key in _TAXONOMY_KEYS}
    if not any(taxonomy.values()):
        return None
    return taxonomy


# Нормализует snapshot для хэширования.
def _canonical_snapshot_for_hash(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_supplier_snapshot(snapshot)
    collections = list(normalized.get("collections") or [])
    collections.sort(key=lambda row: row["handle"])
    out: dict[str, Any] = {
        **normalized,
        "collections": collections,
    }
    taxonomy = out.get("supplier_taxonomy")
    if isinstance(taxonomy, dict):
        out["supplier_taxonomy"] = {
            key: taxonomy[key] for key in sorted(taxonomy) if taxonomy.get(key)
        }
    return out


# Нормализует snapshot.
def _normalize_supplier_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "import_collection_sport": text_or_none(raw.get("import_collection_sport")),
        "product_type": text_or_none(raw.get("product_type")),
        "collections": _normalize_collections(raw.get("collections") or []),
    }
    taxonomy = _normalize_supplier_taxonomy(raw.get("supplier_taxonomy"))
    if taxonomy:
        out["supplier_taxonomy"] = taxonomy
    return out


# Приводит pdp_meta к dict.
def _coerce_pdp_meta_dict(pdp_meta: Any) -> dict[str, Any]:
    if pdp_meta is None:
        return {}
    if isinstance(pdp_meta, dict):
        return pdp_meta
    model_dump = getattr(pdp_meta, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return {}


# Пишет supplier_snapshot_json/hash если hash изменился.
def apply_supplier_snapshot_to_product(
    target: Product,
    product_payload: dict[str, Any],
) -> bool:
    snapshot = build_supplier_snapshot(product_payload)
    if not snapshot:
        return False
    existing_snapshot = target.supplier_snapshot_json
    if isinstance(existing_snapshot, dict):
        existing_taxonomy = existing_snapshot.get("supplier_taxonomy")
        incoming_taxonomy = snapshot.get("supplier_taxonomy")
        same_import_sport = existing_snapshot.get(
            "import_collection_sport"
        ) == snapshot.get("import_collection_sport")
        same_product_type = existing_snapshot.get("product_type") == snapshot.get(
            "product_type"
        )
        same_supplier_scope = same_import_sport and same_product_type
        if same_supplier_scope and isinstance(existing_taxonomy, dict):
            merged_taxonomy = dict(existing_taxonomy)
            if isinstance(incoming_taxonomy, dict):
                merged_taxonomy.update(
                    {key: value for key, value in incoming_taxonomy.items() if value}
                )
            snapshot = _normalize_supplier_snapshot(
                {**snapshot, "supplier_taxonomy": merged_taxonomy}
            )
    new_hash = supplier_snapshot_hash(snapshot)
    if target.supplier_snapshot_hash == new_hash:
        return False
    target.supplier_snapshot_json = snapshot
    target.supplier_snapshot_hash = new_hash
    return True
