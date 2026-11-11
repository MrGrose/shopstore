from src.models.user import User

LOGIN_UNAVAILABLE_DETAIL = "login_unavailable"


# Проверяет, что аккаунт не деактивирован администратором.
def user_is_active(user: User | None) -> bool:
    if user is None:
        return False
    return bool(getattr(user, "is_active", True))


# Запрещает вход и действия от имени деактивированного пользователя.
def assert_user_can_authenticate(user: User) -> None:
    if not user_is_active(user):
        raise ValueError(LOGIN_UNAVAILABLE_DETAIL)
