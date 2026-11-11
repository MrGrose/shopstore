from src.constants.storefront_mapping import (
    STOREFRONT_NAV_STATUS_EXCLUDED,
    STOREFRONT_NAV_STATUS_NOT_SELLABLE,
    STOREFRONT_NAV_STATUS_ORPHAN,
    STOREFRONT_NAV_STATUS_VISIBLE,
)

STOREFRONT_NAV_STATUS_LABELS_RU: dict[str, str] = {
    "all": "Все",
    STOREFRONT_NAV_STATUS_VISIBLE: "В навигации",
    STOREFRONT_NAV_STATUS_EXCLUDED: "Правило навигации",
    STOREFRONT_NAV_STATUS_ORPHAN: "Не в навигации",
    STOREFRONT_NAV_STATUS_NOT_SELLABLE: "Не продаётся",
}


# Русская подпись mapping status для админки (из active release resolutions).
def storefront_mapping_status_label_ru(status: str | None) -> str:
    key = (status or "").strip()
    if not key:
        return ""
    return STOREFRONT_NAV_STATUS_LABELS_RU.get(key, key)
