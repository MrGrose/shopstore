import re
from html import unescape


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def extract_first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I | re.S)
    return clean_text(m.group(1)) if m else ""


def _decode_json_escaped_href(href: str) -> str:
    raw = unescape(href or "").strip()
    if not raw or "\\" not in raw:
        return raw
    # Inline productData on supplier-demo keeps JSON-style escapes in parsed strings.
    raw = raw.replace("\\/", "/")
    if "\\" in raw:
        try:
            decoded = bytes(raw, "utf-8").decode("unicode_escape")
            if decoded:
                raw = decoded
        except UnicodeDecodeError:
            raw = raw.replace("\\", "")
    return raw


def normalize_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    raw = _decode_json_escaped_href(href)

    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    if raw.startswith("//"):
        return f"https:{raw}"

    if raw.startswith("www."):
        return f"https://{raw}"

    if not raw.startswith("/"):
        raw = "/" + raw

    base = base_url.rstrip("/")
    return f"{base}{raw}"
