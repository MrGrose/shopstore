from datetime import UTC, datetime

from src.core.config import settings

_LEGAL_REQUIRED_FIELDS = (
    "LEGAL_ENTITY_NAME",
    "LEGAL_INN",
    "LEGAL_OGRNIP",
    "LEGAL_ADDRESS",
    "LEGAL_EMAIL",
    "LEGAL_PHONE",
)


# Получает дату редакции юридических документов.
def _revision_date() -> str:
    raw = settings.LEGAL_REVISION_DATE.strip()
    if raw:
        return raw
    return datetime.now(UTC).strftime("%d.%m.%Y")


# Проверяет, все ли обязательные реквизиты заданы.
def legal_is_configured() -> bool:
    return all(
        getattr(settings, name).strip()  # type: ignore[attr-defined]
        for name in _LEGAL_REQUIRED_FIELDS
    )


# Контекст юридических документов (реквизиты оператора).
def storefront_legal_context() -> dict[str, str | bool]:
    year = datetime.now(UTC).year
    return {
        "entity_name": settings.LEGAL_ENTITY_NAME.strip(),
        "inn": settings.LEGAL_INN.strip(),
        "ogrn": settings.LEGAL_OGRNIP.strip(),
        "address": settings.LEGAL_ADDRESS.strip(),
        "email": settings.LEGAL_EMAIL.strip(),
        "phone": settings.LEGAL_PHONE.strip(),
        "year": str(year),
        "revision_date": _revision_date(),
        "brand": "Shopstore",
        "public_site_url": settings.PUBLIC_SITE_URL.strip(),
        "is_configured": legal_is_configured(),
    }


# Контекст HTML-фрагмента для React (модалка / LegalPage).
def legal_fragment_context() -> dict[str, str]:
    return {"legal_qs": ""}
