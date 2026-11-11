import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from stealth_requests import AsyncStealthSession

from src.core.config import settings
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderItem,
    OrderStatus,
    order_item_captured_variant_label,
)
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.services.orders.supplier_availability.client import (
    StorageStateStatus,
    SupplierVariantCheckResult,
    SupplierVariantSnapshot,
    apply_storage_state_cookies,
    fetch_supplier_variant,
    load_storage_state_cookies,
    validate_storage_state,
)
from src.utils.datetime_fmt import utc_now_naive

logger = logging.getLogger(__name__)

VERDICT_READY = "ready_for_admin"
VERDICT_MANUAL = "manual_review"
VERDICT_FAILED = "failed"
SUPPLIER_CHECK_METHOD_VERSION = "stealth_http_pdp_v1"


@dataclass(frozen=True)
class _ItemCheckTarget:
    order_item_id: int
    product_id: int
    product_title: str | None
    variant_label: str | None
    product_url: str | None
    variant_id: str | None
    sku: str | None
    quantity: int
    captured_price_eur: Decimal | None


# Хэш состава заказа.
def composition_hash(items: list[OrderItem]) -> str:
    payload = [
        {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "variant_id": item.variant_id,
            "quantity": item.quantity,
            "variant_external_id_captured": item.variant_external_id_captured,
            "variant_sku_captured": item.variant_sku_captured,
        }
        for item in sorted(items, key=lambda row: row.id)
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Преобразовать цену в EUR.
def _decimal_eur(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed


# Проверить, достаточно ли количества варианта.
def quantity_sufficient(
    required: int,
    available: bool | None,
    inventory_quantity: int | None,
) -> bool | None:
    if available is False:
        return False
    if inventory_quantity is not None:
        return inventory_quantity >= required
    if required == 1 and available is True:
        return True
    return None


# EUR для сравнения с captured: catalog node (current), без public fallback.
def _verdict_supplier_price_eur(
    snapshot: SupplierVariantSnapshot | None,
    html_validation: str | None,
) -> Decimal | None:
    if snapshot is None:
        return None
    if html_validation == "no_member_price":
        return None
    current = _decimal_eur(snapshot.current_price_eur)
    if current is not None:
        return current
    return _decimal_eur(snapshot.member_price_eur)


# Вычислить вердикт для одного элемента заказа.
def compute_item_verdict(
    required_quantity: int,
    check: SupplierVariantCheckResult,
    captured_price_eur: Decimal | None,
) -> dict[str, Any]:
    snapshot = check.snapshot
    found = check.found and snapshot is not None
    supplier_price = _verdict_supplier_price_eur(snapshot, check.html_validation)
    eur_delta = None
    if captured_price_eur is not None and supplier_price is not None:
        eur_delta = str(abs(supplier_price - captured_price_eur))
    qty_ok = None
    if snapshot is not None:
        qty_ok = quantity_sufficient(
            required_quantity,
            available=snapshot.available,
            inventory_quantity=snapshot.inventory_quantity,
        )
    needs_manual = bool(
        check.challenge
        or check.error
        or check.html_validation
        or not check.session_valid
        or not found
        or qty_ok is False
        or qty_ok is None
    )
    return {
        "found": found,
        "quantity_sufficient": qty_ok,
        "needs_manual_review": needs_manual,
        "captured_price_eur": str(captured_price_eur) if captured_price_eur else None,
        "supplier_price_eur": str(supplier_price) if supplier_price else None,
        "eur_delta_abs": eur_delta,
        "check": check,
    }


# Вычислить вердикт для заказа.
def compute_order_verdict(item_rows: list[dict[str, Any]]) -> str:
    if not item_rows:
        return VERDICT_FAILED
    checks = [row["check"] for row in item_rows]
    if checks and all(
        check.error and not row["found"] for row, check in zip(item_rows, checks)
    ):
        return VERDICT_FAILED
    if any(row["needs_manual_review"] for row in item_rows):
        return VERDICT_MANUAL
    return VERDICT_READY


# Проверить, не истекло ли время снипшота.
def snapshot_is_fresh(
    snapshot: dict[str, Any] | None,
    now: datetime | None = None,
) -> bool:
    if not isinstance(snapshot, dict):
        return False
    expires_raw = snapshot.get("expires_at")
    if not isinstance(expires_raw, str):
        return False
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    current = now or utc_now_naive()
    return current <= expires_at


# Проверить, соответствует ли снимок составу заказа.
def snapshot_matches_composition(
    snapshot: dict[str, Any] | None,
    composition: str,
) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return str(snapshot.get("composition_hash") or "") == composition


# Проверить, не устарел ли снимок проверки поставщика или не изменился ли состав заказа.
def validate_supplier_snapshot_for_admin_action(
    order: Order,
    items: list[OrderItem],
) -> None:
    snapshot = order.supplier_availability_json
    if not isinstance(snapshot, dict) or not snapshot.get("checked_at"):
        return
    composition = composition_hash(list(items))
    if not snapshot_is_fresh(snapshot):
        raise ValueError(
            "Снимок проверки поставщика устарел — запустите проверку повторно"
        )
    if not snapshot_matches_composition(snapshot, composition):
        raise ValueError(
            "Состав заказа изменился после проверки поставщика — "
            "запустите проверку повторно"
        )


# Построить payload снипшота проверки поставщика.
def build_snapshot_payload(
    order_id: int,
    composition: str,
    verdict: str,
    session_valid: bool,
    items: list[dict[str, Any]],
    checked_at: datetime,
) -> dict[str, Any]:
    ttl_minutes = settings.SUPPLIER_AVAILABILITY_SNAPSHOT_TTL_MINUTES
    expires_at = checked_at + timedelta(minutes=ttl_minutes)
    serialized_items: list[dict[str, Any]] = []
    for row in items:
        check: SupplierVariantCheckResult = row["check"]
        snap = check.snapshot
        serialized_items.append(
            {
                "order_item_id": row["order_item_id"],
                "product_id": row["product_id"],
                "product_title": row.get("product_title"),
                "variant_label": row.get("variant_label"),
                "product_url": row["product_url"],
                "required_quantity": row["required_quantity"],
                "captured_variant_id": row["captured_variant_id"],
                "captured_sku": row["captured_sku"],
                "found_variant_id": snap.variant_id if snap else None,
                "found_sku": snap.sku if snap else None,
                "available": snap.available if snap else None,
                "inventory_quantity": snap.inventory_quantity if snap else None,
                "quantity_sufficient": row["quantity_sufficient"],
                "captured_price_eur": row["captured_price_eur"],
                "supplier_price_eur": row["supplier_price_eur"],
                "member_price_eur": snap.member_price_eur if snap else None,
                "eur_delta_abs": row["eur_delta_abs"],
                "html_validation": check.html_validation,
                "challenge": check.challenge,
                "error": check.error,
                "latency_ms": check.latency_ms,
                "found": row["found"],
            }
        )
    return {
        "order_id": order_id,
        "method_version": SUPPLIER_CHECK_METHOD_VERSION,
        "checked_at": checked_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "composition_hash": composition,
        "verdict": verdict,
        "session_valid": session_valid,
        "items": serialized_items,
    }


class SupplierAvailabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)
        self.product_crud = CrudProduct(session=session, model=Product)

    # Проверить наличие у поставщика.
    async def check_order(self, order_id: int) -> dict[str, Any]:
        if not settings.SUPPLIER_AVAILABILITY_ENABLED:
            return {"status": "disabled", "order_id": order_id}

        order = await self.order_crud.get_by_id_for_update(order_id)
        if order is None:
            raise ValueError("Заказ не найден")

        availability = str(order.availability_confirmation_status or "").lower()
        status = str(order.status or "").lower()
        if availability != AvailabilityConfirmationStatus.PENDING:
            await self.session.commit()
            return {"status": "skipped", "reason": "availability_not_pending"}
        if status not in {OrderStatus.CREATED, OrderStatus.PROCESSING}:
            await self.session.commit()
            return {"status": "skipped", "reason": "order_status"}

        items = await self.order_crud.get_order_items(order_id)
        if not items:
            await self.session.commit()
            return {"status": "skipped", "reason": "no_items"}

        composition = composition_hash(list(items))
        existing = order.supplier_availability_json
        if (
            isinstance(existing, dict)
            and snapshot_is_fresh(existing)
            and snapshot_matches_composition(existing, composition)
        ):
            await self.session.commit()
            return {
                "status": "cached",
                "order_id": order_id,
                "verdict": existing.get("verdict"),
                "composition_hash": composition,
            }

        targets = await self._collect_item_targets(items)
        await self.session.commit()

        item_rows = await self._fetch_item_checks(targets)

        order = await self.order_crud.get_by_id_for_update(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        availability = str(order.availability_confirmation_status or "").lower()
        status = str(order.status or "").lower()
        if availability != AvailabilityConfirmationStatus.PENDING:
            await self.session.commit()
            return {"status": "skipped", "reason": "availability_not_pending"}
        if status not in {OrderStatus.CREATED, OrderStatus.PROCESSING}:
            await self.session.commit()
            return {"status": "skipped", "reason": "order_status"}

        current_items = await self.order_crud.get_order_items(order_id)
        current_composition = composition_hash(list(current_items))
        if current_composition != composition:
            await self.session.commit()
            return {"status": "skipped", "reason": "composition_changed"}

        verdict = compute_order_verdict(item_rows)
        session_valid = all(
            row["check"].session_valid for row in item_rows if row.get("check")
        )
        checked_at = utc_now_naive()
        payload = build_snapshot_payload(
            order_id=order_id,
            composition=current_composition,
            verdict=verdict,
            session_valid=session_valid,
            items=item_rows,
            checked_at=checked_at,
        )
        order.supplier_availability_json = payload
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="supplier_availability_checked",
            event_message=self._event_message_for_verdict(verdict),
            created_by="system",
            payload_json={
                "verdict": verdict,
                "composition_hash": current_composition,
                "method_version": SUPPLIER_CHECK_METHOD_VERSION,
            },
        )
        await self.session.commit()

        return {
            "status": "ok",
            "order_id": order_id,
            "verdict": verdict,
            "composition_hash": current_composition,
        }

    # Собрать цели для проверки одного элемента заказа.
    async def _collect_item_targets(
        self,
        items: list[OrderItem],
    ) -> list[_ItemCheckTarget]:
        rows: list[_ItemCheckTarget] = []
        for item in items:
            product = await self.product_crud.get_by_id(item.product_id)
            product_url = (
                str(product.product_url).strip()
                if product is not None and product.product_url
                else None
            )
            variant_id = (
                str(item.variant_external_id_captured).strip()
                if item.variant_external_id_captured
                else None
            )
            sku = (
                str(item.variant_sku_captured).strip()
                if item.variant_sku_captured
                else None
            )
            captured_price = item.supplier_price_eur_captured
            variant_label = order_item_captured_variant_label(item)
            rows.append(
                _ItemCheckTarget(
                    order_item_id=item.id,
                    product_id=item.product_id,
                    product_title=(
                        str(item.product_title_captured).strip()
                        if item.product_title_captured
                        else None
                    ),
                    variant_label=variant_label,
                    product_url=product_url,
                    variant_id=variant_id,
                    sku=sku,
                    quantity=int(item.quantity),
                    captured_price_eur=(
                        Decimal(str(captured_price))
                        if captured_price is not None
                        else None
                    ),
                )
            )
        return rows

    # Проверить наличие у поставщика для одного элемента заказа.
    async def _fetch_item_checks(
        self,
        targets: list[_ItemCheckTarget],
    ) -> list[dict[str, Any]]:
        if settings.SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE:
            storage_status = validate_storage_state()
            if not storage_status.ok:
                return self._manual_rows_for_targets(targets, storage_status)

        retries = max(1, settings.SUPPLIER_AVAILABILITY_MAX_RETRIES)
        pause_seconds = float(settings.SUPPLIER_AVAILABILITY_ITEM_PAUSE_SECONDS)
        retry_pause_seconds = float(settings.SUPPLIER_AVAILABILITY_RETRY_PAUSE_SECONDS)
        rows: list[dict[str, Any]] = []
        cookies = (
            load_storage_state_cookies()
            if settings.SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE
            else []
        )
        async with AsyncStealthSession() as http_session:
            if cookies:
                apply_storage_state_cookies(http_session, cookies)
            for index, target in enumerate(targets):
                if index > 0 and pause_seconds > 0:
                    await asyncio.sleep(pause_seconds)
                check = await self._fetch_single_item(
                    target,
                    http_session=http_session,
                    retries=retries,
                    retry_pause_seconds=retry_pause_seconds,
                )
                verdict_row = compute_item_verdict(
                    required_quantity=target.quantity,
                    check=check,
                    captured_price_eur=target.captured_price_eur,
                )
                rows.append(
                    {
                        "order_item_id": target.order_item_id,
                        "product_id": target.product_id,
                        "product_title": target.product_title,
                        "variant_label": target.variant_label,
                        "product_url": target.product_url,
                        "required_quantity": target.quantity,
                        "captured_variant_id": target.variant_id,
                        "captured_sku": target.sku,
                        **verdict_row,
                    }
                )
        return rows

    # Собрать строки для ручной проверки одного элемента заказа.
    def _manual_rows_for_targets(
        self,
        targets: list[_ItemCheckTarget],
        storage_status: StorageStateStatus,
    ) -> list[dict[str, Any]]:
        reason = storage_status.reason or "storage_state_unavailable"
        rows: list[dict[str, Any]] = []
        for target in targets:
            check = SupplierVariantCheckResult(
                product_url=target.product_url or "",
                requested_variant_id=target.variant_id,
                requested_sku=target.sku,
                found=False,
                snapshot=None,
                session_valid=False,
                html_validation=reason,
                http_status=None,
                latency_ms=0,
                challenge=None,
                error=None,
            )
            verdict_row = compute_item_verdict(
                required_quantity=target.quantity,
                check=check,
                captured_price_eur=target.captured_price_eur,
            )
            rows.append(
                {
                    "order_item_id": target.order_item_id,
                    "product_id": target.product_id,
                    "product_title": target.product_title,
                    "variant_label": target.variant_label,
                    "product_url": target.product_url,
                    "required_quantity": target.quantity,
                    "captured_variant_id": target.variant_id,
                    "captured_sku": target.sku,
                    **verdict_row,
                }
            )
        return rows

    # Проверить наличие у поставщика для одного элемента заказа.
    @staticmethod
    async def _fetch_single_item(
        target: _ItemCheckTarget,
        http_session: AsyncStealthSession,
        retries: int,
        retry_pause_seconds: float,
    ) -> SupplierVariantCheckResult:
        if target.product_url and target.variant_id:
            check = SupplierVariantCheckResult(
                product_url=target.product_url,
                requested_variant_id=target.variant_id,
                requested_sku=target.sku,
                found=False,
                snapshot=None,
                session_valid=False,
                html_validation=None,
                http_status=None,
                latency_ms=0,
                challenge=None,
                error="fetch_failed",
            )
            for attempt in range(retries):
                check = await fetch_supplier_variant(
                    product_url=target.product_url,
                    variant_id=target.variant_id,
                    sku=target.sku,
                    session=http_session,
                    use_storage_state=False,
                )
                if not check.error and not check.challenge:
                    break
                if attempt + 1 < retries and retry_pause_seconds > 0:
                    await asyncio.sleep(retry_pause_seconds)
            return check
        if target.product_url and target.sku:
            check = SupplierVariantCheckResult(
                product_url=target.product_url,
                requested_variant_id=None,
                requested_sku=target.sku,
                found=False,
                snapshot=None,
                session_valid=False,
                html_validation=None,
                http_status=None,
                latency_ms=0,
                challenge=None,
                error="fetch_failed",
            )
            for attempt in range(retries):
                check = await fetch_supplier_variant(
                    product_url=target.product_url,
                    sku=target.sku,
                    session=http_session,
                    use_storage_state=False,
                )
                if not check.error and not check.challenge:
                    return check
                if attempt + 1 < retries and retry_pause_seconds > 0:
                    await asyncio.sleep(retry_pause_seconds)
            return check
        return SupplierVariantCheckResult(
            product_url=target.product_url or "",
            requested_variant_id=target.variant_id,
            requested_sku=target.sku,
            found=False,
            snapshot=None,
            session_valid=False,
            html_validation="missing_product_url_or_variant",
            http_status=None,
            latency_ms=0,
            challenge=None,
            error="missing_inputs",
        )

    # Построить сообщение для события проверки поставщика.
    @staticmethod
    def _event_message_for_verdict(verdict: str) -> str:
        if verdict == VERDICT_READY:
            return "Автопроверка наличия у поставщика: готово к решению админа"
        if verdict == VERDICT_MANUAL:
            return "Автопроверка наличия у поставщика: нужна ручная проверка"
        return "Автопроверка наличия у поставщика: не удалось получить данные"
