"""add product dom enrichment status

Revision ID: 0a1b2c3d4e5f
Revises: f7a8b9c0d1e2
Create Date: 2026-05-18 11:44:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "dom_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "products",
        sa.Column("dom_last_error", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("dom_last_attempt_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "dom_last_attempt_at")
    op.drop_column("products", "dom_last_error")
    op.drop_column("products", "dom_attempts")
