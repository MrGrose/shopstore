from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.repositories.database import Base


class PhoneVerificationSessionRecord(Base):
    __tablename__ = "phone_verification_sessions"
    __table_args__ = (
        UniqueConstraint(
            "session_key", name="uq_phone_verification_sessions_session_key"
        ),
        Index("ix_phone_verification_sessions_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
