from datetime import UTC, datetime, timedelta

import jwt

from src.core.config import settings


# Создает JWT access token для API.
def create_access_token(user_id: int) -> str:
    now_utc = datetime.now(tz=UTC)
    payload = {
        # Subject(кто)
        "sub": str(user_id),
        # Issued at(когда выдан)
        "iat": now_utc,
        # Expiration(когда истекает)
        "exp": now_utc + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS),
    }
    # Подписываем payload секретом HS256 и возвращаем JWT-строку.
    return jwt.encode(payload, settings.AUTH_SECRET, algorithm="HS256")


# Проверяет JWT подпись и срок действия.
def verify_access_token(token: str) -> int | None:
    try:
        # decode одновременно:
        # 1) проверяет подпись,
        # 2) проверяет exp,
        # 3) принимает только HS256.
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        # Любая проблема с токеном => невалидный.
        return None

    # Достаем subject.
    sub_value = payload.get("sub")
    if sub_value is None:
        return None

    try:
        return int(sub_value)
    except (TypeError, ValueError):
        return None
