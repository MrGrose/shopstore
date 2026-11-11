"""add storefront mapping v2 tables

Revision ID: m1n2o3p4q5r6
Revises: z7y8x9w0v1u2
Create Date: 2026-06-21 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "z7y8x9w0v1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storefront_mapping_releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("dirty_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("cloned_from_release_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cloned_from_release_id"],
            ["storefront_mapping_releases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sf_releases_one_active",
        "storefront_mapping_releases",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "storefront_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("display_key", sa.String(length=128), nullable=False),
        sa.Column("sport_type", sa.String(length=50), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label_ru", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["storefront_mapping_releases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id", "display_key", name="uq_sf_nodes_release_display_key"
        ),
        sa.UniqueConstraint("id", "release_id", name="uq_sf_nodes_id_release"),
    )
    op.create_index(
        "ix_sf_nodes_release_sport_active_sort",
        "storefront_nodes",
        ["release_id", "sport_type", "active", "sort_order"],
    )
    op.create_index(
        "uq_sf_nodes_release_parent_slug",
        "storefront_nodes",
        ["release_id", "parent_id", "slug"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_sf_nodes_release_root_slug",
        "storefront_nodes",
        ["release_id", "slug"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_index(
        "uq_sf_nodes_release_sport_root",
        "storefront_nodes",
        ["release_id", "sport_type"],
        unique=True,
        postgresql_where=sa.text("node_type = 'root'"),
    )
    op.create_foreign_key(
        "fk_sf_nodes_parent_same_release",
        "storefront_nodes",
        "storefront_nodes",
        ["parent_id", "release_id"],
        ["id", "release_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "storefront_mapping_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("storefront_node_id", sa.Integer(), nullable=True),
        sa.Column("sport_type", sa.String(length=50), nullable=False),
        sa.Column("category_l1", sa.String(length=100), nullable=True),
        sa.Column("category_l2", sa.String(length=100), nullable=True),
        sa.Column("category_l3", sa.String(length=100), nullable=True),
        sa.Column("match_mode", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(outcome = 'mapped' AND storefront_node_id IS NOT NULL) "
            "OR (outcome = 'excluded' AND storefront_node_id IS NULL)",
            name="ck_sf_rules_outcome_node",
        ),
        sa.CheckConstraint(
            "match_mode != 'l2_any_l3' "
            "OR (category_l2 IS NOT NULL AND category_l3 IS NULL)",
            name="ck_sf_rules_l2_any_l3",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["storefront_mapping_releases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "release_id", name="uq_sf_rules_id_release"),
    )
    op.create_index(
        "uq_sf_rules_identity",
        "storefront_mapping_rules",
        [
            "release_id",
            "sport_type",
            "match_mode",
            "outcome",
            "category_l1",
            "category_l2",
            "category_l3",
            "storefront_node_id",
        ],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_foreign_key(
        "fk_sf_rules_node_same_release",
        "storefront_mapping_rules",
        "storefront_nodes",
        ["storefront_node_id", "release_id"],
        ["id", "release_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "product_storefront_placements",
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("storefront_node_id", sa.Integer(), nullable=False),
        sa.Column("mapping_rule_id", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["storefront_mapping_releases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("release_id", "product_id", "storefront_node_id"),
    )
    op.create_index(
        "ix_psp_release_node_product",
        "product_storefront_placements",
        ["release_id", "storefront_node_id", "product_id"],
    )
    op.create_index(
        "ix_psp_release_product_node",
        "product_storefront_placements",
        ["release_id", "product_id", "storefront_node_id"],
    )
    op.create_foreign_key(
        "fk_psp_node_same_release",
        "product_storefront_placements",
        "storefront_nodes",
        ["storefront_node_id", "release_id"],
        ["id", "release_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_psp_rule_same_release",
        "product_storefront_placements",
        "storefront_mapping_rules",
        ["mapping_rule_id", "release_id"],
        ["id", "release_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "product_storefront_resolutions",
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.Column("resolver_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["storefront_mapping_releases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("release_id", "product_id"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_sf_nodes_hierarchy_validate()
        RETURNS trigger AS $$
        DECLARE
            parent_type text;
            parent_sport text;
        BEGIN
            IF NEW.node_type = 'root' THEN
                IF NEW.parent_id IS NOT NULL THEN
                    RAISE EXCEPTION 'root node must have NULL parent_id';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.parent_id IS NULL THEN
                RAISE EXCEPTION 'non-root node requires parent_id';
            END IF;
            SELECT node_type, sport_type INTO parent_type, parent_sport
            FROM storefront_nodes
            WHERE id = NEW.parent_id AND release_id = NEW.release_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'parent node not found in same release';
            END IF;
            IF parent_sport != NEW.sport_type THEN
                RAISE EXCEPTION 'parent sport_type mismatch';
            END IF;
            IF NEW.node_type = 'section' AND parent_type != 'root' THEN
                RAISE EXCEPTION 'section parent must be root';
            END IF;
            IF NEW.node_type = 'chip' AND parent_type != 'section' THEN
                RAISE EXCEPTION 'chip parent must be section';
            END IF;
            IF NEW.node_type NOT IN ('root', 'section', 'chip') THEN
                RAISE EXCEPTION 'invalid node_type';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sf_nodes_hierarchy
        AFTER INSERT OR UPDATE ON storefront_nodes
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION trg_sf_nodes_hierarchy_validate();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_sf_rules_mapped_chip_validate()
        RETURNS trigger AS $$
        DECLARE
            ntype text;
            nactive boolean;
        BEGIN
            IF NEW.outcome != 'mapped' OR NEW.storefront_node_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT node_type, active INTO ntype, nactive
            FROM storefront_nodes
            WHERE id = NEW.storefront_node_id AND release_id = NEW.release_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'mapped rule node not found in same release';
            END IF;
            IF ntype != 'chip' OR nactive IS NOT TRUE THEN
                RAISE EXCEPTION 'mapped rule must target active chip node';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sf_rules_mapped_chip
        AFTER INSERT OR UPDATE ON storefront_mapping_rules
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION trg_sf_rules_mapped_chip_validate();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_psp_chip_validate()
        RETURNS trigger AS $$
        DECLARE
            ntype text;
            nactive boolean;
        BEGIN
            SELECT node_type, active INTO ntype, nactive
            FROM storefront_nodes
            WHERE id = NEW.storefront_node_id AND release_id = NEW.release_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'placement node not found in same release';
            END IF;
            IF ntype != 'chip' OR nactive IS NOT TRUE THEN
                RAISE EXCEPTION 'placement must target active chip node';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_psp_chip
        AFTER INSERT OR UPDATE ON product_storefront_placements
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION trg_psp_chip_validate();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_psp_chip ON product_storefront_placements")
    op.execute("DROP FUNCTION IF EXISTS trg_psp_chip_validate()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sf_rules_mapped_chip ON storefront_mapping_rules"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_sf_rules_mapped_chip_validate()")
    op.execute("DROP TRIGGER IF EXISTS trg_sf_nodes_hierarchy ON storefront_nodes")
    op.execute("DROP FUNCTION IF EXISTS trg_sf_nodes_hierarchy_validate()")

    op.drop_table("product_storefront_resolutions")
    op.drop_table("product_storefront_placements")
    op.drop_table("storefront_mapping_rules")
    op.drop_table("storefront_nodes")
    op.drop_index("ix_sf_releases_one_active", table_name="storefront_mapping_releases")
    op.drop_table("storefront_mapping_releases")
