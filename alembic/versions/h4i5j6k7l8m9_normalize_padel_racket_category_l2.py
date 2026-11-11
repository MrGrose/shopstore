"""normalize padel racket category_l2 alias

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-06-09 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "h4i5j6k7l8m9"
down_revision: Union[str, Sequence[str], None] = "g3h4i5j6k7l8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE products
        SET category_l2 = 'Padel rackets'
        WHERE category_l2 = 'Padel racket'
        """
    )


def downgrade() -> None:
    pass
