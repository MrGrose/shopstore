"""add variant option sort keys

Revision ID: z7y8x9w0v1u2
Revises: c4d5e6f7a8b9
Create Date: 2026-07-22 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op

revision: str = "z7y8x9w0v1u2"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("option1_sort_key", "option2_sort_key", "option3_sort_key"):
        op.add_column(
            "product_variants",
            sa.Column(column, sa.Numeric(10, 3), nullable=True),
        )

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        from src.models.product import Product, ProductVariant
        from src.utils.variant_sort import apply_variant_option_sort_keys

        rows = session.execute(
            sa.select(ProductVariant, Product.category_l2).join(
                Product, Product.id == ProductVariant.product_id
            )
        ).all()
        for variant, category_l2 in rows:
            apply_variant_option_sort_keys(variant, category_l2)
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    for column in (
        "option3_sort_key",
        "option2_sort_key",
        "option1_sort_key",
    ):
        op.drop_column("product_variants", column)
