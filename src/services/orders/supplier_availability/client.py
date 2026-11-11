import json
import logging
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from stealth_requests import AsyncStealthSession

from src.integrations.supplier_demo.http_validation import (
    http_challenge_reason,
    reject_http_html_reason,
)
from src.scraper.infrastructure.session_paths import (
    resolve_storage_state_path,
    storage_state_file_status,
)
from src.scraper.parsers.pdp_support import extract_first
from src.scraper.parsers.product_pdp import (
    extract_balanced_div,
    merge_product_data_variant_skus,
    parse_product_json,
    parse_product_page_details,
    parse_product_page_prices,
    product_json_url,
)
from src.scraper.sources.graphql_catalog import apply_variant_stock

logger = logging.getLogger(__name__)


# Снимок варианта поставщика.
@dataclass(frozen=True)
class SupplierVariantSnapshot:
    variant_id: str | None
    sku: str | None
    available: bool | None
    inventory_quantity: int | None
    current_price_eur: str | None
    member_price_eur: str | None


# Результат проверки одного варианта поставщика.
@dataclass(frozen=True)
class SupplierVariantCheckResult:
    product_url: str
    requested_variant_id: str | None
    requested_sku: str | None
    found: bool
    snapshot: SupplierVariantSnapshot | None
    session_valid: bool
    html_validation: str | None
    http_status: int | None
    latency_ms: int
    challenge: str | None
    error: str | None


# Статус cookies Playwright storage_state.
@dataclass(frozen=True)
class StorageStateStatus:
    ok: bool
    reason: str | None = None


# Проверить storage_state перед запросами к поставщику.
def validate_storage_state(
    explicit_path: str | Path | None = None,
) -> StorageStateStatus:
    path = resolve_storage_state_path(explicit_path)
    if path is None:
        return StorageStateStatus(ok=False, reason="storage_state_missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return StorageStateStatus(ok=False, reason="storage_state_corrupt")
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return StorageStateStatus(ok=False, reason="storage_state_corrupt")
    status = storage_state_file_status(explicit_path)
    if status.get("status") != "ok":
        return StorageStateStatus(ok=False, reason="storage_state_stale")
    return StorageStateStatus(ok=True)


# Загружает cookies Playwright storage_state без логирования значений.
def load_storage_state_cookies(
    explicit_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = resolve_storage_state_path(explicit_path)
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    cookies = data.get("cookies") or []
    if not isinstance(cookies, list):
        return []
    return [item for item in cookies if isinstance(item, dict)]


# Подмешивает cookies в AsyncStealthSession.
def apply_storage_state_cookies(
    session: AsyncStealthSession,
    cookies: list[dict[str, Any]],
) -> int:
    applied = 0
    for item in cookies:
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        if not name:
            continue
        domain = str(item.get("domain") or "")
        path = str(item.get("path") or "/")
        secure = bool(item.get("secure"))
        session.cookies.set(name, value, domain=domain, path=path, secure=secure)
        applied += 1
    return applied


# Нормализовать ID варианта.
def _normalize_variant_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# Преобразовать цену Shopify в EUR.
def _shopify_price_to_eur(raw: object) -> str | None:
    if raw is None:
        return None
    try:
        cents = int(str(raw))
    except (TypeError, ValueError):
        return None
    return f"{cents / 100:.2f}"


# Парсинг цены для проверки админом.
def parse_member_price_eur(html: str) -> str | None:
    price_open = re.search(
        r'<div[^>]*id="price-[^"]*"[^>]*class="[^"]*tp-price__wrapper[^"]*"[^>]*>',
        html,
        re.S | re.I,
    )
    segment = html
    if price_open:
        segment = extract_balanced_div(html, price_open.start()) or html
    raw = extract_first(
        r'tp-price-item__member-price[^>]*data-tp-gtm-final-price="([^"]+)"',
        segment,
    )
    if not raw:
        raw = extract_first(
            r'class="[^"]*tp-price-item__member-price[^"]*"[^>]*>\s*([^<]+)',
            segment,
        )
    if not raw:
        return None
    cleaned = raw.replace("€", "").replace("\xa0", "").strip()
    cleaned = cleaned.replace(",", ".")
    return cleaned or None


# Найти вариант в product.json.
def _find_variant(
    product_json: dict[str, Any],
    variant_id: str | None,
    sku: str | None,
) -> dict[str, Any] | None:
    variants = product_json.get("variants")
    if not isinstance(variants, list):
        return None
    normalized_id = _normalize_variant_id(variant_id)
    normalized_sku = (sku or "").strip() or None
    if normalized_id:
        for item in variants:
            if not isinstance(item, dict):
                continue
            item_id = _normalize_variant_id(item.get("id"))
            if item_id == normalized_id:
                return item
        return None
    if normalized_sku:
        for item in variants:
            if not isinstance(item, dict):
                continue
            item_sku = str(item.get("sku") or "").strip() or None
            if item_sku == normalized_sku:
                return item
    return None


# Получить словарь варианта из product.json и HTML.
def _variant_dict_from_sources(
    product_json: dict[str, Any],
    html: str,
    variant_id: str | None,
    sku: str | None,
) -> dict[str, Any] | None:
    base = _find_variant(
        product_json,
        variant_id=variant_id,
        sku=sku if not variant_id else None,
    )
    if base is None:
        return None

    details = parse_product_page_details(html)
    product_data = merge_product_data_variant_skus(
        details.get("product_data") or {},
        product_json,
    )
    seed_variant: dict[str, Any] = {
        "id": base.get("id"),
        "sku": base.get("sku"),
        "inventory_quantity": base.get("inventory_quantity", 0),
        "available": base.get("available", False),
    }
    if base.get("price") is not None:
        seed_variant["price"] = base.get("price")
    product = {"product_data": {"variants": [seed_variant]}}
    if apply_variant_stock(
        product,
        product_data,
        details.get("selected_variant") or {},
    ):
        merged = product["product_data"]["variants"][0]
        if isinstance(merged, dict):
            return merged
    return base


# Построить снимок варианта поставщика.
def build_variant_snapshot(
    variant: dict[str, Any],
    html_prices: dict[str, str] | None = None,
    member_price_eur: str | None = None,
) -> SupplierVariantSnapshot:
    html_prices = html_prices or {}
    shopify_price = _shopify_price_to_eur(variant.get("price"))
    current = html_prices.get("sale_price") or shopify_price
    return SupplierVariantSnapshot(
        variant_id=_normalize_variant_id(variant.get("id")),
        sku=str(variant.get("sku") or "").strip() or None,
        available=bool(variant.get("available")) if "available" in variant else None,
        inventory_quantity=(
            int(variant["inventory_quantity"])
            if variant.get("inventory_quantity") is not None
            else None
        ),
        current_price_eur=current,
        member_price_eur=member_price_eur,
    )


# Парсит offline product.json + HTML без сети.
def parse_supplier_variant_offline(
    product_url: str,
    product_json_text: str,
    html: str,
    variant_id: str | None = None,
    sku: str | None = None,
    http_status: int = 200,
) -> SupplierVariantCheckResult:
    product_json = parse_product_json(product_json_text)
    variant = _variant_dict_from_sources(
        product_json,
        html,
        variant_id=variant_id,
        sku=sku,
    )
    html_validation = reject_http_html_reason(html, http_status)
    challenge = http_challenge_reason(
        html,
        http_status,
        reject_reason=html_validation,
    )
    member_price = parse_member_price_eur(html)
    html_prices = parse_product_page_prices(html)
    snapshot = None
    if variant is not None:
        snapshot = build_variant_snapshot(
            variant,
            html_prices=html_prices,
            member_price_eur=member_price,
        )
    return SupplierVariantCheckResult(
        product_url=product_url,
        requested_variant_id=variant_id,
        requested_sku=sku,
        found=variant is not None,
        snapshot=snapshot,
        session_valid=html_validation != "login" and challenge != "login",
        html_validation=html_validation,
        http_status=http_status,
        latency_ms=0,
        challenge=challenge,
        error=None,
    )


# HTTP-запрос одного точного варианта (concurrency 1 снаружи).
async def fetch_supplier_variant(
    product_url: str,
    variant_id: str | None = None,
    sku: str | None = None,
    storage_state_path: str | Path | None = None,
    session: AsyncStealthSession | None = None,
    use_storage_state: bool = True,
) -> SupplierVariantCheckResult:
    if not variant_id and not sku:
        raise ValueError("Нужен variant_id или sku")
    cookies = (
        load_storage_state_cookies(storage_state_path) if use_storage_state else []
    )
    started = time.monotonic()
    owns_session = session is None
    if owns_session:
        session = AsyncStealthSession()
    assert session is not None
    try:
        if cookies:
            apply_storage_state_cookies(session, cookies)
        json_url = product_json_url(product_url)
        json_response = await session.get(json_url, timeout=30)
        json_status = json_response.status_code
        product_json_text = json_response.text or ""
        product_json = parse_product_json(product_json_text)
        if json_status >= HTTPStatus.BAD_REQUEST and not product_json:
            latency_ms = int((time.monotonic() - started) * 1000)
            challenge = http_challenge_reason(
                product_json_text,
                json_status,
                reject_reason=f"status={json_status}",
            )
            return SupplierVariantCheckResult(
                product_url=product_url,
                requested_variant_id=variant_id,
                requested_sku=sku,
                found=False,
                snapshot=None,
                session_valid=challenge != "login",
                html_validation=f"status={json_status}",
                http_status=json_status,
                latency_ms=latency_ms,
                challenge=challenge,
                error="product_json_unavailable",
            )

        html_response = await session.get(product_url, timeout=30)
        html = html_response.text or ""
        html_status = html_response.status_code
        variant = _variant_dict_from_sources(
            product_json,
            html,
            variant_id=variant_id,
            sku=sku,
        )
        html_validation = reject_http_html_reason(html, html_status)
        challenge = http_challenge_reason(
            html,
            html_status,
            reject_reason=html_validation,
        )
        member_price = parse_member_price_eur(html)
        html_prices = parse_product_page_prices(html)
        snapshot = None
        if variant is not None:
            snapshot = build_variant_snapshot(
                variant,
                html_prices=html_prices,
                member_price_eur=member_price,
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        return SupplierVariantCheckResult(
            product_url=product_url,
            requested_variant_id=variant_id,
            requested_sku=sku,
            found=variant is not None,
            snapshot=snapshot,
            session_valid=html_validation != "login" and challenge != "login",
            html_validation=html_validation,
            http_status=html_status,
            latency_ms=latency_ms,
            challenge=challenge,
            error=None,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "Проверка наличия у поставщика failed для %s: %s",
            product_url,
            type(exc).__name__,
        )
        return SupplierVariantCheckResult(
            product_url=product_url,
            requested_variant_id=variant_id,
            requested_sku=sku,
            found=False,
            snapshot=None,
            session_valid=False,
            html_validation=None,
            http_status=None,
            latency_ms=latency_ms,
            challenge=None,
            error=type(exc).__name__,
        )
    finally:
        if owns_session:
            await session.close()
