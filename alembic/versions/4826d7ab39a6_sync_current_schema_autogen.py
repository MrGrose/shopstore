"""sync_current_schema_autogen

Revision ID: 4826d7ab39a6
Revises: 93da2242df46
Create Date: 2026-04-21 14:31:46.360399

"""

from typing import Sequence, Union

revision: str = "4826d7ab39a6"
down_revision: Union[str, Sequence[str], None] = "93da2242df46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Tables were already created in 93da2242df46.
    # Keep this revision as a no-op to preserve migration history.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    # No-op downgrade for no-op upgrade.
    pass
