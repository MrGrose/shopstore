"""drop admin_audit_log (legacy revision)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-02 12:00:00.000000

DBs that applied d5e6f7a8b9c0 when it still created admin_audit_log need this step.
Fresh installs already drop the table in d5e6f7a8b9c0.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_log CASCADE")


def downgrade() -> None:
    pass
