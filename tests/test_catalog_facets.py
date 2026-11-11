from decimal import Decimal

from src.schemas.catalog import CatalogFacetOptionSchema, CatalogFacetsSchema
from src.utils.labels import normalize_gender, translate_gender


def test_normalize_gender_aliases() -> None:
    assert normalize_gender("Men's") == "men"
    assert normalize_gender("WOMAN") == "women"
    assert normalize_gender("unknown") is None


def test_translate_gender_ru() -> None:
    assert translate_gender("men") == "Мужской"
    assert translate_gender("kids") == "Детский"


def test_catalog_facets_schema() -> None:
    payload = CatalogFacetsSchema(
        brands=[
            CatalogFacetOptionSchema(value="Babolat", label_ru="Babolat", count=5),
        ],
        genders=[
            CatalogFacetOptionSchema(value="men", label_ru="Мужской", count=3),
        ],
        colors=[
            CatalogFacetOptionSchema(value="Black", label_ru="Black", count=2),
        ],
        sizes=[],
        price_min=Decimal("1000"),
        price_max=Decimal("50000"),
    )
    assert payload.genders[0].count == 3
    assert payload.price_max == Decimal("50000")
