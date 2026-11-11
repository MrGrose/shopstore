from typing import Any


# Преобразует значение в обрезанную строку или None.
def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
