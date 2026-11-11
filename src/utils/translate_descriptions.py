import logging
import random
import time

import httpx

from src.utils.html_text import is_manufacturer_imprint_description

logger = logging.getLogger(__name__)

# Лимит запроса к бесплатному Google Translate (с запасом).
_MAX_CHUNK = 4500
# Реальные PDP ~1k; раздутые raw 175k+ не гоняем в recovery.
HUGE_RAW_CHARS = 20_000
_RATE_LIMIT_ATTEMPTS = 3
_APOSTROPHE_MAP = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


# True, если в тексте заметная доля кириллицы (текст уже на русском).
def is_mostly_russian(text: str, threshold: float = 0.25) -> bool:
    if not text or len(text) < 12:
        return False
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    return (cyrillic / len(text)) >= threshold


# Нормализует апострофы для детекта Google error page.
def _normalize_apostrophes(text: str) -> str:
    return text.translate(_APOSTROPHE_MAP)


# True для HTML/текста Google Translate error page (HTTP 200).
def is_google_error_page(text: str | None) -> bool:
    raw = _normalize_apostrophes(text or "").lower()
    if not raw:
        return False
    return "error 500" in raw or "that's all we know" in raw


# True, если ответ переводчика нельзя писать в description_ru.
def is_invalid_translation_response(source: str | None, translated: str | None) -> bool:
    src = (source or "").strip()
    out = (translated or "").strip()
    if not out:
        return True
    if is_google_error_page(out):
        return True
    return bool(src) and out == src


# True, если сохранённый description_ru можно показывать и не переводить заново.
def stored_description_ru_is_valid(ru: str | None) -> bool:
    text = (ru or "").strip()
    if not text or is_google_error_page(text):
        return False
    return is_mostly_russian(text)


# Причина пропуска recovery или None, если SKU надо переводить.
def translation_backfill_skip_reason(
    raw: str | None,
    ru: str | None,
    is_active: bool,
    force: bool = False,
    raw_hash: str | None = None,
    translated_hash: str | None = None,
) -> str | None:
    cleaned = (raw or "").strip()
    if not cleaned:
        return "empty_raw"
    if force:
        return None
    if not is_active:
        return "inactive"
    if len(cleaned) >= HUGE_RAW_CHARS:
        return "huge_raw"
    if is_manufacturer_imprint_description(cleaned):
        return "imprint"
    if is_mostly_russian(cleaned):
        return "raw_ru"
    if stored_description_ru_is_valid(ru):
        if (
            raw_hash is not None
            and translated_hash is not None
            and translated_hash != raw_hash
        ):
            return None
        return "valid_ru"
    return None


# True, если исключение похоже на Google rate limit / 429.
def _is_rate_limited(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "too many requests" in msg or "429" in msg


# Вызывает GoogleTranslator; для тестов патчится.
def _google_translate(text: str, source: str) -> str:
    from deep_translator import GoogleTranslator

    tr = GoogleTranslator(source=source, target="ru")
    return tr.translate(text[:_MAX_CHUNK])


# URL и timeout LibreTranslate; пустой URL = fallback выключен.
def _libre_settings() -> tuple[str, float]:
    from src.scraper.config.settings import load_settings

    settings = load_settings()
    return (settings.libretranslate_url or "").rstrip("/"), float(
        settings.libretranslate_timeout
    )


# Для catalog EN после фильтра raw_ru: auto → en.
def _libre_source(source: str) -> str:
    code = (source or "").strip()
    if not code or code == "auto":
        return "en"
    return code


# Один POST на self-hosted LibreTranslate; сеть/мусор → None.
def _libre_translate(text: str, source: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    base_url, timeout = _libre_settings()
    if not base_url:
        return None
    try:
        response = httpx.post(
            f"{base_url}/translate",
            json={
                "q": raw[:_MAX_CHUNK],
                "source": _libre_source(source),
                "target": "ru",
                "format": "text",
            },
            timeout=timeout,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("LibreTranslate не ответил: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("LibreTranslate HTTP %s", response.status_code)
        return None
    try:
        payload = response.json()
    except ValueError:
        logger.warning("LibreTranslate вернул не JSON")
        return None
    if not isinstance(payload, dict):
        return None
    translated = payload.get("translatedText")
    if not isinstance(translated, str):
        return None
    cleaned = translated.strip()
    return cleaned or None


# LibreTranslate + тот же Phase 5 validator.
def _validated_libre(raw: str, source: str) -> str | None:
    translated = _libre_translate(raw, source)
    if translated is None:
        return None
    if is_invalid_translation_response(raw, translated):
        logger.warning(
            "LibreTranslate отклонён как невалидный (%s)",
            raw[:80],
        )
        return None
    return translated


# Переводит один фрагмент; Google primary, LT fallback, иначе None.
def _translate_chunk(text: str, source: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    last_exc: BaseException | None = None
    for attempt in range(1, _RATE_LIMIT_ATTEMPTS + 1):
        try:
            out = _google_translate(raw, source)
            cleaned = (out or "").strip()
            if is_invalid_translation_response(raw, cleaned):
                logger.warning(
                    "Google-перевод отклонён (%s), пробуем LibreTranslate",
                    raw[:80],
                )
                return _validated_libre(raw, source)
            return cleaned
        except Exception as exc:
            last_exc = exc
            if _is_rate_limited(exc) and attempt < _RATE_LIMIT_ATTEMPTS:
                delay = min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.3)
                logger.warning(
                    "Лимит Google Translate, повтор %s/%s через %.1fс: %s",
                    attempt,
                    _RATE_LIMIT_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue
            logger.warning(
                "Google-перевод не удался (%s): %s, пробуем LibreTranslate",
                raw[:80],
                exc,
            )
            return _validated_libre(raw, source)
    logger.warning(
        "Google-перевод не удался (%s): %s, пробуем LibreTranslate",
        raw[:80],
        last_exc,
    )
    return _validated_libre(raw, source)


# Переводит короткий plain-text на русский (каталог, DHL-статусы и т.п.).
def translate_plain_text_to_ru(text: str, source: str = "en") -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    if is_mostly_russian(raw):
        return raw
    translated = _translate_chunk(raw, source=source)
    if translated is None:
        return raw
    return translated


# Переводит описание целиком; любой невалидный чанк → None.
def translate_description_html(
    text: str, source: str, sleep_range: tuple[float, float]
) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None

    parts: list[str] = []
    pos = 0
    while pos < len(raw):
        chunk = raw[pos : pos + _MAX_CHUNK]  # noqa: E203
        pos += _MAX_CHUNK
        translated = _translate_chunk(chunk, source=source)
        if translated is None:
            return None
        parts.append(translated)
        if pos < len(raw):
            time.sleep(random.uniform(*sleep_range))
    joined = "".join(parts)
    if is_invalid_translation_response(raw, joined):
        return None
    return joined
