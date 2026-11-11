"""backfill opaque referral codes for buyers"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from src.core.referral import generate_opaque_referral_code, is_legacy_ps_referral_code

revision: str = "b2c3d4e5f6a8"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def _allocate_code(used: set[str]) -> str:
    for _ in range(64):
        code = generate_opaque_referral_code()
        if code not in used:
            used.add(code)
            return code
    raise RuntimeError("failed to allocate unique referral code during migration")


def upgrade() -> None:
    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("role", sa.String),
        sa.column("referral_code", sa.String),
    )
    rows = bind.execute(
        sa.select(users.c.id, users.c.role, users.c.referral_code).order_by(users.c.id)
    ).fetchall()

    used_codes = {
        (row.referral_code or "").strip()
        for row in rows
        if row.referral_code and not is_legacy_ps_referral_code(row.referral_code)
    }

    for row in rows:
        role = (row.role or "").strip().lower()
        code = (row.referral_code or "").strip() or None
        if role == "admin":
            if code:
                bind.execute(
                    users.update()
                    .where(users.c.id == row.id)
                    .values(referral_code=None)
                )
            continue
        if role != "buyer":
            continue
        if code and not is_legacy_ps_referral_code(code):
            continue
        new_code = _allocate_code(used_codes)
        bind.execute(
            users.update().where(users.c.id == row.id).values(referral_code=new_code)
        )


def downgrade() -> None:
    pass
