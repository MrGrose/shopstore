import re
import secrets
from decimal import ROUND_HALF_UP, Decimal

from src.core.config import settings
from src.models.order import Order

REFERRAL_ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
LEGACY_PS_REFERRAL_CODE = re.compile(r"^PS-\d+$", re.IGNORECASE)
REFERRAL_ALIAS_RESERVED = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "bot",
        "catalog",
        "cart",
        "checkout",
        "login",
        "orders",
        "referral",
        "ref",
        "start",
        "support",
        "terms",
        "privacy",
        "telegram",
        "null",
        "undefined",
    }
)


def is_legacy_ps_referral_code(code: str | None) -> bool:
    raw = (code or "").strip()
    return bool(raw and LEGACY_PS_REFERRAL_CODE.match(raw))


# Постоянный opaque-код (12 hex, ≤16 символов). Не переиспользуется.
def generate_opaque_referral_code() -> str:
    return secrets.token_hex(6)


# Временный уникальный код до flush (колонка NOT NULL, длина ≤ 16).
def pending_referral_code() -> str:
    return ("T" + secrets.token_hex(7))[:16]


def normalize_referral_alias(raw: str | None) -> str:
    return (raw or "").strip().lower()


# Проверяет alias; None — ок, иначе текст ошибки для пользователя.
def validate_referral_alias(normalized: str) -> str | None:
    if not normalized:
        return None
    if normalized.startswith("ps-"):
        return "Alias не может начинаться с ps-"
    if normalized in REFERRAL_ALIAS_RESERVED:
        return "Это слово зарезервировано"
    if not REFERRAL_ALIAS_PATTERN.match(normalized):
        return "Недопустимый формат alias: 3–32 символа, латиница a-z, цифры, _ и -"
    return None


def build_referral_link(code: str) -> str:
    base = (settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    if not base:
        return f"/?ref={code}"
    return f"{base}/?ref={code}"


def build_referral_short_link(alias: str) -> str:
    base = (settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    if not base:
        return f"/ref/{alias}"
    return f"{base}/ref/{alias}"


def build_referral_link_for_user(
    referral_alias: str | None,
    referral_code: str,
) -> str:
    if referral_alias:
        return build_referral_short_link(referral_alias)
    return build_referral_link(referral_code)


def calculate_commission_amount(
    order_amount_rub: Decimal, commission_percent: Decimal
) -> Decimal:
    raw = order_amount_rub * commission_percent / Decimal("100")
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# База для начисления: сумма заказа без доставки.
def order_amount_for_referral_commission(order: Order) -> Decimal:
    total = Decimal(order.total_amount or 0)
    delivery = Decimal(order.delivery_fee_amount or 0)
    base = total - delivery
    return base if base > 0 else Decimal("0")
