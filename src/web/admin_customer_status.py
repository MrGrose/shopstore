from src.core.customer_activity import customer_activity_status

CUSTOMER_ACTIVITY_LABELS: dict[str, str] = {
    "active": "Активен",
    "new": "Новый",
    "inactive": "Неактивен",
}

__all__ = ["customer_activity_status", "CUSTOMER_ACTIVITY_LABELS"]
