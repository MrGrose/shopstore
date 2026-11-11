"""rename snapshot columns to captured

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
Create Date: 2026-04-23 15:35:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "9e0f1a2b3c4d"
down_revision: Union[str, Sequence[str], None] = "8d9e0f1a2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "order_items",
        "product_title_snapshot",
        new_column_name="product_title_captured",
    )
    op.alter_column(
        "order_items",
        "product_external_id_snapshot",
        new_column_name="product_external_id_captured",
    )
    op.alter_column(
        "order_items",
        "variant_external_id_snapshot",
        new_column_name="variant_external_id_captured",
    )
    op.alter_column(
        "order_items",
        "variant_sku_snapshot",
        new_column_name="variant_sku_captured",
    )
    op.alter_column(
        "order_items",
        "variant_option1_snapshot",
        new_column_name="variant_option1_captured",
    )
    op.alter_column(
        "order_items",
        "variant_option2_snapshot",
        new_column_name="variant_option2_captured",
    )
    op.alter_column(
        "order_items",
        "variant_option3_snapshot",
        new_column_name="variant_option3_captured",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "order_items",
        "product_title_captured",
        new_column_name="product_title_snapshot",
    )
    op.alter_column(
        "order_items",
        "product_external_id_captured",
        new_column_name="product_external_id_snapshot",
    )
    op.alter_column(
        "order_items",
        "variant_external_id_captured",
        new_column_name="variant_external_id_snapshot",
    )
    op.alter_column(
        "order_items",
        "variant_sku_captured",
        new_column_name="variant_sku_snapshot",
    )
    op.alter_column(
        "order_items",
        "variant_option1_captured",
        new_column_name="variant_option1_snapshot",
    )
    op.alter_column(
        "order_items",
        "variant_option2_captured",
        new_column_name="variant_option2_snapshot",
    )
    op.alter_column(
        "order_items",
        "variant_option3_captured",
        new_column_name="variant_option3_snapshot",
    )
