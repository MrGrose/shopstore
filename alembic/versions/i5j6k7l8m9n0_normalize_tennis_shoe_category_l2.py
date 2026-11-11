"""move tennis shoe subtypes from category_l2 to l3

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-06-09 23:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "i5j6k7l8m9n0"
down_revision: Union[str, Sequence[str], None] = "h4i5j6k7l8m9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHOE_SUBTYPES = (
    "All court shoes",
    "Clay court shoes",
    "Carpet shoes",
    "Grass court shoes",
    "Sneakers",
    "Flip flops",
)


def upgrade() -> None:
    in_list = ", ".join(f"'{value}'" for value in _SHOE_SUBTYPES)
    op.execute(
        f"""
        UPDATE products
        SET category_l3 = category_l2,
            category_l2 = 'Tennis shoes'
        WHERE sport_type = 'Tennis'
          AND category_l2 IN ({in_list})
          AND (category_l3 IS NULL OR category_l3 = '')
        """
    )
    op.execute(
        f"""
        UPDATE products
        SET category_l2 = 'Tennis shoes'
        WHERE sport_type = 'Tennis'
          AND category_l2 IN ({in_list})
          AND category_l3 IS NOT NULL
          AND category_l3 != ''
        """
    )


def downgrade() -> None:
    pass
