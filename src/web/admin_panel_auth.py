import secrets

from src.core.config import settings


def verify_admin_panel_credentials(username: str, password: str) -> bool:
    expected_login = settings.ADMIN_PANEL_LOGIN.strip()
    expected_password = settings.ADMIN_PANEL_PASSWORD.strip()
    if not expected_login or not expected_password:
        return False
    return secrets.compare_digest(
        username.strip().encode("utf-8"),
        expected_login.encode("utf-8"),
    ) and secrets.compare_digest(
        password.strip().encode("utf-8"),
        expected_password.encode("utf-8"),
    )
