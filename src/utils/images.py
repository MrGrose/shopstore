import uuid
from collections.abc import Iterable
from io import BytesIO
from mimetypes import guess_extension
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import urlparse, urlunparse

import aiohttp
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps

from src.core.config import settings
from src.storage import get_storage
from src.storage.base import Storage

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_media_root_setting = Path(settings.MEDIA_ROOT)
MEDIA_ROOT = (
    _media_root_setting
    if _media_root_setting.is_absolute()
    else BASE_DIR / _media_root_setting
)
MEDIA_URL_PREFIX = f"/{MEDIA_ROOT.relative_to(BASE_DIR).as_posix()}"
PRODUCT_MEDIA_NAMESPACE = "products"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = settings.MAX_IMAGE_SIZE
PREVIEW_SIZES = tuple(settings.PREVIEW_SIZES)
PREVIEW_STEM_SUFFIXES = tuple(f"_{size}" for size in PREVIEW_SIZES)
_LEGACY_VARIANT_STEM_SUFFIXES = ("_w160", "_w560", "_w1400")
_ORIGINAL_SKIP_STEM_SUFFIXES = PREVIEW_STEM_SUFFIXES + _LEGACY_VARIANT_STEM_SUFFIXES
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CONTENT_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
IMAGE_VARIANT_ORIGINAL = "original"
# Truncated originals из I7: variants нет, I8 не чинит и не удаляет.
KNOWN_CORRUPT_ORIGINAL_NAMES = frozenset(
    {
        "1abb58ec-b3ba-479a-b9ef-5996266c6277.jpg",
        "9fa80b7d-d24b-460e-9095-c21a5c6d8535.jpg",
    }
)

_JPEG_SUFFIXES = {".jpg", ".jpeg"}
_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


# Логический ключ product media (не filesystem path).
def product_media_key(file_name: str) -> str:
    return f"{PRODUCT_MEDIA_NAMESPACE}/{file_name}"


# Ключ по публичному URL /media/products/foo.jpg.
def product_media_key_from_url(url: str | None) -> str | None:
    if not is_local_product_media_url(url):
        return None
    return product_media_key(Path(url).name)


# Content-Type по расширению файла.
def product_media_content_type(file_name: str) -> str:
    return _CONTENT_TYPE_BY_SUFFIX.get(Path(file_name).suffix.lower(), "image/jpeg")


# True если имя — original, не _300/_600/_900 и не legacy w-variant.
def is_product_original_filename(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return False
    return not any(path.stem.endswith(tag) for tag in _ORIGINAL_SKIP_STEM_SUFFIXES)


# True если имя — preview _300/_600/_900.
def is_product_variant_filename(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return False
    return any(path.stem.endswith(tag) for tag in PREVIEW_STEM_SUFFIXES)


# Имя original без суффикса _300/_600/_900.
def original_product_filename(name: str) -> str:
    path = Path(name)
    stem = path.stem
    for tag in PREVIEW_STEM_SUFFIXES:
        if stem.endswith(tag):
            stem = stem[: -len(tag)]
            break
    return f"{stem}{path.suffix}"


# Pathname локального product media; иначе None (remote/прочее).
def _local_product_media_path(url: str) -> str | None:
    raw = url.strip()
    if not raw:
        return None
    path = raw
    if raw.startswith("http://") or raw.startswith("https://"):
        path = urlparse(raw).path
    prefix = f"{MEDIA_URL_PREFIX}/"
    if not path.startswith(prefix):
        return None
    return path


# Собирает URL, сохраняя scheme/host у абсолютных ссылок.
def _rebuild_url(original_url: str, new_path: str) -> str:
    stripped = original_url.strip()
    if stripped.startswith("http://") or stripped.startswith("https://"):
        parsed = urlparse(stripped)
        return urlunparse(parsed._replace(path=new_path))
    return new_path


# URL original или variant без проверки существования в Storage.
def resolve_product_image_url(
    url: str | None, variant: str | int = IMAGE_VARIANT_ORIGINAL
) -> str | None:
    if url is None:
        return None
    stripped = url.strip()
    if not stripped:
        return None
    media_path = _local_product_media_path(stripped)
    if media_path is None:
        return stripped
    original_name = original_product_filename(Path(media_path).name)
    original_path = str(Path(media_path).with_name(original_name))
    if variant == IMAGE_VARIANT_ORIGINAL:
        return _finalize_product_media_url(_rebuild_url(stripped, original_path))
    try:
        size = int(variant)
    except (TypeError, ValueError):
        return _finalize_product_media_url(_rebuild_url(stripped, original_path))
    if size not in PREVIEW_SIZES:
        return _finalize_product_media_url(_rebuild_url(stripped, original_path))
    variant_name = f"{Path(original_name).stem}_{size}{Path(original_name).suffix}"
    variant_path = str(Path(media_path).with_name(variant_name))
    return _finalize_product_media_url(_rebuild_url(stripped, variant_path))


# Сохраняет оригинал и превью через Storage.
def _store_product_bytes(
    file_name: str, content: bytes, content_type: str | None
) -> str:
    storage = get_storage()
    key = product_media_key(file_name)
    storage.put(key, content, content_type)
    suffix = Path(file_name).suffix
    stem = Path(file_name).stem
    for size, data in _preview_payloads(content, suffix):
        storage.put(product_media_key(f"{stem}_{size}{suffix}"), data, content_type)
    # Canonical path в БД — всегда relative; CDN base только на границе API.
    return f"{MEDIA_URL_PREFIX}/{Path(file_name).name}"


# Сохраняет загруженное изображение товара.
async def save_product_image(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Разрешены изображения в формате JPG, PNG или WebP",
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Изображение слишком большое",
        )

    extension = Path(file.filename or "").suffix.lower() or ".jpg"
    file_name = f"{uuid.uuid4()}{extension}"
    return _store_product_bytes(file_name, content, file.content_type)


# Локальный URL в каталоге media/products.
def is_local_product_media_url(url: str | None) -> TypeGuard[str]:
    return bool(url and url.startswith(f"{MEDIA_URL_PREFIX}/"))


# HTTP supplier URL или None.
def _http_source_url(url: str | None) -> str | None:
    raw = (url or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return None


# Битый supplier URL (экранированные слеши, дубль supplier-demo.com).
def is_malformed_product_image_url(url: str | None) -> bool:
    raw = (url or "").strip()
    if not raw:
        return True
    if "\\/\\/" in raw or "/\\/\\/" in raw:
        return True
    lowered = raw.lower()
    if lowered.count("supplier-demo.com") > 1:
        return True
    return False


# Primary и CDN fallback из колонок БД без обращения к Storage.
def resolve_stored_product_image(
    stored_url: str | None,
    source_url: str | None = None,
) -> tuple[str | None, str | None]:
    stored = (stored_url or "").strip() or None
    source = _http_source_url(source_url) or _http_source_url(stored)
    if source and is_malformed_product_image_url(source):
        source = None
    managed = stored if is_local_product_media_url(stored) else None
    primary = managed or source
    fallback = source if managed and source else None
    return primary, fallback


# Базовый origin из MEDIA_PUBLIC_BASE без хвостового слэша.
def media_public_base() -> str:
    return settings.MEDIA_PUBLIC_BASE.strip().rstrip("/")


# Managed /media/products/... → absolute URL, если задан MEDIA_PUBLIC_BASE.
def public_product_media_url(url: str | None) -> str | None:
    if url is None:
        return None
    stripped = url.strip()
    if not stripped:
        return None
    media_path = _local_product_media_path(stripped)
    if media_path is None:
        return stripped
    base = media_public_base()
    if not base:
        return stripped
    if not media_path.startswith("/"):
        media_path = f"/{media_path}"
    return f"{base}{media_path}"


# Storage key products/{file} → URL витрины (CDN или относительный /media/products).
def public_url_for_storage_key(key: str) -> str:
    normalized = key.replace("\\", "/").strip()
    if (
        not normalized
        or normalized.startswith("/")
        or ".." in Path(normalized).parts
        or not normalized.startswith(f"{PRODUCT_MEDIA_NAMESPACE}/")
    ):
        raise ValueError("Некорректный storage key для product media URL")
    file_name = Path(normalized).name
    relative = f"{MEDIA_URL_PREFIX}/{file_name}"
    exposed = public_product_media_url(relative)
    return exposed if exposed else relative


# Применяет public_product_media_url к уже собранному URL (cover, variant).
def _finalize_product_media_url(url: str) -> str:
    exposed = public_product_media_url(url)
    return exposed if exposed is not None else url


# Для Pydantic field_validator: строка или None без изменений, иначе public URL.
def coerce_public_product_media_url(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    return public_product_media_url(value) or value


# Cover витрины: managed /media, иначе CDN, иначе None. Без Storage I/O.
def resolve_product_cover_url(
    image_url: str | None,
    images: Iterable[Any] = (),
) -> str | None:
    if is_local_product_media_url(image_url):
        return _finalize_product_media_url(image_url)
    rows = sorted(images, key=lambda image: getattr(image, "position", 0) or 0)
    first_remote: str | None = None
    for image in rows:
        primary, _fallback = resolve_stored_product_image(
            getattr(image, "url", None),
            getattr(image, "source_url", None),
        )
        if is_local_product_media_url(primary):
            return _finalize_product_media_url(primary)
        if first_remote is None and primary:
            first_remote = primary
    if first_remote:
        return first_remote
    legacy = _http_source_url(image_url)
    if legacy and not is_malformed_product_image_url(legacy):
        return legacy
    return None


# Есть ли файл product media по публичному URL.
def local_product_media_exists(url: str) -> bool:
    key = product_media_key_from_url(url)
    return key is not None and get_storage().exists(key)


# Имена файлов на диске (оригинал + превью) для локального URL.
def local_media_filenames(url: str | None) -> set[str]:
    if not is_local_product_media_url(url):
        return set()
    name = Path(url).name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for size in PREVIEW_SIZES:
        tag = f"_{size}"
        if stem.endswith(tag):
            stem = stem[: -len(tag)]
            break
    return {f"{stem}{suffix}"} | {f"{stem}_{size}{suffix}" for size in PREVIEW_SIZES}


# Удаляет локальное изображение и все его превью.
def remove_product_image(url: str | None) -> None:
    storage = get_storage()
    for file_name in local_media_filenames(url):
        storage.delete(product_media_key(file_name))


# Снимает с диска главное фото и галерею товара (перед заменой при импорте).
def discard_product_local_media(
    image_url: str | None,
    gallery_urls: Iterable[str | None] = (),
) -> None:
    seen: set[str] = set()
    for url in (image_url, *gallery_urls):
        if not url or url in seen:
            continue
        seen.add(url)
        remove_product_image(url)


# Собирает имена файлов, на которые есть ссылки в БД.
def collect_referenced_media_filenames(urls: Iterable[str | None]) -> set[str]:
    referenced: set[str] = set()
    for url in urls:
        referenced.update(local_media_filenames(url))
    return referenced


# Файлы в media/products, не упомянутые в referenced_filenames.
def find_orphan_media_files(referenced_filenames: set[str]) -> list[Path]:
    if not MEDIA_ROOT.is_dir():
        return []
    return [
        path
        for path in MEDIA_ROOT.iterdir()
        if path.is_file() and path.name not in referenced_filenames
    ]


# Пишет отсутствующие _300/_600/_900 через Storage; существующие не трогает.
def ensure_product_preview_variants(
    storage: Storage, original_key: str, apply: bool
) -> dict[str, int]:
    name = Path(original_key).name
    original_name = original_product_filename(name)
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    already_exists = 0
    pending: list[tuple[int, str]] = []
    for size in PREVIEW_SIZES:
        variant_key = product_media_key(f"{stem}_{size}{suffix}")
        if storage.exists(variant_key):
            already_exists += 1
        else:
            pending.append((size, variant_key))
    missing = len(pending)
    if not apply or not pending:
        return {
            "already_exists": already_exists,
            "missing": missing,
            "created": 0,
        }
    content = storage.read(original_key)
    payloads = dict(_preview_payloads(content, suffix))
    content_type = product_media_content_type(name)
    created = 0
    for size, variant_key in pending:
        storage.put(variant_key, payloads[size], content_type)
        created += 1
    return {
        "already_exists": already_exists,
        "missing": 0,
        "created": created,
    }


# JPEG не поддерживает прозрачность — клеим на белый фон.
def _flatten_alpha_to_rgb(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


# Готовит картинку к сохранению в формате исходного файла.
def _image_for_suffix(image: Image.Image, suffix: str) -> Image.Image:
    if suffix.lower() not in _JPEG_SUFFIXES:
        return image
    if image.mode in {"RGBA", "LA", "P"}:
        return _flatten_alpha_to_rgb(image)
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


# Считает байты превью 300/600/900: thumbnail LANCZOS, без upscale.
def _preview_payloads(content: bytes, suffix: str) -> list[tuple[int, bytes]]:
    fmt = _FORMAT_BY_SUFFIX.get(suffix.lower())
    with Image.open(BytesIO(content)) as src:
        base = ImageOps.exif_transpose(src)
        base.load()
    payloads: list[tuple[int, bytes]] = []
    for size in PREVIEW_SIZES:
        preview = base.copy()
        preview.thumbnail((size, size), Image.Resampling.LANCZOS)
        to_save = _image_for_suffix(preview, suffix)
        buffer = BytesIO()
        if fmt is None:
            to_save.save(buffer)
        else:
            to_save.save(buffer, format=fmt)
        payloads.append((size, buffer.getvalue()))
    return payloads


# Генерирует превью 300/600/900 рядом с исходным файлом (Pillow, без Storage).
def _generate_previews(file_path: Path) -> None:
    suffix = file_path.suffix
    for size, data in _preview_payloads(file_path.read_bytes(), suffix):
        file_path.with_name(f"{file_path.stem}_{size}{suffix}").write_bytes(data)


# Скачивает изображение по URL и сохраняет через Storage.
async def save_image_from_url(image_url: str) -> str | None:
    try:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                image_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()

        if len(content) > MAX_IMAGE_SIZE:
            return None

        content_type = resp.headers.get("content-type", "").lower()
        if not content_type.startswith("image/"):
            return None
        if content_type not in ALLOWED_IMAGE_TYPES:
            return None

        extension = guess_extension(content_type) or ".jpg"
        file_name = f"{uuid.uuid4()}{extension}"
        return _store_product_bytes(file_name, content, content_type)
    except Exception:
        return None
