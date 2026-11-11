from pathlib import Path

from fastapi import HTTPException, status
from fastapi.responses import FileResponse, Response

from src.core.config import settings

# Пути витрины, которые отдаём через React SPA (/internal/admin — Jinja).
STOREFRONT_SPA_ROUTE_PREFIXES: tuple[str, ...] = (
    "/",
    "/app",
    "/catalog",
    "/catalog/",
    "/cart",
    "/orders",
    "/account",
    "/checkout",
    "/login",
    "/support",
    "/privacy",
    "/terms",
    "/consent",
    "/returns",
)


def storefront_dist_dir() -> Path:
    return Path(settings.STOREFRONT_DIST_DIR)


def spa_index_path() -> Path | None:
    index = storefront_dist_dir() / "index.html"
    return index if index.is_file() else None


# True, если React-витрина собрана (frontend/dist/index.html).
def is_storefront_ready() -> bool:
    return spa_index_path() is not None


# Текст ошибки, если dist не собран.
def storefront_readiness_error() -> str | None:
    if is_storefront_ready():
        return None
    return "storefront not built"


# None в prod при готовой витрине; иначе текст ошибки для /ready.
def ready_storefront_check(is_dev: bool) -> str | None:
    if is_dev:
        return None
    return storefront_readiness_error()


def spa_assets_dir() -> Path | None:
    assets = storefront_dist_dir() / "assets"
    return assets if assets.is_dir() else None


def spa_public_dirs() -> list[tuple[str, Path]]:
    """Статика из frontend/public → dist (hero/, …), кроме assets/."""
    dist = storefront_dist_dir()
    if not dist.is_dir():
        return []
    mounts: list[tuple[str, Path]] = []
    for child in sorted(dist.iterdir()):
        if child.is_dir() and child.name != "assets":
            mounts.append((f"/{child.name}", child))
    return mounts


# Отдаёт index.html React-витрины или 503, если dist не собран.
def storefront_spa_response() -> Response:
    index = spa_index_path()
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Unavailable",
        )
    return FileResponse(index, media_type="text/html")


def react_storefront_index() -> Response:
    """Совместимость: всегда React SPA."""
    return storefront_spa_response()
