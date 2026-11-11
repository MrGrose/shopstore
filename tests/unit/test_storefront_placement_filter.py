from unittest.mock import MagicMock

from src.models.product import Product
from src.repositories.product_repo import CrudProduct


def _repo() -> CrudProduct:
    return CrudProduct(session=MagicMock(), model=Product)


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


def test_global_chip_node_ids_none_uses_placement_exists() -> None:
    repo = _repo()
    filters: list = []
    repo._append_storefront_placement_filters(
        filters,
        release_id=1,
        chip_node_ids=None,
        top_category="All",
    )
    assert len(filters) == 2


def test_product_id_search_still_requires_placement_filter() -> None:
    repo = _repo()
    filters: list = []
    repo._append_storefront_placement_filters(
        filters,
        release_id=1,
        chip_node_ids=(10, 11),
        q="12345",
    )
    assert len(filters) == 2


def test_external_code_search_still_requires_placement_filter() -> None:
    repo = _repo()
    filters: list = []
    repo._append_storefront_placement_filters(
        filters,
        release_id=1,
        chip_node_ids=(10,),
        q="SKU-ABC-123",
    )
    assert len(filters) >= 2
