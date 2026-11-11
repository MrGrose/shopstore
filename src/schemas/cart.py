from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from src.schemas.money import RubMoneyJSON, ceil_rub
from src.utils.labels import display_product_title, translate_option_value


# Схема добавления товара в корзину.
class CartItemCreate(BaseModel):
    product_id: int
    variant_id: int | None = Field(default=None, ge=1)
    quantity: int = Field(default=1, ge=1)


# Схема обновления количества товара в корзине.
class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=0)


# Схема позиции корзины в ответе API.
class CartItemSchema(BaseModel):
    id: int
    user_id: int | None = None
    product_id: int
    variant_id: int | None = None
    quantity: int
    price_snapshot: RubMoneyJSON
    product_title: str | None = None
    product_brand: str | None = None
    product_image_url: str | None = None
    variant_sku: str | None = None
    variant_option1: str | None = None
    variant_option2: str | None = None
    variant_option3: str | None = None
    available_stock: int = 0

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def variant_option1_ru(self) -> str | None:
        if not self.variant_option1:
            return None
        return translate_option_value(self.variant_option1) or None

    @computed_field  # type: ignore[misc]
    @property
    def variant_option2_ru(self) -> str | None:
        if not self.variant_option2:
            return None
        return translate_option_value(self.variant_option2) or None

    @computed_field  # type: ignore[misc]
    @property
    def variant_option3_ru(self) -> str | None:
        if not self.variant_option3:
            return None
        return translate_option_value(self.variant_option3) or None

    @computed_field  # type: ignore[misc]
    @property
    def display_title(self) -> str | None:
        if not self.product_title:
            return None
        title = display_product_title(
            self.product_title,
            option1=self.variant_option1,
            option2=self.variant_option2,
            option3=self.variant_option3,
        )
        return title or None

    @field_validator("price_snapshot", mode="before")
    @classmethod
    def round_item_price_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")


# Схема корзины пользователя с итоговой суммой.
class CartSchema(BaseModel):
    items: list[CartItemSchema]
    total_amount: RubMoneyJSON
    delivery_fee_amount: RubMoneyJSON = Decimal("0")
    total_with_delivery_amount: RubMoneyJSON = Decimal("0")
    supplier_cost_eur: Decimal = Decimal("0")

    @field_validator(
        "total_amount",
        "delivery_fee_amount",
        "total_with_delivery_amount",
        mode="before",
    )
    @classmethod
    def round_totals_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")
