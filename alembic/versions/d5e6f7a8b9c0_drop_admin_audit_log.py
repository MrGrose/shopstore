"""drop admin_audit_log

Revision ID: d5e6f7a8b9c0
Revises: c8e9f0a1b2c3
Create Date: 2026-06-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_log CASCADE")


def downgrade() -> None:
    pass
