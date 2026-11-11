from types import SimpleNamespace

import pytest

from src.repositories.storefront_mapping import (
    StorefrontChipLookupAmbiguousError,
    match_chip_nodes,
    resolve_chip_node_match,
)


def _chip(
    chip_id: int,
    display_key: str,
    slug: str,
    legacy: list[str] | None = None,
    parent_id: int = 10,
) -> SimpleNamespace:
    meta = {"legacy_query_keys": legacy} if legacy else None
    return SimpleNamespace(
        id=chip_id,
        display_key=display_key,
        slug=slug,
        parent_id=parent_id,
        metadata_json=meta,
    )


def test_match_chip_nodes_finds_legacy_key() -> None:
    nodes = [
        _chip(
            1, "tennis.overgrips.type-overgrips", "type-overgrips", ["tennis.overgrips"]
        ),
    ]
    matches = match_chip_nodes(nodes, "tennis.overgrips")
    assert len(matches) == 1
    assert matches[0].id == 1


def test_resolve_chip_node_match_raises_when_ambiguous_without_section() -> None:
    nodes = [
        _chip(1, "tennis.a.x", "x", ["tennis.overgrips"]),
        _chip(2, "tennis.b.y", "y", ["tennis.overgrips"]),
    ]
    matches = match_chip_nodes(nodes, "tennis.overgrips")
    with pytest.raises(StorefrontChipLookupAmbiguousError):
        resolve_chip_node_match(matches, "tennis.overgrips", "Tennis", None)


def test_resolve_chip_node_match_returns_single_match() -> None:
    nodes = [
        _chip(
            1, "tennis.overgrips.type-overgrips", "type-overgrips", ["tennis.overgrips"]
        )
    ]
    matches = match_chip_nodes(nodes, "tennis.overgrips")
    resolved = resolve_chip_node_match(matches, "tennis.overgrips", "Tennis", None)
    assert resolved is not None
    assert resolved.id == 1
