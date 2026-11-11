"""add product_images.source_url and allow nullable managed url

Revision ID: i8b2c3d4e5f6
Revises: d6e7f8a9b0c1
Create Date: 2026-09-06 16:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "i8b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

product_images = sa.table(
    "product_images",
    sa.column("url", sa.String),
    sa.column("source_url", sa.String),
)

_HTTP_URL = sa.or_(
    product_images.c.url.like("http://%"),
    product_images.c.url.like("https://%"),
)


# Копирует HTTP url в source_url. Возвращает число строк.
def backfill_source_urls(connection: sa.Connection) -> int:
    result = connection.execute(
        product_images.update().where(_HTTP_URL).values(source_url=product_images.c.url)
    )
    return int(result.rowcount or 0)


# Обнуляет managed url у CDN-only строк. Возвращает число строк.
def clear_http_managed_urls(connection: sa.Connection) -> int:
    result = connection.execute(
        product_images.update().where(_HTTP_URL).values(url=None)
    )
    return int(result.rowcount or 0)


# Возвращает HTTP source в url при downgrade.
def restore_http_urls_from_source(connection: sa.Connection) -> int:
    result = connection.execute(
        product_images.update()
        .where(
            sa.or_(
                product_images.c.url.is_(None),
                product_images.c.url == "",
            ),
            product_images.c.source_url.is_not(None),
        )
        .values(url=product_images.c.source_url)
    )
    return int(result.rowcount or 0)


# Добавляет source_url и переносит HTTP gallery URL.
def upgrade() -> None:
    op.add_column(
        "product_images",
        sa.Column("source_url", sa.String(length=512), nullable=True),
    )
    op.alter_column(
        "product_images",
        "url",
        existing_type=sa.String(length=512),
        nullable=True,
    )
    connection = op.get_bind()
    backfill_source_urls(connection)
    clear_http_managed_urls(connection)


# Возвращает HTTP url из source_url и удаляет колонку.
def downgrade() -> None:
    connection = op.get_bind()
    restore_http_urls_from_source(connection)
    op.alter_column(
        "product_images",
        "url",
        existing_type=sa.String(length=512),
        nullable=False,
    )
    op.drop_column("product_images", "source_url")
