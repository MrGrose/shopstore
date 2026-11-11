from src.core.user_display import user_display_label
from src.models.user import User


def test_user_display_label_prefers_name_over_phone() -> None:
    user = User(id=1, name="Иван", email="a@test.com")
    assert user_display_label(user, "+79991234567") == "Иван"


def test_user_display_label_falls_back_to_phone() -> None:
    user = User(id=2, name=None, email="a@test.com")
    assert user_display_label(user, "+79991234567") == "+7 999 123-45-67"


def test_user_display_label_falls_back_to_email_without_phone() -> None:
    user = User(id=3, name=None, email="a@test.com")
    assert user_display_label(user) == "a@test.com"
