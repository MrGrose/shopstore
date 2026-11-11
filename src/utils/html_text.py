import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_IMPRINT_MAX_LEN = 150
_IMPRINT_MARKERS = (
    "TRADINTER",
    "Nike Retail",
    "Focus International",
    "adidas AG",
    "Spodeco GmbH",
    "Supplier-Demo Europe",
)


# Убирает HTML-теги и нормализует пробелы в plain text.
def strip_html_plaintext(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "<" not in text:
        return text
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = _SPACE_RE.sub(" ", unescape(cleaned)).strip()
    return cleaned or None


# True для короткого legal/imprint текста производителя вместо описания товара.
def is_manufacturer_imprint_description(text: str | None) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) >= _IMPRINT_MAX_LEN:
        return False
    lower = cleaned.lower()
    if "www." in lower:
        return True
    return any(marker.lower() in lower for marker in _IMPRINT_MARKERS)


# Убирает хвостовой manufacturer imprint из полного описания.
def strip_manufacturer_imprint_from_description(text: str | None) -> str:
    cleaned = _SPACE_RE.sub(" ", (text or "").strip())
    if not cleaned:
        return ""
    if is_manufacturer_imprint_description(cleaned):
        return ""
    for marker in _IMPRINT_MARKERS:
        idx = cleaned.find(marker)
        if idx > 100:
            cleaned = cleaned[:idx].strip()
            break
    lower = cleaned.lower()
    www_idx = lower.rfind("www.")
    if www_idx > 100 and len(cleaned) - www_idx < 80:
        prefix = cleaned[:www_idx].strip()
        if len(prefix) > 100:
            cleaned = prefix
    return cleaned.strip()
