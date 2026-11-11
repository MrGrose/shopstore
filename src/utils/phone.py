import re

MSG_PHONE = "Укажите российский мобильный номер (+79991234567)"


# Нормализует российский мобильный номер в E.164 (+79XXXXXXXXX).
def normalize_ru_mobile_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("79"):
        raise ValueError(MSG_PHONE)
    return f"+{digits}"


# Маскирует телефон для логов.
def mask_phone(phone: str) -> str:
    normalized = phone.strip()
    if len(normalized) < 8:
        return "***"
    return f"{normalized[:5]}***{normalized[-2:]}"


# Форматирует E.164 российского мобильного для отображения (+7 999 123-45-67).
def format_ru_phone_display(e164: str) -> str:
    digits = re.sub(r"\D", "", e164)
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return e164.strip()
