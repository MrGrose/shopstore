from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from src.core.stock_display import variant_buyable_qty
from src.schemas.money import ceil_rub, format_eur
from src.services.catalog.shoe_size_guide import brand_has_size_chart
from src.utils.images import (
    coerce_public_product_media_url,
    public_product_media_url,
    resolve_stored_product_image,
)
from src.utils.labels import (
    display_product_title,
    is_footwear_category,
    is_redundant_surface_option,
    product_sport_badge_label_ru,
    resolve_variant_option_label,
    translate_category_l2,
    translate_category_l3,
    translate_feature_name,
    translate_feature_value,
    translate_gender,
    translate_option_value,
)
from src.utils.pagination import catalog_total_pages
from src.utils.variant_sort import sort_option_values_from_variants

PUBLIC_CARD_GALLERY_LIMIT = 5


def _public_stock_fields(available_stock: int) -> tuple[int, str]:
    from src.core.stock_display import storefront_stock_status_key

    qty = max(0, int(available_stock))
    return qty, storefront_stock_status_key(qty)


# Схема ответа с данными товара.
class ProductImageSchema(BaseModel):
    id: int
    url: str
    alt: str | None = None
    position: int
    fallback_url: str | None = None

    model_config = ConfigDict(from_attributes=True)

    # Собирает display URL: managed S3, иначе CDN.
    @model_validator(mode="before")
    @classmethod
    def resolve_display_urls(cls, data: Any) -> Any:
        if not hasattr(data, "url"):
            return data
        primary, fallback = resolve_stored_product_image(
            getattr(data, "url", None),
            getattr(data, "source_url", None),
        )
        if not primary:
            return {
                "id": getattr(data, "id", 0),
                "url": "",
                "alt": getattr(data, "alt", None),
                "position": getattr(data, "position", 0),
                "fallback_url": None,
            }
        return {
            "id": data.id,
            "url": public_product_media_url(primary) or primary,
            "alt": data.alt,
            "position": data.position,
            "fallback_url": fallback,
        }


# Убирает gallery rows без display URL.
def _drop_blank_product_images(
    images: list[ProductImageSchema],
) -> list[ProductImageSchema]:
    return [item for item in images if item.url]


# Узкий URL галереи для карточки каталога.
class ProductPublicCardImageSchema(BaseModel):
    url: str
    fallback_url: str | None = None
    position: int


# Берёт url/source_url/position из ORM, dict или schema.
def _card_image_row_fields(item: Any) -> tuple[str | None, str | None, int]:
    if isinstance(item, dict):
        return (
            item.get("url"),
            item.get("source_url"),
            int(item.get("position") or 0),
        )
    return (
        getattr(item, "url", None),
        getattr(item, "source_url", None),
        int(getattr(item, "position", 0) or 0),
    )


# Supplier fallback с повторной валидации карточки.
def _card_image_existing_fallback(item: Any) -> str | None:
    raw = (
        item.get("fallback_url")
        if isinstance(item, dict)
        else getattr(item, "fallback_url", None)
    )
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


# Карточка: managed URL через public base, fallback — supplier как есть.
def _public_card_gallery_images(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        stored_url, source_url, position = _card_image_row_fields(item)
        primary, fallback = resolve_stored_product_image(stored_url, source_url)
        if not primary:
            continue
        if fallback is None and not source_url:
            fallback = _card_image_existing_fallback(item)
        exposed = public_product_media_url(primary) or primary
        rows.append({"url": exposed, "fallback_url": fallback, "position": position})
    rows.sort(key=lambda row: int(row["position"]))
    return rows[:PUBLIC_CARD_GALLERY_LIMIT]


class ProductFeatureSchema(BaseModel):
    id: int
    name: str
    value: str | None = None
    icon_url: str | None = None
    position: int

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def name_ru(self) -> str:
        return translate_feature_name(self.name)

    @computed_field  # type: ignore[misc]
    @property
    def value_ru(self) -> str:
        return translate_feature_value(self.name, self.value)


class ProductVariantSchema(BaseModel):
    id: int
    variant_external_id: str | None = None
    sku: str | None = None
    option1: str | None = None
    option2: str | None = None
    option3: str | None = None
    price: Decimal | None = None
    compare_at_price: Decimal | None = None
    inventory_quantity: int
    available: bool
    available_quantity: int | None = None
    option1_sort_key: Decimal | None = Field(default=None, exclude=True)
    option2_sort_key: Decimal | None = Field(default=None, exclude=True)
    option3_sort_key: Decimal | None = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("price", "compare_at_price", mode="before")
    @classmethod
    def round_variant_money_up(cls, value: Decimal | None) -> Decimal | None:
        return ceil_rub(value)

    @computed_field  # type: ignore[misc]
    @property
    def option1_ru(self) -> str:
        return translate_option_value(self.option1)

    @computed_field  # type: ignore[misc]
    @property
    def option2_ru(self) -> str:
        return translate_option_value(self.option2)

    @computed_field  # type: ignore[misc]
    @property
    def option3_ru(self) -> str:
        return translate_option_value(self.option3)

    @computed_field  # type: ignore[misc]
    @property
    def buyable_qty(self) -> int:
        return variant_buyable_qty(
            inventory_quantity=self.inventory_quantity,
            available=self.available,
            available_quantity=self.available_quantity,
        )

    @computed_field  # type: ignore[misc]
    @property
    def stock_status(self) -> str:
        _, status = _public_stock_fields(self.buyable_qty)
        return status


def _variant_option_values(
    variants: list[ProductVariantSchema],
) -> dict[str, list[str]]:
    collected: dict[str, list[str]] = {
        "option1": [],
        "option2": [],
        "option3": [],
    }
    for variant in variants:
        for key in collected:
            raw = getattr(variant, key, None)
            text = str(raw or "").strip()
            if text and text not in collected[key]:
                collected[key].append(text)
    for key, values in collected.items():
        collected[key] = sort_option_values_from_variants(
            variants,
            key,
            values,
        )
    return collected


def _variant_option_value_labels(
    variants: list[ProductVariantSchema],
) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    for key, values in _variant_option_values(variants).items():
        if not values:
            continue
        labels[key] = {value: translate_option_value(value) for value in values}
    return labels


def _variant_display_titles(
    title: str,
    variants: list[ProductVariantSchema],
) -> dict[str, str]:
    base = display_product_title(title)
    out: dict[str, str] = {}
    for variant in variants:
        out[str(variant.id)] = (
            display_product_title(
                base,
                option1=variant.option1,
                option2=variant.option2,
                option3=variant.option3,
            )
            or base
        )
    return out


class ProductSchema(BaseModel):
    id: int
    title: str
    brand: str
    description: str | None = None
    image_url: str | None = None
    sale_price: Decimal
    regular_price: Decimal
    product_url: str
    is_active: bool
    stock: int
    available_stock: int | None = None
    external_id: str | None = None
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    sport_type: str | None = None
    trade_group: str | None = None
    gender: str | None = None
    shipping_estimate: str | None = None
    catalog_synced_at: datetime | None = None
    variants: list[ProductVariantSchema] = Field(default_factory=list)
    images: list[ProductImageSchema] = Field(default_factory=list)
    features: list[ProductFeatureSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    # Прячет gallery rows без display URL.
    @field_validator("images")
    @classmethod
    def drop_blank_product_images(
        cls, value: list[ProductImageSchema]
    ) -> list[ProductImageSchema]:
        return _drop_blank_product_images(value)

    @field_validator("sale_price", "regular_price", mode="before")
    @classmethod
    def round_product_money_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")

    @computed_field  # type: ignore[misc]
    @property
    def display_title(self) -> str:
        return display_product_title(self.title)


# Публичная схема товара для клиентов без поля stock.
class ProductPublicSchema(BaseModel):
    id: int
    title: str
    brand: str
    description: str | None = None
    image_url: str | None = None
    sale_price: Decimal
    regular_price: Decimal
    product_url: str
    is_active: bool
    available_stock: int = 0
    external_id: str | None = None
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    sport_type: str | None = None
    trade_group: str | None = None
    gender: str | None = None
    shipping_estimate: str | None = None
    variants: list[ProductVariantSchema] = Field(default_factory=list)
    images: list[ProductImageSchema] = Field(default_factory=list)
    features: list[ProductFeatureSchema] = Field(default_factory=list)

    @field_validator("image_url", mode="before")
    @classmethod
    def expose_public_product_media(cls, value: Any) -> Any:
        return coerce_public_product_media_url(value)

    model_config = ConfigDict(from_attributes=True)

    # Прячет gallery rows без display URL.
    @field_validator("images")
    @classmethod
    def drop_blank_public_images(
        cls, value: list[ProductImageSchema]
    ) -> list[ProductImageSchema]:
        return _drop_blank_product_images(value)

    @field_validator("sale_price", "regular_price", mode="before")
    @classmethod
    def round_public_product_money_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")

    @computed_field  # type: ignore[misc]
    @property
    def buyable_qty(self) -> int:
        return _public_stock_fields(self.available_stock)[0]

    @computed_field  # type: ignore[misc]
    @property
    def stock_status(self) -> str:
        return _public_stock_fields(self.available_stock)[1]

    @computed_field  # type: ignore[misc]
    @property
    def sport_type_label_ru(self) -> str:
        return product_sport_badge_label_ru(
            self.sport_type,
            self.category_l1,
            self.category_l2,
            self.category_l3,
        )

    @computed_field  # type: ignore[misc]
    @property
    def category_l2_label_ru(self) -> str:
        return translate_category_l2(self.category_l2)

    @computed_field  # type: ignore[misc]
    @property
    def category_l3_label_ru(self) -> str:
        return translate_category_l3(self.category_l3)

    @computed_field  # type: ignore[misc]
    @property
    def gender_label_ru(self) -> str:
        return translate_gender(self.gender)

    @computed_field  # type: ignore[misc]
    @property
    def display_title(self) -> str:
        return display_product_title(self.title)

    @computed_field  # type: ignore[misc]
    @property
    def variant_option_labels(self) -> dict[str, str]:
        values = _variant_option_values(self.variants)
        return {
            key: resolve_variant_option_label(
                key,
                category_l2=self.category_l2,
                option_values=values[key],
            )
            for key in values
            if values[key]
        }

    @computed_field  # type: ignore[misc]
    @property
    def variant_option_values(self) -> dict[str, list[str]]:
        return _variant_option_values(self.variants)

    @computed_field  # type: ignore[misc]
    @property
    def variant_option_values_ru(self) -> dict[str, dict[str, str]]:
        return _variant_option_value_labels(self.variants)

    @computed_field  # type: ignore[misc]
    @property
    def variant_options_hidden(self) -> list[str]:
        values = _variant_option_values(self.variants)
        return [
            key
            for key, opts in values.items()
            if opts and is_redundant_surface_option(self.category_l2, key, opts)
        ]

    @computed_field  # type: ignore[misc]
    @property
    def variant_display_titles(self) -> dict[str, str]:
        return _variant_display_titles(self.title, self.variants)

    @computed_field  # type: ignore[misc]
    @property
    def show_shoe_size_guide(self) -> bool:
        if not is_footwear_category(self.category_l2, self.category_l3):
            return False
        return brand_has_size_chart(self.brand)


# Схема ответа списка товаров с пагинацией.
class ProductListSchema(BaseModel):
    items: list[ProductSchema] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)


# Публичная карточка товара для выдачи в списках.
class ProductPublicCardSchema(BaseModel):
    id: int
    title: str
    brand: str
    description: str | None = None
    image_url: str | None = None
    images: list[ProductPublicCardImageSchema] = Field(default_factory=list)
    sale_price: Decimal
    regular_price: Decimal
    product_url: str
    is_active: bool
    available_stock: int = 0
    external_id: str | None = None
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    sport_type: str | None = None
    trade_group: str | None = None
    gender: str | None = None
    shipping_estimate: str | None = None
    catalog_synced_at: datetime | None = None
    storefront_mapping_status: str = "not_sellable"
    catalog_inclusion: str = Field(default="included", exclude=True)
    storefront_site: str = Field(default="none", exclude=True)
    storefront_hide_reasons: list[str] = Field(default_factory=list, exclude=True)
    supplier_price_eur: Decimal = Field(default=Decimal("0"), exclude=True)

    @field_validator("image_url", mode="before")
    @classmethod
    def expose_public_product_media(cls, value: Any) -> Any:
        return coerce_public_product_media_url(value)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("supplier_price_eur", mode="before")
    @classmethod
    def normalize_public_card_supplier_eur(
        cls, value: Decimal | float | int | None
    ) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    # Сортирует gallery по position и обрезает до 5 URL.
    @field_validator("images", mode="before")
    @classmethod
    def cap_public_card_gallery(cls, value: Any) -> list[dict[str, Any]]:
        return _public_card_gallery_images(value)

    @field_validator("sale_price", "regular_price", mode="before")
    @classmethod
    def round_public_card_money_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")

    @computed_field  # type: ignore[misc]
    @property
    def buyable_qty(self) -> int:
        return _public_stock_fields(self.available_stock)[0]

    @computed_field  # type: ignore[misc]
    @property
    def stock_status(self) -> str:
        return _public_stock_fields(self.available_stock)[1]

    @computed_field  # type: ignore[misc]
    @property
    def sport_type_label_ru(self) -> str:
        return product_sport_badge_label_ru(
            self.sport_type,
            self.category_l1,
            self.category_l2,
            self.category_l3,
        )

    @computed_field  # type: ignore[misc]
    @property
    def category_l2_label_ru(self) -> str:
        return translate_category_l2(self.category_l2)

    @computed_field  # type: ignore[misc]
    @property
    def category_l3_label_ru(self) -> str:
        return translate_category_l3(self.category_l3)

    @computed_field  # type: ignore[misc]
    @property
    def gender_label_ru(self) -> str:
        return translate_gender(self.gender)

    @computed_field  # type: ignore[misc]
    @property
    def display_title(self) -> str:
        return display_product_title(self.title)


# Схема публичного списка товаров с пагинацией.
class ProductPublicListSchema(BaseModel):
    items: list[ProductPublicCardSchema] = Field(default_factory=list)
    total: int | None = Field(default=None, ge=0)
    has_more: bool = False
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)

    @computed_field  # type: ignore[misc]
    @property
    def total_pages(self) -> int | None:
        if self.total is None:
            return None
        return catalog_total_pages(self.total, self.page_size)


# Схема создания нового товара.
class ProductCreate(BaseModel):
    title: str
    brand: str | None = None
    description: str | None = None
    sale_price: Decimal
    regular_price: Decimal = Decimal("0")
    product_url: str
    image_url: str | None = None
    stock: int = 0
    is_active: bool = True


# Вариант товара для админки: резерв и доступно по SKU.
class ProductAdminVariantSchema(ProductVariantSchema):
    reserved_stock: int = 0
    available_for_sale: int = 0


class ProductAdminOrderRowSchema(BaseModel):
    order_id: int
    created_at: datetime | None = None
    status: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


# Расширенная схема товара для админ-панели (EUR/snapshot, резерв).
class ProductAdminSchema(ProductSchema):
    variants: list[ProductAdminVariantSchema] = Field(default_factory=list)
    supplier_price_eur: Decimal = Decimal("0")
    eur_rate_snapshot: Decimal | None = None
    margin_snapshot_percent: Decimal | None = None
    markup_snapshot: Decimal | None = None
    reserved_stock: int = 0
    current_eur_rate: Decimal | None = None
    dom_last_error: str | None = None
    catalog_synced_at_display: str | None = None
    storefront_mapping_status: str = "not_sellable"
    storefront_mapping_status_label_ru: str = ""
    storefront_mapping_orphan_reason: str | None = None
    catalog_in_stock: bool = False
    catalog_inclusion: str = "included"
    storefront_site: str = "none"
    storefront_hide_reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("supplier_price_eur", mode="before")
    @classmethod
    def normalize_supplier_price_eur(
        cls, value: Decimal | float | int | None
    ) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    @field_validator(
        "eur_rate_snapshot",
        "margin_snapshot_percent",
        "markup_snapshot",
        "current_eur_rate",
        mode="before",
    )
    @classmethod
    def round_admin_money(cls, value: Decimal | float | int | None) -> Decimal | None:
        if value is None:
            return None
        return ceil_rub(Decimal(str(value)))

    @computed_field  # type: ignore[misc]
    @property
    def supplier_price_eur_display(self) -> str:
        return format_eur(self.supplier_price_eur)


# Схема частичного обновления товара.
class ProductUpdate(BaseModel):
    title: str | None = None
    brand: str | None = None
    description: str | None = None
    sale_price: Decimal | None = None
    regular_price: Decimal | None = None
    product_url: str | None = None
    image_url: str | None = None
    stock: int | None = None
    is_active: bool | None = None
