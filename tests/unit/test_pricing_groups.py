from src.services.catalog.display.pricing_nav_registry import (
    CATALOG_SUBCATEGORIES,
    CatalogSubCategoryDef,
)
from src.services.pricing import groups as pricing_groups
from src.services.pricing.groups import (
    FALLBACK_SUBCATEGORY_SLUG,
    iter_pricing_groups,
    resolve_pricing_group,
)
from src.web.admin_icons import ADMIN_ICONS


# Фиксирует публичный состав storefront-групп.
def test_catalog_subcategories_snapshot() -> None:
    snapshot = {
        sport: tuple((item.slug, item.label) for item in subcategories)
        for sport, subcategories in CATALOG_SUBCATEGORIES.items()
    }

    assert snapshot == {
        "Padel": (
            ("rackets", "Ракетки"),
            ("apparel", "Одежда"),
            ("shoes", "Обувь"),
            ("balls", "Мячи"),
            ("bags", "Сумки"),
            ("accessories", "Аксессуары"),
        ),
        "Tennis": (
            ("rackets", "Ракетки"),
            ("apparel", "Одежда"),
            ("shoes", "Обувь"),
            ("bags", "Сумки"),
            ("balls", "Мячи"),
            ("strings", "Струны"),
            ("accessories", "Аксессуары"),
        ),
        "Running": (
            ("shoes", "Обувь"),
            ("apparel", "Одежда"),
            ("accessories", "Аксессуары"),
        ),
    }


# Проверяет, что pricing не теряет и не добавляет storefront-группы.
def test_pricing_group_count_matches_storefront_count() -> None:
    storefront_count = sum(len(items) for items in CATALOG_SUBCATEGORIES.values())

    assert len(iter_pricing_groups()) == storefront_count


# У каждой карточки группы в админке есть своя иконка.
def test_pricing_groups_have_admin_icons() -> None:
    group_slugs = {group.subcategory_slug for group in iter_pricing_groups()}

    assert group_slugs <= ADMIN_ICONS.keys()


# Разрешает товар в одну точную storefront-группу.
def test_resolve_pricing_group_exact() -> None:
    resolution = resolve_pricing_group("Padel", "Padel balls")

    assert resolution.subcategory_slug == "balls"
    assert resolution.matched_subcategory_slugs == ("balls",)
    assert resolution.is_exact is True
    assert resolution.reason is None


# Отправляет неизвестную storefront-категорию в fallback.
def test_resolve_pricing_group_fallback() -> None:
    resolution = resolve_pricing_group("Padel", "Unknown supplier group")

    assert resolution.subcategory_slug == FALLBACK_SUBCATEGORY_SLUG
    assert resolution.matched_subcategory_slugs == ()
    assert resolution.is_exact is False
    assert resolution.reason == "no_storefront_group"


# Не выбирает случайную группу при нескольких совпадениях.
def test_resolve_pricing_group_multiple_matches(monkeypatch) -> None:
    duplicate = CatalogSubCategoryDef(
        "duplicate",
        "Дубликат",
        ("Padel balls",),
    )
    monkeypatch.setitem(
        pricing_groups.CATALOG_SUBCATEGORIES,
        "Padel",
        (*CATALOG_SUBCATEGORIES["Padel"], duplicate),
    )

    resolution = resolve_pricing_group("Padel", "Padel balls")

    assert resolution.subcategory_slug == FALLBACK_SUBCATEGORY_SLUG
    assert resolution.matched_subcategory_slugs == ("balls", "duplicate")
    assert resolution.is_exact is False
    assert resolution.reason == "multiple_storefront_groups"
