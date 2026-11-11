from src.models.user import User
from src.utils.phone import format_ru_phone_display


# Короткая подпись пользователя для админки и ЛК.
def user_display_label(
    user: User,
    login_phone_e164: str | None = None,
) -> str:
    if user.name and user.name.strip():
        return user.name.strip()
    if login_phone_e164 and login_phone_e164.strip():
        return format_ru_phone_display(login_phone_e164.strip())
    if user.email and user.email.strip():
        return user.email.strip()
    if user.referral_code and user.referral_code.strip():
        return user.referral_code.strip()
    return f"#{user.id}"
