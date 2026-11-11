import csv
import io
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product

PRODUCT_EXPORT_FIELDS = [
    "ID",
    "Бренд",
    "Название",
    "Вид спорта",
    "Цена EUR",
    "Цена RUB",
    "Остаток",
    "URL",
]

_CHUNK_SIZE = 1000


# Имя CSV-файла для выгрузки каталога.
def export_filename() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return f"products-export-{ts}.csv"


# Форматирует числовую цену для CSV.
def _format_price(value: Decimal | float | None) -> str:
    if value is None:
        return ""
    return str(value)


# Преобразует Product в строку CSV по PRODUCT_EXPORT_FIELDS.
def product_to_export_row(product: Product) -> list[str]:
    return [
        str(product.id),
        product.brand or "",
        product.title or "",
        product.sport_type or "",
        _format_price(product.supplier_price_eur),
        _format_price(product.sale_price),
        str(product.stock),
        product.product_url or "",
    ]


class ProductExportService:
    # AsyncSession для read-only выгрузки каталога.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Собирает CSV всех товаров (utf-8-sig) в память.
    async def build_csv_bytes(self) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(PRODUCT_EXPORT_FIELDS)

        offset = 0
        while True:
            stmt = (
                select(Product).order_by(Product.id).offset(offset).limit(_CHUNK_SIZE)
            )
            rows = list((await self.session.scalars(stmt)).all())
            if not rows:
                break
            for product in rows:
                writer.writerow(product_to_export_row(product))
            offset += len(rows)
            if len(rows) < _CHUNK_SIZE:
                break

        return buffer.getvalue().encode("utf-8-sig")
