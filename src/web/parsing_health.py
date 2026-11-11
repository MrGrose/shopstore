from datetime import datetime
from typing import Any


# Собирает алерт парсинга с приоритетом и подсказками для оператора.
def build_parsing_alert(
    alert_id: str,
    level: str,
    title: str,
    text: str,
    cause: str = "",
    action_hint: str = "",
    priority: int = 50,
    action: str | None = None,
    action_label: str | None = None,
    banner: bool = True,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": alert_id,
        "level": level,
        "title": title,
        "text": text,
        "cause": cause,
        "action_hint": action_hint,
        "priority": priority,
        "banner": banner,
    }
    if action:
        row["action"] = action
    if action_label:
        row["action_label"] = action_label
    return row


# Сортирует алерты: баннеры по priority, остальные — в лог.
def partition_parsing_alerts(
    alerts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    banners = [a for a in alerts if a.get("banner", True)]
    logs = [a for a in alerts if not a.get("banner", True)]
    banners.sort(key=lambda row: int(row.get("priority") or 50))
    logs.sort(key=lambda row: int(row.get("priority") or 50))
    return banners, logs


# Человекочитаемый возраст события относительно now.
def format_relative_age(value: datetime | None, now: datetime) -> str | None:
    if value is None:
        return None
    delta = now - value
    if delta.total_seconds() < 0:
        return "только что"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} д назад"
