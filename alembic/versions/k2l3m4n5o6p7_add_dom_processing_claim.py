"""add dom processing claim columns

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-06-11 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("dom_processing_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("dom_processing_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "dom_processing_expires_at")
    op.drop_column("products", "dom_processing_at")
