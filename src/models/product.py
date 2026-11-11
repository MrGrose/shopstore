from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.repositories.database import Base
from src.utils.translate_descriptions import stored_description_ru_is_valid


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))  # Название товара
    brand: Mapped[str] = mapped_column(String(100))  # Бренд товара
    description_raw: Mapped[str | None] = mapped_column(
        Text
    )  # Оригинал описания из фида
    description_ru: Mapped[str | None] = mapped_column(
        Text
    )  # Машинный перевод описания на русский
    description_hash: Mapped[str | None] = mapped_column(
        String(64)
    )  # sha256 от description_raw для идемпотентного перевода
    description_translated_hash: Mapped[str | None] = mapped_column(
        String(64)
    )  # sha256 raw, с которого записан валидный description_ru

    # Текст для показа: валидный RU, иначе оригинал (не Google error / echo).
    @property
    def description(self) -> str | None:
        if stored_description_ru_is_valid(self.description_ru):
            return self.description_ru
        return self.description_raw

    # Совместимость со старыми вызовами (API создания/апдейта): значение трактуем
    # как исходник; description_ru при этом сбрасываем, чтобы импорт перевёл заново.
    @description.setter
    def description(self, value: str | None) -> None:
        self.description_raw = value
        self.description_ru = None
        self.description_hash = None
        self.description_translated_hash = None

    sale_price: Mapped[float] = mapped_column(Numeric(10, 2))  # Текущая цена продажи
    supplier_price_eur: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )  # Исходная цена поставщика в EUR
    regular_price: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )  # Базовая цена без скидки
    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Общий остаток товара
    catalog_in_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )  # Доступен на витрине (остаток − резерв), denorm для catalog SQL
    available_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )  # Доступное кол-во для витрины, denorm

    product_url: Mapped[str | None] = mapped_column(
        String(255), unique=True
    )  # Канонический URL карточки товара
    image_url: Mapped[str | None] = mapped_column(
        String(255)
    )  # Главная картинка товара
    external_id: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )  # Внешний ID из источника импорта

    category_l1: Mapped[str | None] = mapped_column(
        String(100)
    )  # Категория 1-го уровня
    category_l2: Mapped[str | None] = mapped_column(
        String(100)
    )  # Категория 2-го уровня
    category_l3: Mapped[str | None] = mapped_column(
        String(100)
    )  # Категория 3-го уровня
    pricing_category_key: Mapped[str | None] = mapped_column(
        String(64)
    )  # Ключ ценовой категории для маржи
    eur_rate_snapshot: Mapped[float | None] = mapped_column(
        Numeric(12, 4)
    )  # Курс EUR на момент расчета цены
    margin_snapshot_percent: Mapped[float | None] = mapped_column(
        Numeric(6, 2)
    )  # Маржа на момент расчета цены
    markup_snapshot: Mapped[float | None] = mapped_column(
        Numeric(10, 4)
    )  # Мультипликатор на момент расчета цены

    sport_type: Mapped[str | None] = mapped_column(
        String(50)
    )  # Тип спорта (из витрины/GTM)
    trade_group: Mapped[str | None] = mapped_column(
        String(50)
    )  # Торговая группа товара
    gender: Mapped[str | None] = mapped_column(String(50))  # Гендерная группа товара
    shipping_estimate: Mapped[str | None] = mapped_column(
        String(255)
    )  # Срок/оценка доставки (импорт; на витрине не используется)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )  # Флаг активности товара в каталоге
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Когда товар снят finalize (missing из snapshot)
    catalog_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Последний успешный импорт из парсера поставщика
    dom_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )  # Количество неуспешных DOM-попыток подряд
    dom_last_error: Mapped[str | None] = mapped_column(
        String(255)
    )  # Последняя причина ошибки DOM enrichment
    dom_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Последняя попытка DOM enrichment
    dom_processing_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Rolling refresh: захват перед enqueue
    dom_processing_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Истечение захвата (worker crash → self-heal)
    dom_processing_owner_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Владелец DB claim (scheduler batch token)
    supplier_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # RAW supplier input для category pipeline (GraphQL only)
    supplier_snapshot_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # sha256 canonical supplier_snapshot_json
    dom_full_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Timestamp первого успешного FULL DOM enrichment

    # Связанные сущности для вариаций, изображений и характеристик товара.
    variants: Mapped[list["ProductVariant"]] = relationship(  # Список вариантов товара
        back_populates="product", cascade="all, delete-orphan"
    )
    images: Mapped[list["ProductImage"]] = relationship(  # Галерея изображений товара
        back_populates="product", cascade="all, delete-orphan"
    )
    features: Mapped[list["ProductFeature"]] = relationship(  # Характеристики товара
        back_populates="product", cascade="all, delete-orphan"
    )


# Варианта товара.
class ProductVariant(Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)  # Внутренний ID варианта
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )  # Ссылка на родительский товар

    variant_external_id: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )  # Внешний ID варианта из источника
    sku: Mapped[str | None] = mapped_column(String(64), index=True)  # Артикул варианта

    option1: Mapped[str | None] = mapped_column(
        String(100)
    )  # Параметр варианта 1 (например, цвет)
    option2: Mapped[str | None] = mapped_column(
        String(100)
    )  # Параметр варианта 2 (например, размер)
    option3: Mapped[str | None] = mapped_column(
        String(100)
    )  # Параметр варианта 3 (например, grip)

    option1_sort_key: Mapped[float | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )  # Числовой ключ сортировки option1
    option2_sort_key: Mapped[float | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )  # Числовой ключ сортировки option2
    option3_sort_key: Mapped[float | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )  # Числовой ключ сортировки option3

    price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # Цена варианта
    compare_at_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2)
    )  # Цена до скидки
    inventory_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Остаток на складе по варианту
    available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )  # Флаг доступности варианта

    product: Mapped["Product"] = relationship(
        back_populates="variants"
    )  # ORM-ссылка обратно на Product


# Изображения товара в галерее.
class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)  # Внутренний ID изображения
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )  # Ссылка на товар, которому принадлежит изображение

    url: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )  # Ссылка на медиа файл в Storage
    source_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )  # Ссылка на медиа файл в Supplier CDN
    alt: Mapped[str | None] = mapped_column(String(255))  # ALT-текст для UI/SEO
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Порядок в галерее

    product: Mapped["Product"] = relationship(
        back_populates="images"
    )  # ORM-ссылка обратно на Product


class CatalogHiddenBrand(Base):
    __tablename__ = "catalog_hidden_brands"

    brand: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


# Характеристики товара (например, Weight, Balance).
class ProductFeature(Base):
    __tablename__ = "product_features"

    id: Mapped[int] = mapped_column(primary_key=True)  # Внутренний ID характеристики
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )  # Ссылка на товар, которому принадлежит характеристика

    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # Название характеристики
    value: Mapped[str | None] = mapped_column(String(255))  # Значение характеристики
    icon_url: Mapped[str | None] = mapped_column(String(512))  # Иконка характеристики
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Порядок вывода характеристики

    product: Mapped["Product"] = relationship(
        back_populates="features"
    )  # ORM-ссылка обратно на Product
