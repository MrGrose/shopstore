import unittest

from sqlalchemy.dialects import postgresql

from src.core.stock_display import variant_buyable_sql_clause
from src.models.product import Product, ProductVariant
from src.repositories.product_repo import CrudProduct, product_search_filter
from src.services.catalog.read.catalog_search import resolve_catalog_search_hit


class CatalogSearchResolverTests(unittest.TestCase):
    def test_slipover_typo_matches_display_slice(self) -> None:
        hit = resolve_catalog_search_hit("слиппоны")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(
            any(slice_.category_l3 == "Slipover" for slice_ in hit.raw_slices),
        )

    def test_hoodies_group_label_matches(self) -> None:
        hit = resolve_catalog_search_hit("толстовки")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.raw_slices)

    def test_subcategory_label_matches_apparel_l2(self) -> None:
        hit = resolve_catalog_search_hit("одежда")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(
            any(slice_.category_l2 == "Shirts" for slice_ in hit.raw_slices)
        )

    def test_short_query_ignored(self) -> None:
        self.assertIsNone(resolve_catalog_search_hit("ми"))


class CatalogSearchFilterTests(unittest.TestCase):
    def test_product_search_matches_product_text_fields(self) -> None:
        clause = product_search_filter(Product, "слипоны")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("products.title", sql)
        self.assertIn("products.brand", sql)
        self.assertIn("product_variants.sku", sql)

    def test_product_search_does_not_match_category_columns(self) -> None:
        clause = product_search_filter(Product, "слипоны")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertNotIn("category_l2", sql)
        self.assertNotIn("category_l3", sql)


class CatalogVariantBuyableFilterTests(unittest.TestCase):
    def test_variant_buyable_clause_requires_available_stock(self) -> None:
        clause = variant_buyable_sql_clause(ProductVariant)
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("available", sql)
        self.assertIn("inventory_quantity", sql)

    def test_color_exists_filter_uses_buyable_clause(self) -> None:
        repo = CrudProduct(session=None, model=Product)
        clause = repo._color_exists_filter("black")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("available", sql)
        self.assertIn("inventory_quantity", sql)

    def test_size_exists_filter_uses_buyable_clause(self) -> None:
        repo = CrudProduct(session=None, model=Product)
        clause = repo._size_exists_filter("43")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("available", sql)
        self.assertIn("inventory_quantity", sql)


if __name__ == "__main__":
    unittest.main()
