import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.selectable import Exists

from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.services.catalog.display.compat_params import (
    StorefrontCompatParamError,
    StorefrontCompatParams,
    StorefrontNodeFilter,
)
from src.services.catalog.display.runtime import resolve_catalog_query_context
from src.services.catalog.read.scope import (
    CATALOG_ALL_TOP_CATEGORY,
    UnknownCatalogTopCategoryError,
    encode_placement_chip_ids_for_cache,
    resolve_public_catalog_top_category,
)


def _repo() -> CrudProduct:
    return CrudProduct(session=MagicMock(), model=Product)


def test_resolve_public_catalog_top_category_all_and_missing() -> None:
    assert resolve_public_catalog_top_category(None) == CATALOG_ALL_TOP_CATEGORY
    assert resolve_public_catalog_top_category("") == CATALOG_ALL_TOP_CATEGORY
    assert resolve_public_catalog_top_category("all") == CATALOG_ALL_TOP_CATEGORY
    assert resolve_public_catalog_top_category("All") == CATALOG_ALL_TOP_CATEGORY


def test_resolve_public_catalog_top_category_sports() -> None:
    assert resolve_public_catalog_top_category("Padel") == "Padel"
    assert resolve_public_catalog_top_category("Tennis") == "Tennis"
    assert resolve_public_catalog_top_category("Running") == "Running"


def test_resolve_public_catalog_top_category_unknown_raises() -> None:
    with pytest.raises(UnknownCatalogTopCategoryError, match="Football"):
        resolve_public_catalog_top_category("Football")


def test_encode_placement_chip_ids_for_cache_distinguishes_none_and_empty() -> None:
    assert encode_placement_chip_ids_for_cache(None) == "__global__"
    assert encode_placement_chip_ids_for_cache(()) == "__empty__"
    assert encode_placement_chip_ids_for_cache((1, 2)) == [1, 2]


def test_global_chip_node_ids_none_adds_exists_not_sentinel() -> None:
    repo = _repo()
    filters: list = []
    repo._append_storefront_placement_filters(
        filters,
        release_id=1,
        chip_node_ids=None,
        top_category=CATALOG_ALL_TOP_CATEGORY,
    )
    assert len(filters) == 2
    assert isinstance(filters[1], Exists)


def test_empty_chip_node_ids_returns_zero_products_filter() -> None:
    repo = _repo()
    filters: list = []
    repo._append_storefront_placement_filters(
        filters,
        release_id=1,
        chip_node_ids=(),
        top_category="Padel",
    )
    assert len(filters) == 2


@pytest.mark.asyncio
async def test_resolve_catalog_query_context_unknown_top_returns_400() -> None:
    session = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await resolve_catalog_query_context(session, top_category="Football")
    assert exc.value.status_code == 400


def test_global_scope_paths_have_no_legacy_catalog_slice_imports() -> None:
    paths = [
        Path("src/services/catalog/display/compat_params.py"),
        Path("src/services/catalog/display/runtime.py"),
    ]
    forbidden_modules = ("src.services.catalog.display.catalog_slice",)
    forbidden_tokens = ("CatalogRawSlice", "storefront_nav")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        for mod in forbidden_modules:
            assert mod not in modules, f"{path} imports {mod}"
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{path} references {token}"


@pytest.mark.asyncio
async def test_compat_params_global_all_skips_descendant_lookup(monkeypatch) -> None:
    compat = StorefrontCompatParams(session=MagicMock())
    compat.repo.descendant_chip_ids = MagicMock()

    async def _resolve_filter(release_id: int, top_category, section, node):
        return await compat.resolve_filter(release_id, top_category, section, node)

    result = await _resolve_filter(1, "All", None, None)
    assert isinstance(result, StorefrontNodeFilter)
    assert result.chip_node_ids is None
    compat.repo.descendant_chip_ids.assert_not_called()


@pytest.mark.asyncio
async def test_compat_params_section_with_all_scope_rejected() -> None:
    compat = StorefrontCompatParams(session=MagicMock())
    with pytest.raises(StorefrontCompatParamError, match="section/node"):
        await compat.resolve_filter(1, "All", "rackets", None)
