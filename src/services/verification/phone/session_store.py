import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from src.core.config import settings
from src.models.phone_verification_session import PhoneVerificationSessionRecord
from src.repositories.session import async_session_maker

logger = logging.getLogger(__name__)

VerificationPurpose = Literal["login", "link"]


@dataclass
class PhoneVerificationSession:
    request_id: str
    attempts: int
    sent_at: datetime


# Строит Redis-ключ сессии phone verify.
def phone_session_key(
    phone_e164: str,
    purpose: VerificationPurpose,
    user_id: int | None,
) -> str:
    if purpose == "link" and user_id is not None:
        return f"phone_verify:link:{user_id}:{phone_e164}"
    return f"phone_verify:{phone_e164}"


class PhoneSessionStore:
    # Хранит request_id между send-code и verify; Redis primary, PostgreSQL fallback.
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def save(
        self,
        phone_e164: str,
        purpose: VerificationPurpose,
        request_id: str,
        user_id: int | None = None,
    ) -> None:
        sent_at = datetime.now(tz=UTC)
        record = {
            "request_id": request_id,
            "attempts": 0,
            "sent_at": sent_at.isoformat(),
        }
        key = phone_session_key(phone_e164, purpose, user_id)
        try:
            await self.redis.setex(
                key,
                settings.PHONE_LOGIN_CODE_TTL_SECONDS,
                json.dumps(record),
            )
        except RedisError as exc:
            logger.warning(
                "Redis session store недоступен, fallback в PostgreSQL: %s",
                exc,
            )
            await self._save_db(key, request_id, 0, sent_at)

    async def load(
        self,
        phone_e164: str,
        purpose: VerificationPurpose,
        user_id: int | None = None,
    ) -> PhoneVerificationSession | None:
        key = phone_session_key(phone_e164, purpose, user_id)
        try:
            raw = await self.redis.get(key)
            if raw:
                session = _session_from_json(raw)
                if session is not None:
                    return session
            return None
        except RedisError as exc:
            logger.warning(
                "Redis session store недоступен, читаем из PostgreSQL: %s",
                exc,
            )
            return await self._load_db(key)

    async def increment_attempts(
        self,
        phone_e164: str,
        purpose: VerificationPurpose,
        session: PhoneVerificationSession,
        user_id: int | None = None,
    ) -> None:
        key = phone_session_key(phone_e164, purpose, user_id)
        next_attempts = session.attempts + 1
        record = {
            "request_id": session.request_id,
            "attempts": next_attempts,
            "sent_at": session.sent_at.isoformat(),
        }
        try:
            ttl = await self.redis.ttl(key)
            if ttl > 0:
                await self.redis.setex(key, ttl, json.dumps(record))
                return
        except RedisError as exc:
            logger.warning(
                "Redis session store недоступен, обновляем PostgreSQL: %s",
                exc,
            )
        await self._update_db_attempts(key, next_attempts)

    async def delete(
        self,
        phone_e164: str,
        purpose: VerificationPurpose,
        user_id: int | None = None,
    ) -> None:
        key = phone_session_key(phone_e164, purpose, user_id)
        try:
            await self.redis.delete(key)
        except RedisError as exc:
            logger.warning(
                "Redis session store недоступен, удаляем из PostgreSQL: %s",
                exc,
            )
        await self._delete_db(key)

    async def _save_db(
        self,
        key: str,
        request_id: str,
        attempts: int,
        sent_at: datetime,
    ) -> None:
        expires_at = sent_at + timedelta(seconds=settings.PHONE_LOGIN_CODE_TTL_SECONDS)
        async with async_session_maker() as session:
            await session.execute(
                delete(PhoneVerificationSessionRecord).where(
                    PhoneVerificationSessionRecord.expires_at < datetime.now(tz=UTC)
                )
            )
            stmt = (
                insert(PhoneVerificationSessionRecord)
                .values(
                    session_key=key,
                    request_id=request_id,
                    attempts=attempts,
                    sent_at=sent_at,
                    expires_at=expires_at,
                )
                .on_conflict_do_update(
                    index_elements=["session_key"],
                    set_={
                        "request_id": request_id,
                        "attempts": attempts,
                        "sent_at": sent_at,
                        "expires_at": expires_at,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def _load_db(self, key: str) -> PhoneVerificationSession | None:
        now = datetime.now(tz=UTC)
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(PhoneVerificationSessionRecord).where(
                        PhoneVerificationSessionRecord.session_key == key,
                        PhoneVerificationSessionRecord.expires_at > now,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return PhoneVerificationSession(
            request_id=row.request_id,
            attempts=row.attempts,
            sent_at=row.sent_at,
        )

    async def _update_db_attempts(self, key: str, attempts: int) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(PhoneVerificationSessionRecord)
                .where(
                    PhoneVerificationSessionRecord.session_key == key,
                    PhoneVerificationSessionRecord.expires_at > datetime.now(tz=UTC),
                )
                .values(attempts=attempts)
            )
            await session.commit()

    async def _delete_db(self, key: str) -> None:
        async with async_session_maker() as session:
            await session.execute(
                delete(PhoneVerificationSessionRecord).where(
                    PhoneVerificationSessionRecord.session_key == key
                )
            )
            await session.commit()


# Парсит JSON-сессию из Redis.
def _session_from_json(raw: str) -> PhoneVerificationSession | None:
    record = json.loads(raw)
    request_id = str(record.get("request_id") or "").strip()
    if not request_id:
        return None
    sent_raw = record.get("sent_at")
    sent_at = datetime.now(tz=UTC)
    if isinstance(sent_raw, str) and sent_raw.strip():
        try:
            sent_at = datetime.fromisoformat(sent_raw)
        except ValueError:
            pass
    return PhoneVerificationSession(
        request_id=request_id,
        attempts=int(record.get("attempts") or 0),
        sent_at=sent_at,
    )
