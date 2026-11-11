import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_IMPORT_PRICE_RE = re.compile(r"[^0-9.\-]")


# Нормализует цену товара из фида (строка, float, int в центах).
def coerce_import_price(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value) / Decimal("100")
    if isinstance(value, float):
        return Decimal(str(value))
    cleaned = (
        str(value)
        .replace("€", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    cleaned = _IMPORT_PRICE_RE.sub("", cleaned)
    if cleaned == "":
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


# Нормализует цену варианта: int чаще в центах Shopify.
def coerce_variant_price(value: Any) -> Decimal:
    if isinstance(value, int):
        return Decimal(value) / Decimal("100")
    return coerce_import_price(value)


class ProductImportVariant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | str | None = None
    sku: str | None = None
    option1: str | None = None
    option2: str | None = None
    option3: str | None = None
    price: Decimal = Decimal("0")
    compare_at_price: Decimal = Decimal("0")
    inventory_quantity: int = 0
    available: bool = True

    # Нормализует цены варианта.
    @field_validator("price", "compare_at_price", mode="before")
    @classmethod
    def _coerce_money(cls, value: Any) -> Decimal:
        return coerce_variant_price(value)

    # Нормализует количество на складе.
    @field_validator("inventory_quantity", mode="before")
    @classmethod
    def _coerce_qty(cls, value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0


class ProductImportFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    name: str | None = None
    description: str | None = None
    value: str | None = None
    icon_url: str | None = None

    # Имя характеристики после очистки HTML-хвоста.
    @property
    def feature_name(self) -> str:
        raw = (self.title or self.name or "").strip()
        return raw.split("<", 1)[0].strip()

    # Значение характеристики или None.
    @property
    def feature_value(self) -> str | None:
        text = (self.description or self.value or "").strip()
        return text or None


class ProductImportImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = ""
    alt: str | None = None


class ProductImportGtm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str | None = None
    item_name: str | None = None
    item_brand: str | None = None
    item_category: str | None = None
    item_category2: str | None = None
    item_category3: str | None = None
    item_sport_type: str | None = None
    item_trade_group: str | None = None
    item_gender: str | None = None


class ProductImportSupplierCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    handle: str
    title: str | None = None


class ProductImportSupplierMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    import_collection_sport: str | None = None
    product_type: str | None = None
    collections: list[ProductImportSupplierCollection] = Field(default_factory=list)


class ProductImportPdpMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gender: str | None = None
    gender_source: str | None = None
    stock_source: str | None = None
    supplier: ProductImportSupplierMeta | None = None
    sku: str | None = None
    stock_status: str | None = None
    tax_info: str | None = None
    product_id: str | None = None
    variant_id: str | None = None
    item_size: str | None = None
    sport_type: str | None = None
    trade_group: str | None = None
    global_category: str | None = None
    item_category: str | None = None
    item_category2: str | None = None
    item_category3: str | None = None
    import_collection_sport: str | None = None
    product_type: str | None = None
    collections: list[ProductImportSupplierCollection] = Field(default_factory=list)

    # Нормализует supplier-блок.
    @field_validator("supplier", mode="before")
    @classmethod
    def _coerce_supplier(cls, value: Any) -> Any:
        if not value:
            return None
        return value

    # Признак supplier-блока GraphQL в pdp_meta.
    @property
    def has_supplier_block(self) -> bool:
        return self.supplier is not None and bool(
            (self.supplier.product_type or "").strip()
        )

    # Остаток синхронизирован из listing коллекции (scraper).
    @property
    def listing_stock_synced(self) -> bool:
        return self.stock_source == "collection_listing_fallback"


class ProductImportProductData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    variants: list[ProductImportVariant] = Field(default_factory=list)


class ProductImport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    brand: str | None = None
    description: str | None = None
    sale_price: Decimal = Decimal("0")
    sale_price_numeric: Decimal | None = None
    regular_price: Decimal = Decimal("0")
    product_url: str
    image_url: str = ""
    item_id: str | None = None
    gtm: ProductImportGtm = Field(default_factory=ProductImportGtm)
    features: list[ProductImportFeature] = Field(default_factory=list)
    media_gallery: list[ProductImportImage] = Field(default_factory=list)
    product_data: ProductImportProductData = Field(
        default_factory=ProductImportProductData
    )
    selected_variant: ProductImportVariant | None = None
    pdp_meta: ProductImportPdpMeta = Field(default_factory=ProductImportPdpMeta)
    import_source: str | None = None
    price_source: str | None = None
    dom_mode: str | None = None
    stock: int = 0
    is_active: bool = True

    # Нормализует цены товара.
    @field_validator(
        "sale_price",
        "sale_price_numeric",
        "regular_price",
        mode="before",
    )
    @classmethod
    def _coerce_product_price(cls, value: Any) -> Any:
        if value is None:
            return None
        return coerce_import_price(value)

    # Нормализует выбранный вариант.
    @field_validator("selected_variant", mode="before")
    @classmethod
    def _coerce_selected_variant(cls, value: Any) -> Any:
        if not value:
            return None
        return value

    # Нормализует данные товара.
    @field_validator("product_data", mode="before")
    @classmethod
    def _coerce_product_data(cls, value: Any) -> Any:
        if value is None:
            return {}
        return value

    # Нормализует GTM.
    @field_validator("gtm", mode="before")
    @classmethod
    def _coerce_gtm(cls, value: Any) -> Any:
        if not value:
            return {}
        return value

    # Нормализует pdp_meta.
    @field_validator("pdp_meta", mode="before")
    @classmethod
    def _coerce_pdp_meta(cls, value: Any) -> Any:
        if not value:
            return {}
        return value

    # EUR-цена поставщика для pricing/stock.
    @property
    def resolved_sale_price(self) -> Decimal:
        if self.sale_price_numeric is not None:
            return self.sale_price_numeric
        return self.sale_price

    # Варианты из product_data.
    @property
    def variants(self) -> list[ProductImportVariant]:
        return self.product_data.variants


class ProductImportList(BaseModel):
    products: list[ProductImport]

    # Валидирует список товаров из сырого JSON чанка.
    @classmethod
    def from_raw_products(cls, products: list[dict[str, Any]]) -> "ProductImportList":
        return cls.model_validate({"products": products})
