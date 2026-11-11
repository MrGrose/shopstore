"""add user_delivery_profiles and order JSON snapshots

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-06-12 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, Sequence[str], None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_delivery_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("street", sa.String(length=255), nullable=False),
        sa.Column("house", sa.String(length=50), nullable=False),
        sa.Column("apartment", sa.String(length=50), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column("orders", sa.Column("customer_data_json", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("delivery_data_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "delivery_data_json")
    op.drop_column("orders", "customer_data_json")
    op.drop_table("user_delivery_profiles")
