from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel, Field, computed_field

from src.schemas.product import ProductPublicCardSchema, ProductPublicListSchema
from src.utils.pagination import catalog_total_pages

ADMIN_BRANDS_PAGE_SIZE = 20


class AdminBrandRow(TypedDict):
    brand: str
    product_count: int
    storefront_visible: bool


class CatalogFacetOptionSchema(BaseModel):
    value: str
    label_ru: str
    count: int = Field(..., ge=0)


class CatalogProductCountSchema(BaseModel):
    total: int = Field(..., ge=0)


class CatalogFacetsSchema(BaseModel):
    brands: list[CatalogFacetOptionSchema] = Field(default_factory=list)
    genders: list[CatalogFacetOptionSchema] = Field(default_factory=list)
    colors: list[CatalogFacetOptionSchema] = Field(default_factory=list)
    sizes: list[CatalogFacetOptionSchema] = Field(default_factory=list)
    price_min: Decimal | None = None
    price_max: Decimal | None = None


class CatalogProductMetaSchema(BaseModel):
    total: int = Field(..., ge=0)
    facets: CatalogFacetsSchema


@dataclass(frozen=True)
class CatalogFilterSelection:
    top_categories: list[str]
    selected_top: str
    categories: list[str]
    selected_category: str | None
    brands: list[str]
    selected_brand: str | None
    selected_gender: str | None = None
    selected_color: str | None = None
    selected_size: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None


class CatalogPageState(BaseModel):
    items: list[ProductPublicCardSchema] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    top_categories: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    selected_top: str
    selected_category: str | None = None
    selected_brand: str | None = None
    selected_gender: str | None = None
    selected_color: str | None = None
    selected_size: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    catalog_summary: dict[str, int] | None = None
    show_out_of_stock: bool = False
    show_zero_stock: bool = False
    show_removed: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def total_pages(self) -> int:
        return catalog_total_pages(self.total, self.page_size)

    def to_public_list_schema(self) -> ProductPublicListSchema:
        return ProductPublicListSchema(
            items=self.items,
            total=self.total,
            has_more=self.page * self.page_size < self.total,
            page=self.page,
            page_size=self.page_size,
        )
