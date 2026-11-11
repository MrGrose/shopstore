from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.services.catalog.read.sort import normalize_admin_sort


def test_normalize_admin_sort_legacy_price() -> None:
    assert normalize_admin_sort(None, "asc") == "price_asc"
    assert normalize_admin_sort(None, "desc") == "price_desc"


def test_normalize_admin_sort_values() -> None:
    assert normalize_admin_sort("stock_desc", None) == "stock_desc"
    assert normalize_admin_sort("id_asc", None) == "id_asc"
    assert normalize_admin_sort("invalid", None) is None


def test_catalog_order_clause_admin_sort() -> None:
    repo = CrudProduct(session=None, model=Product)
    assert repo._catalog_order_clause(admin_sort="stock_desc") is not None
    assert repo._catalog_order_clause(admin_sort="synced_desc") is not None
    assert repo._catalog_order_clause(sort_price="asc") is not None
