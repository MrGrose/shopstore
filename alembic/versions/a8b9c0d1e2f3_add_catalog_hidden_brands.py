"""add catalog_hidden_brands

Revision ID: a8b9c0d1e2f3
Revises: b8c9d0e1f2a3
Create Date: 2026-07-04 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

hidden_brands = sa.table(
    "catalog_hidden_brands",
    sa.column("brand", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.create_table(
        "catalog_hidden_brands",
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("brand"),
    )
    op.execute(
        hidden_brands.insert().values(brand="Supplier-Demo", created_at=sa.func.now())
    )


def downgrade() -> None:
    op.drop_table("catalog_hidden_brands")
