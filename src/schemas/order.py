import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
)

from src.schemas.money import RubMoneyJSON, ceil_rub
from src.utils.datetime_fmt import format_datetime_msk, format_utc_iso_z
from src.utils.images import coerce_public_product_media_url
from src.utils.labels import (
    display_product_title,
    translate_category_l2,
    translate_category_l3,
    translate_option_value,
)

LATIN_NAME_REGEX = re.compile(r"^[A-Za-z\s\-']+$")
LATIN_STREET_REGEX = re.compile(r"^[A-Za-z0-9\s.,\-/'#]+$")
LATIN_SHORT_REGEX = re.compile(r"^[A-Za-z0-9\s\-/]+$")
POSTAL_REGEX = re.compile(r"^[0-9]{5,6}$")

MSG_REQUIRED = "Обязательное поле"
MSG_LATIN_NAME = "Указывайте латиницей (Ivanov Ivan)"
MSG_LATIN_CITY = "Указывайте латиницей (Moscow)"
MSG_LATIN_STREET = "Указывайте латиницей; допустимы цифры и знаки . , - / #"
MSG_HOUSE = "Номер дома: латиница и хотя бы одна цифра (например 10 или 10A)"
MSG_APARTMENT = "Квартира: латиница и хотя бы одна цифра (например 42)"
MSG_POSTAL = "Индекс: 5-6 цифр (101000)"
MSG_PHONE = "Укажите российский мобильный номер (+79991234567)"

_DELIVERY_TEXT_FIELDS = (
    "last_name",
    "first_name",
    "street",
    "house",
    "apartment",
    "city",
    "postal_code",
    "phone",
)
_REQUIRED_DELIVERY_FIELDS = (
    "last_name",
    "first_name",
    "street",
    "house",
    "city",
    "postal_code",
    "phone",
)


def _normalize_delivery_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _validate_optional(
    value: str | None,
    validator: Callable[[str], str],
) -> str | None:
    if value is None:
        return None
    return validator(value)


def _validate_latin_name(value: str, *, msg: str = MSG_LATIN_NAME) -> str:
    if not LATIN_NAME_REGEX.fullmatch(value):
        raise ValueError(msg)
    return value


def _validate_latin_street(value: str) -> str:
    if not LATIN_STREET_REGEX.fullmatch(value):
        raise ValueError(MSG_LATIN_STREET)
    return value


def _validate_house(value: str) -> str:
    if not LATIN_SHORT_REGEX.fullmatch(value) or not re.search(r"\d", value):
        raise ValueError(MSG_HOUSE)
    return value


def _validate_apartment(value: str) -> str:
    if not LATIN_SHORT_REGEX.fullmatch(value) or not re.search(r"\d", value):
        raise ValueError(MSG_APARTMENT)
    return value


def _validate_postal_code(value: str) -> str:
    if not POSTAL_REGEX.fullmatch(value):
        raise ValueError(MSG_POSTAL)
    return value


def normalize_ru_mobile_phone(value: str) -> str:
    from src.utils.phone import normalize_ru_mobile_phone as _normalize

    return _normalize(value)


def _validate_phone(value: str) -> str:
    return normalize_ru_mobile_phone(value)


# Схема адреса доставки для оформления заказа.
class DeliveryAddressCreate(BaseModel):
    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    street: str = Field(min_length=1, max_length=255)
    house: str = Field(min_length=1, max_length=50)
    apartment: str | None = Field(default=None, max_length=50)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    phone: str = Field(min_length=1, max_length=20)

    @field_validator(*_REQUIRED_DELIVERY_FIELDS, mode="before")
    @classmethod
    def require_and_normalize(cls, value: str | None) -> str:
        if value is None or not str(value).strip():
            raise ValueError(MSG_REQUIRED)
        normalized = _normalize_delivery_text(str(value).strip())
        assert normalized is not None
        return normalized

    @field_validator("apartment", mode="before")
    @classmethod
    def normalize_apartment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_delivery_text(value)
        if not normalized:
            return None
        return normalized

    @field_validator("last_name", "first_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        return _validate_latin_name(value)

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str) -> str:
        return _validate_latin_name(value, msg=MSG_LATIN_CITY)

    @field_validator("street")
    @classmethod
    def validate_street(cls, value: str) -> str:
        return _validate_latin_street(value)

    @field_validator("house")
    @classmethod
    def validate_house(cls, value: str) -> str:
        return _validate_house(value)

    @field_validator("apartment")
    @classmethod
    def validate_apartment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_apartment(value)

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code_field(cls, value: str) -> str:
        return _validate_postal_code(value)

    @field_validator("phone")
    @classmethod
    def validate_phone_field(cls, value: str) -> str:
        return _validate_phone(value)


# Схема payload для checkout текущего пользователя.
class CheckoutCreate(BaseModel):
    delivery: DeliveryAddressCreate
    promo_code: str | None = Field(default=None, max_length=64)
    notification_channels: list[str] = Field(min_length=1, max_length=2)
    notification_email: str | None = Field(default=None, max_length=255)


# Схема запроса предпросмотра checkout без создания заказа.
class CheckoutPreviewRequest(BaseModel):
    promo_code: str | None = Field(default=None, max_length=64)


# Схема расчета итогов checkout для UI.
class CheckoutPreviewSchema(BaseModel):
    items_subtotal_amount: RubMoneyJSON
    discounted_items_subtotal_amount: RubMoneyJSON
    discount_items_amount: RubMoneyJSON
    delivery_fee_amount: RubMoneyJSON
    total_amount: RubMoneyJSON
    promo_code_applied: str | None = None
    supplier_cost_eur: Decimal = Decimal("0")
    customs_duty_amount: RubMoneyJSON = Decimal("0")
    customs_duty_notice: str | None = None
    eur_rate: Decimal = Decimal("0")
    requires_availability_confirmation: bool = False
    availability_message_ru: str | None = None

    @field_validator(
        "items_subtotal_amount",
        "discounted_items_subtotal_amount",
        "discount_items_amount",
        "delivery_fee_amount",
        "total_amount",
        "customs_duty_amount",
        mode="before",
    )
    @classmethod
    def round_checkout_totals_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")


# RU-подпись категории; None если snapshot пустой.
def _category_label_ru(
    value: str | None, translate: Callable[[str | None], str]
) -> str | None:
    if not str(value or "").strip():
        return None
    label = str(translate(value) or "").strip()
    return label or None


# Схема позиции товара в заказе.
class OrderItemSchema(BaseModel):
    id: int | None = None
    product_id: int
    variant_id: int | None = None
    quantity: int
    unit_price: RubMoneyJSON
    product_title: str | None = None
    product_external_id: str | None = None
    product_image_url: str | None = None
    product_url: str | None = None
    variant_sku: str | None = None
    variant_external_id: str | None = None
    variant_option1: str | None = None
    variant_option2: str | None = None
    variant_option3: str | None = None
    category_l2: str | None = Field(
        default=None,
        validation_alias=AliasChoices("category_l2_captured", "category_l2"),
    )
    category_l3: str | None = Field(
        default=None,
        validation_alias=AliasChoices("category_l3_captured", "category_l3"),
    )

    @field_validator("product_image_url", mode="before")
    @classmethod
    def expose_public_product_image_url(cls, value: Any) -> Any:
        return coerce_public_product_media_url(value)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

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

    @computed_field  # type: ignore[misc]
    @property
    def category_l2_label_ru(self) -> str | None:
        return _category_label_ru(self.category_l2, translate_category_l2)

    @computed_field  # type: ignore[misc]
    @property
    def category_l3_label_ru(self) -> str | None:
        return _category_label_ru(self.category_l3, translate_category_l3)

    @field_validator("unit_price", mode="before")
    @classmethod
    def round_unit_price_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")


# Customer-safe ссылка на трек: carrier + готовый URL, без raw ParcelLab.
class OrderShipmentTrackingLinkSchema(BaseModel):
    carrier: str
    url: str


# Нога трекинга посылки для ЛК: URL как в БД, links — DHL/Почта от CJ.
class OrderShipmentTrackingSchema(BaseModel):
    carrier: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    links: list[OrderShipmentTrackingLinkSchema] = Field(default_factory=list)


# Состав посылки: qty allocation, без TP/cost.
class OrderShipmentItemSchema(BaseModel):
    order_item_id: int
    quantity: int
    product_title: str | None = None
    display_title: str | None = None
    product_image_url: str | None = None
    variant_option1_ru: str | None = None
    variant_option2_ru: str | None = None
    variant_option3_ru: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None

    @field_validator("product_image_url", mode="before")
    @classmethod
    def expose_public_product_image_url(cls, value: Any) -> Any:
        return coerce_public_product_media_url(value)

    @computed_field  # type: ignore[misc]
    @property
    def category_l2_label_ru(self) -> str | None:
        return _category_label_ru(self.category_l2, translate_category_l2)

    @computed_field  # type: ignore[misc]
    @property
    def category_l3_label_ru(self) -> str | None:
        return _category_label_ru(self.category_l3, translate_category_l3)


# Customer read-model посылки; seq считается в сервисе.
class OrderShipmentSchema(BaseModel):
    id: int
    seq: int
    status: str
    status_label: str
    status_updated_at: datetime | None = None
    delivered_at: datetime | None = None
    supplier_tracking: OrderShipmentTrackingSchema
    customer_tracking: OrderShipmentTrackingSchema
    items: list[OrderShipmentItemSchema] = Field(default_factory=list)


# Схема заказа в ответе API.
class OrderSchema(BaseModel):
    id: int
    user_id: int
    status: str
    status_label: str | None = None
    availability_confirmation_status: str = "not_required"
    availability_confirmation_status_label: str | None = None
    availability_message_ru: str | None = None
    payment_allowed: bool = True
    payment_gateway_enabled: bool = True
    customer_cancel_allowed: bool = False
    customer_cancel_blocked_reason: str | None = None
    payment_due_at: datetime | None = None
    payment_due_at_display: str | None = None
    cancellation_reason: str | None = None
    payment_attempts_used: int = 0
    payment_attempts_limit: int = 5
    payment_attempts_remaining: int = 5
    payment_attempts_exhausted: bool = False
    late_payment_after_auto_cancel: bool = False
    total_amount: RubMoneyJSON
    items_subtotal_amount: RubMoneyJSON = Decimal("0")
    discount_items_amount: RubMoneyJSON = Decimal("0")
    delivery_fee_amount: RubMoneyJSON = Decimal("0")
    eur_rate_snapshot: Decimal = Decimal("0")
    promo_code_applied: str | None = None
    last_name: str | None = None
    first_name: str | None = None
    street: str | None = None
    house: str | None = None
    apartment: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    notification_channels: list[str] = Field(default_factory=list)
    notification_email: str | None = None
    payment_provider: str | None = None
    payment_order_id: str | None = None
    payment_status: str | None = None
    payment_paid_at: datetime | None = None
    payment_state: str = "not_started"
    payment_label: str = "Можно оплатить"
    payment_method_label: str | None = None
    payment_paid_at_short_display: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_phone: str | None = None
    user_telegram_id: int | None = None
    user_telegram_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    supplier_order_id: str | None = None
    supplier_tracking_id: str | None = None
    failed_from_status: str | None = None
    items: list[OrderItemSchema] = Field(default_factory=list)
    shipments: list[OrderShipmentSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def created_at_display(self) -> str | None:
        return format_datetime_msk(self.created_at, with_tz_label=False)

    @field_validator(
        "total_amount",
        "items_subtotal_amount",
        "discount_items_amount",
        "delivery_fee_amount",
        mode="before",
    )
    @classmethod
    def round_order_totals_up(cls, value: Decimal) -> Decimal:
        return ceil_rub(value) or Decimal("0")


# Схема события истории заказа.
class OrderEventSchema(BaseModel):
    id: int
    order_id: int
    event_type: str
    event_message: str | None = None
    created_by: str | None = None
    payload_json: dict | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def created_at_display(self) -> str | None:
        return format_datetime_msk(self.created_at)


# Ответ инициализации оплаты для checkout.
class PaymentInitSchema(BaseModel):
    order_id: int
    provider: str
    payment_attempt_id: int
    payment_state: str
    payment_qr_payload: str | None = None
    qr_expires_at: datetime | None = None
    is_paid: bool = False
    payment_status: str | None = None
    is_test_mode: bool = False
    payment_attempts_used: int = 0
    payment_attempts_limit: int = 5
    payment_attempts_remaining: int = 5
    payment_attempts_exhausted: bool = False

    # Сериализует время истечения QR в UTC с Z.
    @field_serializer("qr_expires_at")
    def serialize_qr_expires_at(self, value: datetime | None) -> str | None:
        return format_utc_iso_z(value)


# Ответ проверки текущего статуса оплаты заказа.
class PaymentStatusSchema(BaseModel):
    order_id: int
    status: str
    payment_attempt_id: int
    payment_state: str
    is_paid: bool = False
    qr_expires_at: datetime | None = None
    payment_status: str | None = None
    payment_attempts_used: int = 0
    payment_attempts_limit: int = 5
    payment_attempts_remaining: int = 5
    payment_attempts_exhausted: bool = False

    # Сериализует время истечения QR в UTC с Z.
    @field_serializer("qr_expires_at")
    def serialize_qr_expires_at(self, value: datetime | None) -> str | None:
        return format_utc_iso_z(value)


# Схема подтверждения/отклонения наличия админом.
class AdminAvailabilityConfirmationUpdate(BaseModel):
    action: str = Field(min_length=1, max_length=16)
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)
    notify_customer: bool = True


# Схема смены статуса заказа админом.
class AdminOrderStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)
    notify_customer: bool = False
    custom_message: str | None = Field(default=None, max_length=1000)


# Схема передачи заказа в сборку у поставщика.
class AdminStartAssemblingUpdate(BaseModel):
    supplier_order_id: str = Field(min_length=1, max_length=128)
    supplier_delivery_json: dict | None = None
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)
    notify_customer: bool = False
    custom_message: str | None = Field(default=None, max_length=1000)


# Схема передачи собранного заказа в доставку.
class AdminStartDeliveryUpdate(BaseModel):
    supplier_tracking_id: str = Field(min_length=1, max_length=128)
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)
    notify_customer: bool = False
    custom_message: str | None = Field(default=None, max_length=1000)


class SupplierTrackingPublicEventSchema(BaseModel):
    key: str
    at: datetime | None = None
    stage: str
    title: str
    description: str | None = None


class SupplierTrackingPublicSchema(BaseModel):
    available: bool = False
    current_status: str | None = None
    current_description: str | None = None
    current_stage: str | None = None
    carrier_label: str | None = None
    last_updated_at: datetime | None = None
    events: list[SupplierTrackingPublicEventSchema] = Field(default_factory=list)


# Схема редактирования полей доставки в заказе админом.
class AdminOrderUpdate(BaseModel):
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    street: str | None = Field(default=None, min_length=1, max_length=255)
    house: str | None = Field(default=None, min_length=1, max_length=50)
    apartment: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    phone: str | None = Field(default=None, min_length=1, max_length=20)
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)

    @field_validator(*_DELIVERY_TEXT_FIELDS, mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_delivery_text(value)

    @field_validator("last_name", "first_name")
    @classmethod
    def validate_optional_names(cls, value: str | None) -> str | None:
        return _validate_optional(value, _validate_latin_name)

    @field_validator("city")
    @classmethod
    def validate_optional_city(cls, value: str | None) -> str | None:
        return _validate_optional(
            value, lambda v: _validate_latin_name(v, msg=MSG_LATIN_CITY)
        )

    @field_validator("street")
    @classmethod
    def validate_optional_street(cls, value: str | None) -> str | None:
        return _validate_optional(value, _validate_latin_street)

    @field_validator("house")
    @classmethod
    def validate_optional_house(cls, value: str | None) -> str | None:
        return _validate_optional(value, _validate_house)

    @field_validator("apartment")
    @classmethod
    def validate_optional_apartment(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return _validate_apartment(value)

    @field_validator("postal_code")
    @classmethod
    def validate_optional_postal_code(cls, value: str | None) -> str | None:
        return _validate_optional(value, _validate_postal_code)

    @field_validator("phone")
    @classmethod
    def validate_optional_phone(cls, value: str | None) -> str | None:
        return _validate_optional(value, _validate_phone)


# Схема изменения одной позиции заказа админом.
class AdminOrderItemUpdate(BaseModel):
    id: int
    quantity: int = Field(ge=1)
    unit_price: Decimal | None = None


# Схема добавления позиции в заказ админом.
class AdminOrderItemAdd(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(ge=1)
    unit_price: Decimal | None = Field(default=None, ge=0)


# Схема массовой правки позиций заказа админом.
class AdminOrderItemsUpdate(BaseModel):
    items: list[AdminOrderItemUpdate] = Field(default_factory=list)
    remove_item_ids: list[int] = Field(default_factory=list)
    add_items: list[AdminOrderItemAdd] = Field(default_factory=list)
    event_message: str | None = Field(default=None, max_length=1000)
    notify_customer: bool = True
    created_by: str | None = Field(default=None, max_length=64)


# Решение по одной low-stock позиции при проверке наличия.
class AdminAvailabilityItemDecision(BaseModel):
    order_item_id: int
    confirmed: bool


# Сохранение результата проверки наличия по позициям.
class AdminAvailabilityStockCheckUpdate(BaseModel):
    items: list[AdminAvailabilityItemDecision]
    event_message: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=64)
    notify_customer: bool = True


# Схема списка заказов админки.
class AdminOrderListSchema(BaseModel):
    items: list[OrderSchema] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)


# Вариант товара в результатах поиска для добавления в заказ.
class AdminOrderProductSearchVariant(BaseModel):
    id: int
    label: str | None = None
    sale_price: Decimal | None = None
    sku: str | None = None


# Товар в результатах поиска для добавления в заказ.
class AdminOrderProductSearchItem(BaseModel):
    id: int
    title: str
    sale_price: Decimal | None = None
    variants: list[AdminOrderProductSearchVariant] = Field(default_factory=list)


# Ответ поиска товаров для добавления в заказ.
class AdminOrderProductSearchResponse(BaseModel):
    items: list[AdminOrderProductSearchItem] = Field(default_factory=list)
