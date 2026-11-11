from pydantic import BaseModel, Field


class CatalogLabelSchema(BaseModel):
    key: str
    label_ru: str = Field(..., description="Подпись для UI (рус.)")


class CatalogSubCategoryTypeSchema(BaseModel):
    key: str
    label_ru: str
    count: int = Field(..., ge=0)


class CatalogSubCategorySchema(BaseModel):
    slug: str
    label: str
    type_level: str = Field(default="chip", pattern="^(l2|l3|chip)$")
    types: list[CatalogSubCategoryTypeSchema] = Field(default_factory=list)


class CatalogLabelsDictSchema(BaseModel):
    sport_types: dict[str, str] = Field(default_factory=dict)
    category_l2: dict[str, str] = Field(default_factory=dict)
    category_l3: dict[str, str] = Field(default_factory=dict)
    genders: dict[str, str] = Field(default_factory=dict)
    filter_all: str = "Все"
    product_fallback: str = "Товар"


class CatalogTaxonomySubSchema(BaseModel):
    slug: str
    label: str
    category_l2: list[str] = Field(default_factory=list)


class CatalogTaxonomyChipSchema(BaseModel):
    display_key: str
    slug: str
    label: str


class CatalogTaxonomySectionSchema(BaseModel):
    slug: str
    label: str
    chips: list[CatalogTaxonomyChipSchema] = Field(default_factory=list)


class CatalogTaxonomySportSchema(BaseModel):
    sport: str
    slug: str
    label: str
    sections: list[CatalogTaxonomySectionSchema] = Field(default_factory=list)
    subcategories: list[CatalogTaxonomySubSchema] = Field(default_factory=list)


class CatalogTaxonomySchema(BaseModel):
    sports: list[CatalogTaxonomySportSchema] = Field(default_factory=list)
    sub_slug_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)


class CatalogNavigationLinkSchema(BaseModel):
    label: str
    url_params: dict[str, str] = Field(default_factory=dict)


class CatalogNavigationActiveNodeSchema(BaseModel):
    sub: str = ""
    category_type: str = ""
    section_label: str | None = None
    type_label: str | None = None


class CatalogNavigationSchema(BaseModel):
    top_category: str
    use_mapping_params: bool = True
    sub: str = ""
    category_type: str = ""
    url_params: dict[str, str] = Field(default_factory=dict)
    active_node: CatalogNavigationActiveNodeSchema | None = None
    breadcrumbs: list[CatalogNavigationLinkSchema] = Field(default_factory=list)
    subcategories: list[CatalogSubCategorySchema] = Field(default_factory=list)
