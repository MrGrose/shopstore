"""add storefront pricing rules and recalculation jobs

Revision ID: a0b1c2d3e4f5
Revises: a1b2c3d4e5f8
Create Date: 2026-07-14 12:00:00.000000
"""

from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STOREFRONT_RULE_KEYS = (
    ("Padel", "rackets"),
    ("Padel", "apparel"),
    ("Padel", "shoes"),
    ("Padel", "balls"),
    ("Padel", "bags"),
    ("Padel", "accessories"),
    ("Tennis", "rackets"),
    ("Tennis", "apparel"),
    ("Tennis", "shoes"),
    ("Tennis", "bags"),
    ("Tennis", "balls"),
    ("Tennis", "strings"),
    ("Tennis", "accessories"),
    ("Running", "shoes"),
    ("Running", "apparel"),
    ("Running", "accessories"),
    ("Padel", "__fallback__"),
    ("Tennis", "__fallback__"),
    ("Running", "__fallback__"),
)

margin_rules = sa.table(
    "margin_rules",
    sa.column("category_key", sa.String()),
    sa.column("label", sa.String()),
    sa.column("sport_type", sa.String()),
    sa.column("subcategory_slug", sa.String()),
    sa.column("margin_percent", sa.Numeric()),
    sa.column("is_active", sa.Boolean()),
)


# Возвращает зафиксированные строки начальных storefront-правил.
def initial_margin_rule_rows() -> list[dict[str, object]]:
    return [
        {
            "category_key": f"{sport_type}:{subcategory_slug}",
            "label": f"{sport_type} / {subcategory_slug}",
            "sport_type": sport_type,
            "subcategory_slug": subcategory_slug,
            "margin_percent": Decimal("30.00"),
            "is_active": True,
        }
        for sport_type, subcategory_slug in STOREFRONT_RULE_KEYS
    ]


# Переводит margin rules на storefront-ключ и создаёт таблицы batch jobs.
def upgrade() -> None:
    op.add_column(
        "margin_rules", sa.Column("sport_type", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "margin_rules",
        sa.Column("subcategory_slug", sa.String(length=64), nullable=True),
    )
    op.bulk_insert(margin_rules, initial_margin_rule_rows())
    op.execute(
        margin_rules.delete().where(
            margin_rules.c.category_key.in_(
                ("rackets", "shoes_clothing", "accessories")
            )
        )
    )
    op.alter_column("margin_rules", "sport_type", nullable=False)
    op.alter_column("margin_rules", "subcategory_slug", nullable=False)
    op.drop_constraint("uq_margin_rule_category", "margin_rules", type_="unique")
    op.drop_column("margin_rules", "label")
    op.drop_column("margin_rules", "category_key")
    op.create_unique_constraint(
        "uq_margin_rule_sport_subcategory",
        "margin_rules",
        ["sport_type", "subcategory_slug"],
    )

    op.create_table(
        "pricing_recalculation_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("margin_rule_id", sa.Integer(), nullable=False),
        sa.Column("rq_job_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("margin_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("rule_version", sa.DateTime(), nullable=False),
        sa.Column("settings_version", sa.DateTime(), nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cursor_product_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["margin_rule_id"],
            ["margin_rules.id"],
            name="fk_pricing_job_margin_rule",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rq_job_id", name="uq_pricing_job_rq_job_id"),
    )
    op.create_table(
        "pricing_recalculation_job_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pricing_job_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["pricing_job_id"],
            ["pricing_recalculation_jobs.id"],
            name="fk_pricing_job_error_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_job_id",
            "product_id",
            name="uq_pricing_job_error_product",
        ),
    )
    op.create_table(
        "margin_rule_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("margin_rule_id", sa.Integer(), nullable=False),
        sa.Column("previous_margin_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("margin_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["margin_rule_id"],
            ["margin_rules.id"],
            name="fk_margin_rule_history_rule",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO margin_rule_history (
                margin_rule_id,
                previous_margin_percent,
                margin_percent,
                created_at
            )
            SELECT id, NULL, margin_percent, updated_at
            FROM margin_rules
            """
        )
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_pricing_recalculation_jobs_margin_rule_id",
            "pricing_recalculation_jobs",
            ["margin_rule_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_pricing_recalculation_job_errors_pricing_job_id",
            "pricing_recalculation_job_errors",
            ["pricing_job_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_margin_rule_history_rule_created_at",
            "margin_rule_history",
            ["margin_rule_id", "created_at"],
            postgresql_concurrently=True,
        )


# Возвращает legacy-схему margin rules при откате.
def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_margin_rule_history_rule_created_at",
            table_name="margin_rule_history",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_pricing_recalculation_job_errors_pricing_job_id",
            table_name="pricing_recalculation_job_errors",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_pricing_recalculation_jobs_margin_rule_id",
            table_name="pricing_recalculation_jobs",
            postgresql_concurrently=True,
        )
    op.drop_table("margin_rule_history")
    op.drop_table("pricing_recalculation_job_errors")
    op.drop_table("pricing_recalculation_jobs")
    op.drop_constraint(
        "uq_margin_rule_sport_subcategory", "margin_rules", type_="unique"
    )
    op.add_column(
        "margin_rules", sa.Column("category_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "margin_rules", sa.Column("label", sa.String(length=128), nullable=True)
    )
    op.execute(margin_rules.delete())
    op.bulk_insert(
        margin_rules,
        [
            {
                "category_key": "rackets",
                "label": "Ракетки",
                "sport_type": "Padel",
                "subcategory_slug": "rackets",
                "margin_percent": Decimal("25.00"),
                "is_active": True,
            },
            {
                "category_key": "shoes_clothing",
                "label": "Обувь/Одежда",
                "sport_type": "Padel",
                "subcategory_slug": "apparel",
                "margin_percent": Decimal("30.00"),
                "is_active": True,
            },
            {
                "category_key": "accessories",
                "label": "Аксессуары",
                "sport_type": "Padel",
                "subcategory_slug": "accessories",
                "margin_percent": Decimal("50.00"),
                "is_active": True,
            },
        ],
    )
    op.alter_column("margin_rules", "category_key", nullable=False)
    op.alter_column("margin_rules", "label", nullable=False)
    op.drop_column("margin_rules", "subcategory_slug")
    op.drop_column("margin_rules", "sport_type")
    op.create_unique_constraint(
        "uq_margin_rule_category", "margin_rules", ["category_key"]
    )
