import unittest

from sqlalchemy.dialects import postgresql

from src.models.product import Product
from src.repositories.product_repo import (
    is_product_external_code_query,
    normalize_product_search_query,
    parse_product_id_query,
    product_external_code_filter,
    product_search_filter,
)


class ProductSearchQueryTests(unittest.TestCase):
    def test_normalize_strips_and_removes_hash(self) -> None:
        self.assertEqual(normalize_product_search_query("  #12871 "), "12871")
        self.assertIsNone(normalize_product_search_query("   "))
        self.assertIsNone(normalize_product_search_query(None))

    def test_parse_product_id_query(self) -> None:
        self.assertEqual(parse_product_id_query("12700"), 12700)
        self.assertEqual(parse_product_id_query("#42"), 42)
        self.assertIsNone(parse_product_id_query("head"))
        self.assertIsNone(parse_product_id_query("12ab"))
        self.assertIsNone(parse_product_id_query("1994750094200020"))

    def test_external_code_query_detects_long_barcode(self) -> None:
        self.assertTrue(is_product_external_code_query("1994750094200020"))
        self.assertFalse(is_product_external_code_query("12700"))
        self.assertFalse(is_product_external_code_query("head"))

    def test_external_code_filter_matches_external_id_and_sku(self) -> None:
        clause = product_external_code_filter(Product, "1994750094200020")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("products.external_id", sql)
        self.assertIn("product_variants", sql)
        self.assertIn("sku", sql)

    def test_filter_includes_title_brand_id_and_sku_exists(self) -> None:
        clause = product_search_filter(Product, "head")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("products.title", sql)
        self.assertIn("products.brand", sql)
        self.assertIn("products.external_id", sql)
        self.assertIn("products.id", sql)
        self.assertIn("exists", sql)
        self.assertIn("product_variants", sql)
        self.assertIn("sku", sql)

    def test_filter_adds_exact_id_for_digits(self) -> None:
        clause = product_search_filter(Product, "42")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("products.id = 42", sql)

    def test_filter_skips_exact_id_when_out_of_pg_int_range(self) -> None:
        clause = product_search_filter(Product, "1994750094200020")
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertNotIn("products.id = 1994750094200020", sql)
        self.assertIn("products.external_id", sql.lower())


if __name__ == "__main__":
    unittest.main()
