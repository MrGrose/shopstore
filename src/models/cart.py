from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.repositories.database import Base


# ORM-модель позиции корзины (пользователь или гость).
class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(user_id, guest_cart_id) = 1",
            name="ck_cart_items_user_or_guest",
        ),
        Index(
            "uq_cart_user_product_no_variant",
            "user_id",
            "product_id",
            unique=True,
            postgresql_where=text("variant_id IS NULL AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_cart_user_product_variant",
            "user_id",
            "product_id",
            "variant_id",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_cart_guest_product_no_variant",
            "guest_cart_id",
            "product_id",
            unique=True,
            postgresql_where=text("variant_id IS NULL AND guest_cart_id IS NOT NULL"),
        ),
        Index(
            "uq_cart_guest_product_variant",
            "guest_cart_id",
            "product_id",
            "variant_id",
            unique=True,
            postgresql_where=text(
                "variant_id IS NOT NULL AND guest_cart_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    guest_cart_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id"), index=True, nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
