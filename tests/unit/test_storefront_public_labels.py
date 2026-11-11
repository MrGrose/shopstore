from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.catalog.display.catalog_read import StorefrontCatalogReadService
from src.services.catalog.display.constants import NODE_TYPE_ROOT
from src.services.catalog.display.seed import StorefrontGreenfieldSeeder
from src.services.catalog.display.ux_blueprint import (
    StorefrontUxBlueprintError,
    _validate_node,
    load_storefront_ux_blueprint,
)


def test_ux_blueprint_public_nodes_have_cyrillic_label_ru() -> None:
    blueprint = load_storefront_ux_blueprint()
    for node in blueprint["nodes"]:
        label = str(node["label_ru"]).strip()
        assert label
        assert any("\u0400" <= ch <= "\u04ff" for ch in label), node["display_key"]


def test_ux_blueprint_sport_root_labels_are_russian() -> None:
    blueprint = load_storefront_ux_blueprint()
    roots = {
        n["display_key"]: n["label_ru"]
        for n in blueprint["nodes"]
        if n["node_type"] == NODE_TYPE_ROOT
    }
    assert roots["tennis"] == "Теннис"
    assert roots["padel"] == "Падел"
    assert roots["running"] == "Бег"


def test_ux_blueprint_rejects_empty_label_ru() -> None:
    node = dict(load_storefront_ux_blueprint()["nodes"][0])
    node["label_ru"] = "   "
    with pytest.raises(StorefrontUxBlueprintError, match="label_ru"):
        _validate_node(node, 0)


def test_ux_blueprint_rejects_forbidden_english_public_label() -> None:
    node = dict(load_storefront_ux_blueprint()["nodes"][0])
    node["label_ru"] = "Shoes"
    with pytest.raises(StorefrontUxBlueprintError, match="forbidden"):
        _validate_node(node, 0)


@pytest.mark.asyncio
async def test_seed_insert_blueprint_node_requires_label_ru() -> None:
    seeder = StorefrontGreenfieldSeeder(session=MagicMock())
    seeder.session.flush = AsyncMock()
    with pytest.raises(ValueError, match="label_ru"):
        await seeder._insert_blueprint_node(
            1,
            {
                "display_key": "bad",
                "node_type": NODE_TYPE_ROOT,
                "sport_type": "Tennis",
                "slug": "bad",
                "sort_order": 1,
            },
            {},
            expected_type=NODE_TYPE_ROOT,
            parent_id=None,
        )


@pytest.mark.asyncio
async def test_build_taxonomy_uses_label_ru_for_public_labels() -> None:
    root = MagicMock()
    root.id = 1
    root.node_type = NODE_TYPE_ROOT
    root.sport_type = "Tennis"
    root.slug = "tennis"
    root.label_ru = "Теннис"
    root.parent_id = None

    section = MagicMock()
    section.id = 2
    section.node_type = "section"
    section.parent_id = 1
    section.slug = "rackets"
    section.label_ru = "Ракетки"

    chip = MagicMock()
    chip.node_type = "chip"
    chip.parent_id = 2
    chip.display_key = "tennis.rackets.tennis-rackets"
    chip.slug = "tennis-rackets"
    chip.label_ru = "Теннисные ракетки"

    session = MagicMock()
    svc = StorefrontCatalogReadService(session)
    svc.repo.load_taxonomy_nodes = AsyncMock(return_value=[root, section, chip])

    payload = await svc.build_taxonomy(release_id=1)
    sport = payload["sports"][0]
    assert sport["label"] == "Теннис"
    assert sport["sections"][0]["label"] == "Ракетки"
    assert sport["sections"][0]["chips"][0]["label"] == "Теннисные ракетки"
