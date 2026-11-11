"""Regression: admin pages expose canonical buttons, checkboxes and selects.

Page-by-page contracts for future UI unification. Dashboard and parsing are excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import pytest

from src.main import app
from src.repositories.session import async_session_maker
from tests.integration.helpers.order_admin import create_admin_access_token

EXCLUDED_ADMIN_PAGES = ("dashboard", "parsing")


@dataclass(frozen=True)
class AdminPageContract:
    page_id: str
    path: str
    markers: tuple[str, ...]
    partial_path: str | None = None
    partial_markers: tuple[str, ...] = ()
    partial_any_of: tuple[str, ...] = ()


def _missing_markers(html: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker not in html]


def _assert_markers(html: str, markers: tuple[str, ...], context: str) -> None:
    missing = _missing_markers(html, markers)
    assert not missing, f"{context}: missing {missing}"


def _assert_any_marker(html: str, markers: tuple[str, ...], context: str) -> None:
    if any(marker in html for marker in markers):
        return
    assert False, f"{context}: expected one of {markers!r}"


ADMIN_PAGE_CONTRACTS: tuple[AdminPageContract, ...] = (
    AdminPageContract(
        page_id="orders",
        path="/internal/admin/orders",
        markers=(
            'class="admin-page orders-page"',
            'id="admin-orders-filters"',
            'id="admin-orders-table"',
            'class="admin-filter-pill',
            'id="admin-orders-delete-btn"',
            "data-date-range-picker",
            'name="q"',
        ),
        partial_path="/internal/admin/orders/table",
        partial_markers=("admin-orders-status-count-all",),
        partial_any_of=("orders-table-wrap", "orders-empty"),
    ),
    AdminPageContract(
        page_id="products",
        path="/internal/admin/products",
        markers=(
            'class="admin-page products-page',
            'class="products-page-tabs"',
            'id="admin-products-filters"',
            'id="admin-products-table"',
            'id="admin-product-detail"',
            'class="admin-filter-pill',
            'href="/internal/admin/products/new"',
            'href="/internal/admin/products/export.csv"',
        ),
        partial_path="/internal/admin/products/table",
        partial_markers=(
            'id="admin-products-search-input"',
            'id="admin-products-search-btn"',
            'id="admin-products-sort-select"',
            'name="top"',
        ),
        partial_any_of=("products-list-wrap", "empty muted"),
    ),
    AdminPageContract(
        page_id="products_bulk",
        path="/internal/admin/products?tab=bulk",
        markers=(
            'id="admin-products-bulk-form"',
            'id="admin-products-group-top-select"',
            'id="admin-products-group-activate-btn"',
            'id="admin-products-group-deactivate-btn"',
        ),
    ),
    AdminPageContract(
        page_id="products_brands",
        path="/internal/admin/products?tab=brands",
        markers=(
            'id="admin-products-brands-filters"',
            'id="admin-products-brands-search-input"',
            'id="admin-products-brands-search-btn"',
            'data-brand-visibility="all"',
            'data-brand-visibility="visible"',
            'data-brand-visibility="hidden"',
        ),
        partial_path="/internal/admin/products/brands",
        partial_markers=(
            'id="admin-products-brands-search-input"',
            'data-brand-visibility="all"',
        ),
    ),
    AdminPageContract(
        page_id="product_new",
        path="/internal/admin/products/new",
        markers=(
            'id="admin-product-create-form"',
            'name="is_active"',
            'type="checkbox"',
            'id="admin-product-image-files"',
            'form="admin-product-create-form"',
            "Создать товар",
        ),
    ),
    AdminPageContract(
        page_id="customers",
        path="/internal/admin/customers",
        markers=(
            'class="admin-page customers-page"',
            'id="admin-customers-filters"',
            'id="admin-customers-table"',
            'class="admin-filter-pill',
        ),
        partial_path="/internal/admin/customers/table",
        partial_markers=('class="customers-table',),
        partial_any_of=("customers-table", "customers-empty"),
    ),
    AdminPageContract(
        page_id="prices",
        path="/internal/admin/prices",
        markers=(
            'class="admin-page"',
            "Настройки цен",
            'class="prices-grid"',
            'name="eur_rate"',
            'name="markup_multiplier"',
            'name="delivery_fee_eur"',
            'name="service_commission_percent"',
            'name="referral_commission_percent"',
            'action="/internal/admin/prices/settings"',
            'action="/internal/admin/prices/refresh-rate"',
            'action="/internal/admin/prices/recalculate"',
            "Сохранить",
            "Обновить курс EUR",
            "Переоценка",
        ),
    ),
    AdminPageContract(
        page_id="margins",
        path="/internal/admin/margins",
        markers=(
            'class="admin-page margins-page"',
            'class="admin-filter-pills margins-sports"',
            'class="admin-filter-pill',
            'class="margin-group-card',
            'class="margin-fallback"',
        ),
    ),
    AdminPageContract(
        page_id="promos",
        path="/internal/admin/promos",
        markers=(
            "promos-toolbar",
            "promos-layout",
            "promos-create-card",
            "promos-help-card",
            "Справка по типам",
            'name="code"',
            'name="discount_type"',
            'name="usage_mode"',
            'name="active_to"',
            "Создать",
        ),
    ),
    AdminPageContract(
        page_id="support",
        path="/internal/admin/support",
        markers=(
            'class="admin-page orders-page support-page"',
            'class="admin-filter-pill',
            'id="admin-support-delete-btn"',
            'id="admin-support-table"',
            "Поддержка",
        ),
        partial_any_of=(),
    ),
    AdminPageContract(
        page_id="finance",
        path="/internal/admin/finance",
        markers=(
            'class="admin-page finance-page"',
            'id="admin-finance-filters"',
            "finance-presets",
            "finance-groups",
            "data-date-range-picker",
            'href="/internal/admin/finance/export.csv',
            "Скачать CSV",
        ),
    ),
)


@pytest.fixture
async def admin_html_client(merge_unique_suffix: int):
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        headers=headers,
    ) as client:
        yield client


@pytest.mark.parametrize(
    "page",
    EXCLUDED_ADMIN_PAGES,
)
@pytest.mark.asyncio
async def test_admin_excluded_pages_not_in_contracts(page: str) -> None:
    assert page not in {contract.page_id for contract in ADMIN_PAGE_CONTRACTS}


@pytest.mark.parametrize(
    "contract",
    ADMIN_PAGE_CONTRACTS,
    ids=lambda contract: contract.page_id,
)
@pytest.mark.asyncio
async def test_admin_page_shell_controls(
    admin_html_client: httpx.AsyncClient,
    contract: AdminPageContract,
) -> None:
    response = await admin_html_client.get(contract.path)
    assert response.status_code == 200, contract.page_id
    _assert_markers(response.text, contract.markers, f"{contract.page_id} shell")


@pytest.mark.parametrize(
    "contract",
    tuple(c for c in ADMIN_PAGE_CONTRACTS if c.partial_path),
    ids=lambda contract: f"{contract.page_id}-partial",
)
@pytest.mark.asyncio
async def test_admin_page_partial_controls(
    admin_html_client: httpx.AsyncClient,
    contract: AdminPageContract,
) -> None:
    assert contract.partial_path is not None
    response = await admin_html_client.get(contract.partial_path)
    assert response.status_code == 200, contract.page_id
    _assert_markers(
        response.text,
        contract.partial_markers,
        f"{contract.page_id} partial",
    )
    if contract.partial_any_of:
        _assert_any_marker(
            response.text,
            contract.partial_any_of,
            f"{contract.page_id} partial body",
        )


@pytest.mark.asyncio
async def test_support_list_bulk_delete_controls_when_rows(
    admin_html_client: httpx.AsyncClient,
) -> None:
    response = await admin_html_client.get("/internal/admin/support")
    assert response.status_code == 200
    if "orders-table-wrap--bulk-delete" not in response.text:
        pytest.skip("no support tickets in fixture DB")
    _assert_markers(
        response.text,
        ("data-support-select-all", "data-support-delete-checkbox"),
        "support list bulk delete",
    )


@pytest.mark.asyncio
async def test_orders_partial_bulk_delete_controls_when_rows(
    admin_html_client: httpx.AsyncClient,
) -> None:
    response = await admin_html_client.get("/internal/admin/orders/table")
    assert response.status_code == 200
    if "orders-table-wrap--bulk-delete" not in response.text:
        pytest.skip("no orders in fixture DB")
    _assert_markers(
        response.text,
        ("data-orders-select-all", "data-order-delete-checkbox"),
        "orders partial bulk delete",
    )


@pytest.mark.asyncio
async def test_products_detail_vitrina_and_media_tab_when_product_exists(
    admin_html_client: httpx.AsyncClient,
) -> None:
    table = await admin_html_client.get("/internal/admin/products/table")
    assert table.status_code == 200
    if "products-list-wrap" not in table.text:
        pytest.skip("no products in fixture DB")
    match = re.search(r"/internal/admin/products/(\d+)/detail", table.text)
    if not match:
        pytest.skip("no product rows in fixture DB")
    product_id = match.group(1)
    detail = await admin_html_client.get(
        f"/internal/admin/products/{product_id}/detail"
    )
    assert detail.status_code == 200
    _assert_markers(
        detail.text,
        ('name="is_active"', 'class="products-toggle"'),
        "product detail vitrina",
    )
    _assert_markers(
        detail.text,
        ('data-tab="media"', 'name="image_url"', 'name="gallery_urls"'),
        "product detail media",
    )


@pytest.mark.asyncio
async def test_margins_rule_form_when_group_selected(
    admin_html_client: httpx.AsyncClient,
) -> None:
    shell = await admin_html_client.get("/internal/admin/margins")
    assert shell.status_code == 200
    match = re.search(
        r'href="/internal/admin/margins\?sport=[^&]+&selected=([^"]+)"', shell.text
    )
    if not match:
        pytest.skip("no margin group cards in DB")
    selected = match.group(1)
    sport_match = re.search(
        r'href="/internal/admin/margins\?sport=([^"&]+)',
        shell.text,
    )
    assert sport_match
    detail = await admin_html_client.get(
        "/internal/admin/margins",
        params={"sport": sport_match.group(1), "selected": selected},
    )
    assert detail.status_code == 200
    _assert_markers(
        detail.text,
        (
            'class="margin-rule-form"',
            'name="margin_percent"',
            "Сохранить и пересчитать",
        ),
        "margins rule detail",
    )


def _brand_toggle_form(html: str, brand: str) -> str:
    pattern = (
        rf"<form[^>]*products-brands-toggle-form[^>]*>"
        rf'[\s\S]*?name="brand" value="{re.escape(brand)}"[\s\S]*?</form>'
    )
    match = re.search(pattern, html)
    return match.group(0) if match else ""


@pytest.mark.asyncio
async def test_admin_products_brand_toggle_updates_visibility(
    admin_html_client: httpx.AsyncClient,
) -> None:
    page = await admin_html_client.get("/internal/admin/products/brands")
    assert page.status_code == 200
    brand_match = re.search(r'name="brand" value="([^"]+)"', page.text)
    if not brand_match:
        pytest.skip("no brands in fixture DB")
    brand = brand_match.group(1)

    hide = await admin_html_client.post(
        "/internal/admin/products/brands/toggle",
        data={"brand": brand, "visible": "false"},
    )
    assert hide.status_code == 200
    hide_form = _brand_toggle_form(hide.text, brand)
    assert hide_form
    assert "checked" not in hide_form

    show = await admin_html_client.post(
        "/internal/admin/products/brands/toggle",
        data={"brand": brand, "visible": "true"},
    )
    assert show.status_code == 200
    show_form = _brand_toggle_form(show.text, brand)
    assert show_form
    assert "checked" in show_form


@pytest.mark.asyncio
async def test_promos_row_actions_when_promos_exist(
    admin_html_client: httpx.AsyncClient,
) -> None:
    response = await admin_html_client.get("/internal/admin/promos")
    assert response.status_code == 200
    if "/toggle" not in response.text:
        pytest.skip("no promos in fixture DB")
    _assert_markers(
        response.text,
        ('action="/internal/admin/promos/', "Выкл", "Удалить"),
        "promos row actions",
    )
