import asyncio
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from src.models.order import AvailabilityConfirmationStatus, OrderStatus  # noqa: E402
from src.repositories.session import async_session_maker  # noqa: E402
from src.services.orders.supplier_tracking import (  # noqa: E402
    initialize_supplier_tracking,
)
from src.utils.datetime_fmt import utc_now_naive  # noqa: E402
from tests.fixtures.supplier_tracking_demo import (  # noqa: E402
    build_full_dhl_tracking_json,
)
from tests.integration.helpers.order_admin import (  # noqa: E402
    create_telegram_user,
    pick_active_product_id,
)
from tests.integration.test_order_availability_sync import (  # noqa: E402
    _create_processing_order,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).resolve().parent / "artifacts" / "supplier-tracking"


@dataclass(frozen=True)
class VisualOrders:
    stamp: str
    buyer_id: int
    buyer_token: str
    waiting_order_id: int
    dhl_order_id: int


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# Создаёт два заказа: без CJ и с DHL carrier_events.
async def seed_visual_orders(stamp: str) -> VisualOrders:
    from src.core.security import create_access_token

    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, int(stamp[-6:]))
        await pick_active_product_id(session)
        waiting_order, _items = await _create_processing_order(
            session,
            buyer.id,
            int(stamp[-6:]),
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        waiting_order.payment_paid_at = now
        waiting_order.status = OrderStatus.ASSEMBLING
        waiting_order.supplier_order_id = f"TP-VISUAL-{stamp}-WAIT"
        initialize_supplier_tracking(waiting_order, now)

        dhl_order, _dhl_items = await _create_processing_order(
            session,
            buyer.id,
            int(stamp[-6:]) + 1,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        dhl_order.payment_paid_at = now
        dhl_order.status = OrderStatus.DELIVERY
        dhl_order.supplier_order_id = f"TP-VISUAL-{stamp}-DHL"
        dhl_order.supplier_tracking_id = "CJ687378245DE"
        dhl_order.supplier_tracking_sync_state = "active"
        dhl_tracking = build_full_dhl_tracking_json(
            purchased_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC).isoformat(),
        )
        dhl_tracking["supplier_events"] = [
            {
                "key": "pl-visual-1",
                "at": "2026-07-07T15:17:59Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ]
        dhl_tracking["carrier_label"] = "DHL"
        dhl_tracking["tracking_number"] = "CJ687378245DE"
        dhl_order.supplier_tracking_json = dhl_tracking
        dhl_order.supplier_tracking_updated_at = datetime(2026, 7, 8, 8, 0, tzinfo=None)
        await session.commit()
        return VisualOrders(
            stamp=stamp,
            buyer_id=buyer.id,
            buyer_token=create_access_token(buyer.id),
            waiting_order_id=int(waiting_order.id),
            dhl_order_id=int(dhl_order.id),
        )


def playwright_admin_login(page: Page, base: str) -> None:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    page.goto(f"{base}/internal/admin/login")
    page.fill("#username", login)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/internal/admin/login" not in url, timeout=10000)


def storefront_auth(page: Page, base: str, token: str) -> None:
    page.goto(base)
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "sameSite": "Lax",
            }
        ]
    )
    page.evaluate("(token) => localStorage.setItem('access_token', token)", token)


# Раскрывает карточку «Доставка и завершение» на странице заказа.
def open_delivery_card(page: Page) -> None:
    delivery = page.locator("details.orders-detail-action--delivery").first
    if not delivery.evaluate("el => el.open"):
        delivery.locator("summary.ac-card__head").click()
    page.wait_for_timeout(200)


def capture_admin_order(
    page: Page,
    base: str,
    order_id: int,
    prefix: str,
    shots: list[dict[str, str]],
) -> None:
    page.goto(f"{base}/internal/admin/orders?id={order_id}")
    page.wait_for_selector(".order-journey", timeout=15000)
    journey_path = ARTIFACTS / f"{prefix}-admin-journey.png"
    page.locator(".order-journey").screenshot(path=str(journey_path))
    shots.append(
        {
            "file": journey_path.name,
            "zone": "Админка → верх страницы заказа",
            "what": "section.order-journey — только 5 бизнес-этапов SHOPSTORE",
        }
    )

    shipment = page.locator(
        "details.orders-detail-action--delivery.order-shipment-card"
    )
    if shipment.count():
        shipment_path = ARTIFACTS / f"{prefix}-admin-shipment-card.png"
        shipment.screenshot(path=str(shipment_path))
        shots.append(
            {
                "file": shipment_path.name,
                "zone": "Админка → карточка «Доставка» (правая колонка)",
                "what": (
                    "orders-detail-action--delivery: summary, кнопки, "
                    "вертикальная история DHL"
                ),
            }
        )
        events = page.locator(".shipment-events .shipment-event")
        if events.count():
            events_path = ARTIFACTS / f"{prefix}-admin-shipment-events.png"
            page.locator(".shipment-events").screenshot(path=str(events_path))
            shots.append(
                {
                    "file": events_path.name,
                    "zone": "Админка → история движения DHL",
                    "what": "Вертикальный timeline carrier_events (новые сверху)",
                }
            )

    open_delivery_card(page)
    block_path = ARTIFACTS / f"{prefix}-admin-delivery-card.png"
    page.locator("details.orders-detail-action--delivery").screenshot(
        path=str(block_path)
    )
    shots.append(
        {
            "file": block_path.name,
            "zone": "Админка → карточка «Доставка и завершение» (data-step=6)",
            "what": "Автопроверка / DHL, блок ParcelLab + DHL raw, ручные этапы",
        }
    )


def capture_lk_api_preview(
    base: str,
    order_id: int,
    token: str,
    prefix: str,
    shots: list[dict[str, str]],
) -> None:
    response = httpx.get(
        f"{base}/orders/{order_id}/tracking",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    events = data.get("events") or []
    rows = "\n".join(
        f"<li><strong>{item.get('title')}</strong>"
        f"<div>{item.get('description') or ''}</div>"
        f"<small>{item.get('at') or ''}</small></li>"
        for item in events
    )
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8" />
<title>LK tracking #{order_id}</title>
<style>body{{font-family:system-ui;margin:24px}}ol{{padding-left:18px}}</style></head>
<body>
<h1>ЛК: /api/orders/{order_id}/tracking</h1>
<p>Сейчас: <strong>{data.get("current_status") or "—"}</strong></p>
<p>{"Отслеживание: DHL" if data.get("carrier_source") == "dhl" else ""}</p>
<ol>{rows}</ol>
</body></html>"""
    path = ARTIFACTS / f"{prefix}-lk-api-preview.html"
    path.write_text(html, encoding="utf-8")
    shots.append(
        {
            "file": path.name,
            "zone": (
                f"ЛК клиента → GET /orders/{order_id}/tracking "
                "(то же, что OrderTrackingDialog)"
            ),
            "what": "Публичная проекция store + DHL; открой HTML в браузере",
        }
    )


def capture_lk_dialog(
    page: Page,
    base: str,
    order_id: int,
    token: str,
    prefix: str,
    shots: list[dict[str, str]],
) -> None:
    storefront_auth(page, base, token)
    page.goto(f"{base}/account?tab=orders")
    page.wait_for_selector(f'span:text-is("#{order_id}")', timeout=15000)
    page.locator(f'button:has(span:text-is("#{order_id}"))').first.click()
    page.wait_for_timeout(500)
    track = page.get_by_role("button", name="Отследить товар")
    track.wait_for(state="visible", timeout=10000)
    track.click()
    title = f"Движение заказа №{order_id}"
    page.wait_for_selector(f'h2:text("{title}")', timeout=10000)
    dialog_path = ARTIFACTS / f"{prefix}-lk-dialog.png"
    page.locator("div.fixed.inset-0").last.screenshot(path=str(dialog_path))
    shots.append(
        {
            "file": dialog_path.name,
            "zone": "ЛК клиента → /account?tab=orders → модалка",
            "what": (
                "React OrderTrackingDialog — store milestones + "
                "supplier_events (ParcelLab); DHL только fallback"
            ),
        }
    )


def write_index_html(
    orders: VisualOrders, base: str, shots: list[dict[str, str]]
) -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"""
        <article class="shot">
          <h3>{item["file"]}</h3>
          <p><strong>Где:</strong> {item["zone"]}</p>
          <p><strong>Что:</strong> {item["what"]}</p>
          <img src="{item["file"]}" alt="{item["file"]}" loading="lazy" />
        </article>
        """
        for item in shots
    )
    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Supplier tracking UI map</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f6f7f9; }}
    h1 {{ margin-bottom: 8px; }}
    .meta {{ color: #555; margin-bottom: 24px; }}
    .legend {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
      padding: 16px; margin-bottom: 24px; }}
  .grid {{ display: grid; gap: 20px; }}
    .shot {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
      padding: 16px; }}
    .shot img {{ width: 100%; height: auto; border: 1px solid #eee;
      border-radius: 8px; margin-top: 12px; }}
    code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Карта UI: supplier tracking</h1>
  <div class="meta">Сгенерировано {orders.stamp}. API: <code>{base}</code></div>
  <div class="legend">
    <p><strong>Заказ A (ждём CJ):</strong> #{orders.waiting_order_id} —
      assembling, TP без трека</p>
    <p><strong>Заказ B (DHL):</strong> #{orders.dhl_order_id} —
      delivery, CJ + carrier_events</p>
    <p>Открой скриншоты ниже — подпись объясняет DOM-зону.</p>
  </div>
  <div class="grid">{rows}</div>
</body>
</html>
"""
    index_path = ARTIFACTS / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path


def run_supplier_tracking_visual() -> list[str]:
    load_env()
    base = os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
    stamp = str(int(time.time()))
    shots: list[dict[str, str]] = []
    failed: list[str] = []

    try:
        orders = asyncio.run(seed_visual_orders(stamp))
    except Exception as exc:
        print(f"FAIL seed_visual_orders: {exc}")
        return ["seed_visual_orders"]

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("VISUAL_HEADLESS", "1") != "0"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})

            playwright_admin_login(page, base)
            try:
                capture_admin_order(
                    page, base, orders.waiting_order_id, "01-waiting", shots
                )
            except Exception as exc:
                print(f"WARN admin waiting: {exc}")
                failed.append("admin_waiting")
            try:
                capture_admin_order(page, base, orders.dhl_order_id, "02-dhl", shots)
            except Exception as exc:
                print(f"WARN admin dhl: {exc}")
                failed.append("admin_dhl")

            try:
                capture_lk_api_preview(
                    base,
                    orders.waiting_order_id,
                    orders.buyer_token,
                    "03-waiting",
                    shots,
                )
                capture_lk_api_preview(
                    base, orders.dhl_order_id, orders.buyer_token, "04-dhl", shots
                )
            except Exception as exc:
                print(f"WARN lk api preview: {exc}")
                failed.append("lk_api")

            try:
                capture_lk_dialog(
                    page,
                    base,
                    orders.waiting_order_id,
                    orders.buyer_token,
                    "03-waiting-ui",
                    shots,
                )
            except Exception as exc:
                print(f"WARN lk waiting ui: {exc}")
                failed.append("lk_waiting")
            try:
                capture_lk_dialog(
                    page,
                    base,
                    orders.dhl_order_id,
                    orders.buyer_token,
                    "04-dhl-ui",
                    shots,
                )
            except Exception as exc:
                print(f"WARN lk dhl: {exc}")
                failed.append("lk_dhl")
            browser.close()
    except Exception as exc:
        print(f"FAIL playwright: {exc}")
        failed.append("playwright")

    if shots:
        index_path = write_index_html(orders, base, shots)
        print(f"OK artifacts: {index_path}")
        print(f"  waiting order #{orders.waiting_order_id}")
        print(f"  dhl order #{orders.dhl_order_id}")
        print("  open index.html in browser")

    return failed


@pytest.mark.e2e
def test_supplier_tracking_visual() -> None:
    failed = run_supplier_tracking_visual()
    assert (
        ARTIFACTS / "index.html"
    ).exists(), "нет index.html — проверь make up и .env"
    blocking = [
        name
        for name in failed
        if name.startswith("admin_") or name == "seed_visual_orders"
    ]
    assert not blocking, f"failed: {', '.join(blocking)}"
    if failed:
        print(f"WARN optional failed: {', '.join(failed)}")


if __name__ == "__main__":
    raise SystemExit(0 if not run_supplier_tracking_visual() else 1)
