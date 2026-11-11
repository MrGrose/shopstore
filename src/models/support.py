from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.repositories.database import Base


# Тема обращения
class SupportTopic(StrEnum):
    ORDER_QUESTION = "order_question"
    DELIVERY_QUESTION = "delivery_question"
    PRODUCT_PROBLEM = "product_problem"
    REFERRER_CHANGE = "referrer_change"
    GENERAL = "general"


# Статус обращения
class SupportTicketStatus(StrEnum):
    WAITING_STAFF = "waiting_staff"
    WAITING_CUSTOMER = "waiting_customer"
    CLOSED = "closed"


# Кто закрыл обращение
class SupportClosedBy(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"


# Кто отправил сообщение
class SupportMessageAuthor(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"


# Обращение
class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_user_status", "user_id", "status"),
        Index("ix_support_tickets_order_id", "order_id"),
        Index("ix_support_tickets_closed_at", "closed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    topic: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    closed_by: Mapped[str | None] = mapped_column(String(16), nullable=True)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        Index("ix_support_messages_ticket_created", "ticket_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False
    )
    author_type: Mapped[str] = mapped_column(String(16), nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_delivered: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    attachments: Mapped[list["SupportMessageAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="SupportMessageAttachment.id",
    )


class SupportMessageAttachment(Base):
    __tablename__ = "support_message_attachments"
    __table_args__ = (Index("ix_support_message_attachments_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("support_messages.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    message: Mapped[SupportMessage] = relationship(back_populates="attachments")
