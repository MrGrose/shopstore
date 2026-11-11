import asyncio
import os
import time
from dataclasses import dataclass
from decimal import Decimal

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from src.models.order import AvailabilityConfirmationStatus, OrderStatus  # noqa: E402
from src.repositories.session import async_session_maker  # noqa: E402
from src.utils.datetime_fmt import utc_now_naive  # noqa: E402
from tests.e2e.conftest import load_dotenv  # noqa: E402
from tests.integration.helpers.order_admin import (  # noqa: E402
    create_telegram_user,
    pick_active_product_id,
)
from tests.integration.test_order_availability_sync import (  # noqa: E402
    _create_processing_order,
)

OVERFLOW_CHECK_JS = """
() => {
  const wrap = document.querySelector('#admin-orders-table .orders-table-wrap');
  const page = document.querySelector('.orders-page');
  if (!wrap || !page) {
    return { ok: false, reason: 'missing table or page root' };
  }

  const wrapRect = wrap.getBoundingClientRect();
  const pageRect = page.getBoundingClientRect();
  if (wrapRect.right > pageRect.right + 1) {
    return {
      ok: false,
      reason: 'table card exceeds page width',
      wrapRight: wrapRect.right,
      pageRight: pageRect.right,
    };
  }

  const overflows = [];
  wrap.querySelectorAll('.orders-table__row > *').forEach((cell, index) => {
    const rect = cell.getBoundingClientRect();
    if (rect.right > wrapRect.right + 1) {
      overflows.push({
        index,
        text: (cell.textContent || '').trim().slice(0, 80),
        right: rect.right,
        wrapRight: wrapRect.right,
      });
    }
  });

  return {
    ok: overflows.length === 0,
    overflows,
    wrapWidth: wrapRect.width,
    pageWidth: pageRect.width,
  };
}
"""


@dataclass(frozen=True)
class LayoutOrdersSeed:
    search_token: str
    long_tr: str
    short_tr: str
    large_sum: str


async def seed_orders_table_layout(stamp: str) -> LayoutOrdersSeed:
    suffix = int(stamp[-6:])
    search_token = f"buyer_test_{suffix}"
    long_tr = f"TP-LAYOUT-{suffix}-EXTRA-LONG-SUPPLIER-REF"
    short_tr = f"TP-SHORT-{suffix}"
    large_sum = "123456"
    now = utc_now_naive()

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        await pick_active_product_id(session)

        paid_created, _ = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        paid_created.payment_paid_at = now
        paid_created.status = OrderStatus.CREATED
        paid_created.supplier_order_id = long_tr
        paid_created.total_amount = Decimal(large_sum)
        paid_created.items_subtotal_amount = Decimal("122956")

        short_tr_order, _ = await _create_processing_order(
            session,
            buyer.id,
            suffix + 1,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        short_tr_order.status = OrderStatus.CREATED
        short_tr_order.supplier_order_id = short_tr

        no_tr_order, _ = await _create_processing_order(
            session,
            buyer.id,
            suffix + 2,
            availability_status=AvailabilityConfirmationStatus.PENDING,
        )
        no_tr_order.status = OrderStatus.PROCESSING
        no_tr_order.total_amount = Decimal("987654")
        no_tr_order.items_subtotal_amount = Decimal("987154")

        await session.commit()

    return LayoutOrdersSeed(
        search_token=search_token,
        long_tr=long_tr,
        short_tr=short_tr,
        large_sum=large_sum,
    )


def playwright_admin_login(page: Page, base: str) -> None:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    page.goto(f"{base}/internal/admin/login")
    page.fill("#username", login)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/internal/admin/login" not in url, timeout=15000)


def assert_orders_table_cells_contained(page: Page) -> None:
    page.wait_for_selector(
        "#admin-orders-table .orders-table-wrap .orders-table__row",
        timeout=15000,
    )
    result = page.evaluate(OVERFLOW_CHECK_JS)
    assert result.get("ok"), f"orders table overflow: {result}"


def run_orders_table_layout_check(base: str) -> None:
    load_dotenv()
    stamp = str(int(time.time()))
    seed = asyncio.run(seed_orders_table_layout(stamp))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1180, "height": 900})
        try:
            playwright_admin_login(page, base)
            page.goto(f"{base}/internal/admin/orders?q={seed.search_token}")
            page.wait_for_selector("#admin-orders-filters", timeout=15000)
            page.wait_for_selector(
                "#admin-orders-table .orders-table-wrap .orders-table__row",
                timeout=15000,
            )
            assert_orders_table_cells_contained(page)

            tr_cells = page.locator(".orders-table__tr")
            assert (
                tr_cells.filter(has_text=seed.long_tr).count() >= 1
            ), f"TR column missing long value {seed.long_tr!r}"
            assert (
                tr_cells.filter(has_text=seed.short_tr).count() >= 1
            ), f"TR column missing short value {seed.short_tr!r}"
            assert (
                tr_cells.filter(has_text="—").count() >= 1
            ), "TR column missing empty placeholder"

            sum_cells = page.locator(".orders-table__sum")
            assert (
                sum_cells.filter(has_text=seed.large_sum).count() >= 1
            ), f"6-digit sum {seed.large_sum!r} not rendered"
            assert (
                sum_cells.filter(has_text="987654").count() >= 1
            ), "second 6-digit sum 987654 not rendered"
        finally:
            browser.close()


@pytest.mark.e2e
def test_admin_orders_table_cells_do_not_overflow_page(e2e_base_url: str) -> None:
    run_orders_table_layout_check(e2e_base_url)


if __name__ == "__main__":
    load_dotenv()
    base = os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
    run_orders_table_layout_check(base)
    print("OK admin orders table layout")
