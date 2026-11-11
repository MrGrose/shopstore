from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.repositories.database import Base


class StorefrontMappingRelease(Base):
    __tablename__ = "storefront_mapping_releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dirty_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloned_from_release_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("storefront_mapping_releases.id", ondelete="SET NULL"),
        nullable=True,
    )

    nodes: Mapped[list["StorefrontNode"]] = relationship(back_populates="release")
    rules: Mapped[list["StorefrontMappingRule"]] = relationship(
        back_populates="release"
    )


class StorefrontNode(Base):
    __tablename__ = "storefront_nodes"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "display_key", name="uq_sf_nodes_release_display_key"
        ),
        UniqueConstraint("id", "release_id", name="uq_sf_nodes_id_release"),
        ForeignKeyConstraint(
            ["parent_id", "release_id"],
            ["storefront_nodes.id", "storefront_nodes.release_id"],
            name="fk_sf_nodes_parent_same_release",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("storefront_mapping_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sport_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    label_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    release: Mapped["StorefrontMappingRelease"] = relationship(back_populates="nodes")


class StorefrontMappingRule(Base):
    __tablename__ = "storefront_mapping_rules"
    __table_args__ = (
        UniqueConstraint("id", "release_id", name="uq_sf_rules_id_release"),
        ForeignKeyConstraint(
            ["storefront_node_id", "release_id"],
            ["storefront_nodes.id", "storefront_nodes.release_id"],
            name="fk_sf_rules_node_same_release",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("storefront_mapping_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    storefront_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sport_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category_l1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_l2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_l3: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    release: Mapped["StorefrontMappingRelease"] = relationship(back_populates="rules")


class ProductStorefrontPlacement(Base):
    __tablename__ = "product_storefront_placements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["storefront_node_id", "release_id"],
            ["storefront_nodes.id", "storefront_nodes.release_id"],
            name="fk_psp_node_same_release",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["mapping_rule_id", "release_id"],
            ["storefront_mapping_rules.id", "storefront_mapping_rules.release_id"],
            name="fk_psp_rule_same_release",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    release_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("storefront_mapping_releases.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    )
    storefront_node_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mapping_rule_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class ProductStorefrontResolution(Base):
    __tablename__ = "product_storefront_resolutions"

    release_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("storefront_mapping_releases.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    resolver_hash: Mapped[str] = mapped_column(String(64), nullable=False)
