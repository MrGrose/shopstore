"""add order notification channel snapshots"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "notification_channels", sa.JSON(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "orders", sa.Column("notification_email", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("orders", "notification_email")
    op.drop_column("orders", "notification_channels")
