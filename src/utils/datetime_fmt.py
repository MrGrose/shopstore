from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
_DISPLAY_FMT = "%d.%m.%Y %H:%M"
_DISPLAY_SHORT_FMT = "%d.%m, %H:%M"
_DISPLAY_COMPACT_FMT = "%d.%m %H:%M"


# Возвращает текущую дату по Москве.
def msk_today() -> date:
    return datetime.now(MSK).date()


def msk_date_start_utc_naive(value: date) -> datetime:
    # 00:00 MSK указанного дня → naive UTC для сравнения с created_at в БД.
    local = datetime(value.year, value.month, value.day, tzinfo=MSK)
    return local.astimezone(UTC).replace(tzinfo=None)


def msk_date_end_exclusive_utc_naive(value: date) -> datetime:
    # 00:00 MSK следующего дня → верхняя граница (исключающая).
    next_day = value + timedelta(days=1)
    local = datetime(next_day.year, next_day.month, next_day.day, tzinfo=MSK)
    return local.astimezone(UTC).replace(tzinfo=None)


def utc_now_naive() -> datetime:
    # Возвращает текущую дату и время в UTC, naive.
    return datetime.now(UTC).replace(tzinfo=None)


def _as_utc_aware(value: datetime) -> datetime:
    # Преобразует naive UTC в aware UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_datetime_msk(
    value: datetime | None,
    *,
    with_tz_label: bool = True,
) -> str | None:
    # Форматирует naive/aware UTC из БД в локальное время Москвы.
    if value is None:
        return None
    local = _as_utc_aware(value).astimezone(MSK)
    text = local.strftime(_DISPLAY_FMT)
    if with_tz_label:
        return f"{text} мск"
    return text


def _format_naive_utc_msk(value: datetime, fmt: str) -> str:
    local = _as_utc_aware(value).astimezone(MSK)
    return local.strftime(fmt)


def _coerce_iso_to_naive_utc(value: str | datetime | None) -> datetime | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return text
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.astimezone(UTC)
        return parsed.replace(tzinfo=None)
    return value


def format_datetime_msk_short(value: datetime | None) -> str | None:
    # Компактная дата/время в MSK для UI оплаты: 29.06, 15:23.
    if value is None:
        return None
    return _format_naive_utc_msk(value, _DISPLAY_SHORT_FMT)


def format_datetime_msk_compact(value: datetime | None) -> str | None:
    # Компактная дата/время в MSK для ops TG: 15.07 18:20.
    if value is None:
        return None
    return _format_naive_utc_msk(value, _DISPLAY_COMPACT_FMT)


def _format_iso_datetime_msk(value: str | datetime | None, fmt: str) -> str | None:
    coerced = _coerce_iso_to_naive_utc(value)
    if coerced is None:
        return None
    if isinstance(coerced, str):
        return coerced
    return _format_naive_utc_msk(coerced, fmt)


def format_iso_datetime_msk_short(value: str | datetime | None) -> str | None:
    # ISO или naive UTC → компактное MSK без подписи «мск».
    return _format_iso_datetime_msk(value, _DISPLAY_SHORT_FMT)


def format_iso_datetime_msk_compact(value: str | datetime | None) -> str | None:
    # ISO или naive UTC → компактное MSK без запятой (ops TG).
    return _format_iso_datetime_msk(value, _DISPLAY_COMPACT_FMT)


def format_utc_iso_z(value: datetime | None) -> str | None:
    # Сериализует naive UTC из БД в ISO 8601 с суффиксом Z.
    if value is None:
        return None
    return _as_utc_aware(value).strftime("%Y-%m-%dT%H:%M:%SZ")
