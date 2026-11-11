import asyncio
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from src.models.product import ProductImage
from src.repositories.session import async_session_maker
from src.schemas.product import ProductUpdate
from src.services.product_service import ProductService
from src.services.user_service import UserService
from tests.integration.helpers.test_customer import create_test_customer

ROOT = Path(__file__).resolve().parents[2]

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


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


def admin_client(base: str) -> httpx.Client:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    client = httpx.Client(base_url=base, follow_redirects=True, timeout=30)
    client.post(
        "/internal/admin/login",
        data={
            "username": login,
            "password": password,
            "next": "/internal/admin/products",
        },
    )
    return client


def upload_png(client: httpx.Client, name: str) -> str:
    response = client.post(
        "/internal/admin/products/upload-image",
        files={"file": (name, PNG, "image/png")},
    )
    response.raise_for_status()
    url = response.json().get("url")
    if not url:
        raise RuntimeError("upload-image: пустой url")
    return url


def run_http_create_gallery(client: httpx.Client, stamp: str) -> int:
    url1 = upload_png(client, f"smoke-a-{stamp}.png")
    url2 = upload_png(client, f"smoke-b-{stamp}.png")
    product_url = f"https://smoke.local/e2e-{stamp}"
    response = client.post(
        "/internal/admin/products/create",
        data={
            "title": f"Smoke E2E {stamp}",
            "brand": "Smoke",
            "product_url": product_url,
            "sale_price": "1000",
            "regular_price": "1200",
            "stock": "3",
            "is_active": "true",
            "gallery_urls": [url1, url2],
        },
    )
    if response.status_code not in (200, 303):
        raise RuntimeError(f"create product: HTTP {response.status_code}")
    match = re.search(r"[?&]id=(\d+)", str(response.url))
    if not match:
        raise RuntimeError("create product: не найден id в redirect")
    product_id = int(match.group(1))
    detail = client.get(
        f"/internal/admin/products/{product_id}/detail",
        params={"view": "in_catalog", "top": "All", "page": 1},
    )
    detail.raise_for_status()
    if url1 not in detail.text and url2 not in detail.text:
        raise RuntimeError("detail: нет URL загруженных изображений")
    if "products-detail__thumb" not in detail.text:
        raise RuntimeError("detail: нет превью обложки")
    return product_id


def run_delivery_flow(client: httpx.Client, stamp: str) -> int:
    email = f"smoke-e2e-{stamp}@local.test"

    async def _create_user() -> int:
        async with async_session_maker() as session:
            user = await create_test_customer(
                session,
                name=f"Smoke E2E {stamp}",
                email=email,
                telegram_username=None,
                telegram_id=None,
            )
            await session.commit()
            return user.id

    user_id = asyncio.run(_create_user())

    save = client.post(
        f"/internal/admin/customers/{user_id}/delivery",
        data={
            "last_name": "Ivanov",
            "first_name": "Ivan",
            "street": "Testovaya",
            "house": "10A",
            "apartment": "42",
            "city": "Moscow",
            "postal_code": "101000",
            "phone": "+79001234567",
        },
    )
    if save.status_code not in (200, 303):
        raise RuntimeError(f"delivery save: HTTP {save.status_code}")
    if "error=" in str(save.url):
        raise RuntimeError(f"delivery save: redirect с ошибкой ({save.url})")
    page = client.get("/internal/admin/customers", params={"id": user_id})
    page.raise_for_status()
    if 'value="Testovaya"' not in page.text:
        raise RuntimeError("delivery save: улица не в форме")

    reset = client.post(f"/internal/admin/customers/{user_id}/delivery/reset")
    if reset.status_code not in (200, 303):
        raise RuntimeError(f"delivery reset: HTTP {reset.status_code}")
    after = client.get("/internal/admin/customers", params={"id": user_id})
    after.raise_for_status()
    if "Профиль доставки не заполнен" not in after.text:
        raise RuntimeError("delivery reset: empty-state не показан")
    return user_id


async def run_service_category_preserve(product_id: int) -> None:
    async with async_session_maker() as session:
        service = ProductService(session)
        product = await service.product_crud.get_by_id_with_related(product_id)
        if not product:
            raise RuntimeError("category preserve: товар не найден")
        before = (
            product.sport_type,
            product.category_l1,
            product.category_l2,
            product.category_l3,
        )
        await service.update_product(
            product_id,
            ProductUpdate(title=f"{product.title} (patched)"),
        )
        product = await service.product_crud.get_by_id_with_related(product_id)
        after = (
            product.sport_type,
            product.category_l1,
            product.category_l2,
            product.category_l3,
        )
        if before != after:
            raise RuntimeError(f"category preserve: ожидали {before}, получили {after}")


async def count_product_images(product_id: int) -> int:
    async with async_session_maker() as session:
        rows = await session.scalars(
            select(ProductImage).where(ProductImage.product_id == product_id)
        )
        return len(list(rows))


async def cleanup(product_id: int | None, user_id: int | None) -> None:
    async with async_session_maker() as session:
        if product_id:
            try:
                await ProductService(session).hard_delete_product(product_id)
            except Exception as exc:
                print(f"WARN cleanup product #{product_id}: {exc}")
        if user_id:
            try:
                await UserService(session).delete_admin_customer(user_id)
            except Exception as exc:
                print(f"WARN cleanup customer #{user_id}: {exc}")


async def run_db_checks_and_cleanup(
    product_ids: list[int],
    user_id: int | None,
    category_product_id: int | None,
) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    if category_product_id:
        try:
            await run_service_category_preserve(category_product_id)
            results.append(("category_preserve_partial_update", True, ""))
        except Exception as exc:
            results.append(("category_preserve_partial_update", False, str(exc)))
    else:
        results.append(("category_preserve_partial_update", False, "no product"))

    for pid in product_ids:
        try:
            images = await count_product_images(pid)
            results.append((f"product_{pid}_images", images >= 2, f"images={images}"))
        except Exception as exc:
            results.append((f"product_{pid}_images", False, str(exc)))

    for pid in reversed(product_ids):
        await cleanup(pid, None)
    if user_id:
        await cleanup(None, user_id)
    return results


def playwright_login(page, base: str) -> None:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    page.goto(f"{base}/internal/admin/login")
    page.fill("#username", login)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(
        lambda url: "/internal/admin/login" not in url,
        timeout=10000,
    )


def run_playwright_create(base: str, stamp: str) -> int:
    png_a = Path(f"/tmp/shopstore-smoke-a-{stamp}.png")
    png_b = Path(f"/tmp/shopstore-smoke-b-{stamp}.png")
    png_a.write_bytes(PNG)
    png_b.write_bytes(PNG)
    product_id: int | None = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            playwright_login(page, base)

            page.goto(f"{base}/internal/admin/products/new")
            page.fill('input[name="title"]', f"Smoke UI {stamp}")
            page.fill('input[name="product_url"]', f"https://smoke.local/ui-{stamp}")
            page.set_input_files("#admin-product-image-files", [str(png_a), str(png_b)])
            page.wait_for_function(
                "() => document.querySelectorAll('#admin-product-gallery-preview img')"
                ".length >= 2"
                " && document.querySelectorAll('input[name=\"gallery_urls\"]')"
                ".length >= 2",
                timeout=10000,
            )
            previews = page.locator("#admin-product-gallery-preview img").count()
            if previews < 2:
                raise RuntimeError(f"playwright create: preview images={previews}")
            gallery_urls = page.locator('input[name="gallery_urls"]').evaluate_all(
                "els => els.map((el) => el.value).filter(Boolean)"
            )
            if len(gallery_urls) < 2:
                raise RuntimeError("playwright create: hidden gallery_urls не созданы")
            page.fill('input[name="sale_price"]', "1000")
            # Submit через UI: file input вынесен из <form>, иначе браузер шлёт
            # multipart и FastAPI-страница уходит на /login (cookie не теряется).
            page.click('button[type=submit][form="admin-product-create-form"]')
            page.wait_for_url(
                lambda url: (
                    "/internal/admin/login" not in url
                    and "/internal/admin/products" in url
                ),
                timeout=15000,
            )
            match = re.search(r"[?&]id=(\d+)", page.url)
            if not match:
                raise RuntimeError(f"playwright create: нет id ({page.url})")
            product_id = int(match.group(1))
            page.goto(f"{base}/internal/admin/products?id={product_id}")
            page.wait_for_selector(".products-detail__thumb", timeout=10000)
            browser.close()
    finally:
        png_a.unlink(missing_ok=True)
        png_b.unlink(missing_ok=True)
    if product_id is None:
        raise RuntimeError("playwright create: product_id не получен")
    return product_id


def run_admin_ui_smoke() -> list[str]:
    load_env()
    base = os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
    stamp = str(int(time.time()))
    product_ids: list[int] = []
    user_id: int | None = None
    results: list[tuple[str, bool, str]] = []
    category_product_id: int | None = None

    client = admin_client(base)

    try:
        pid = run_http_create_gallery(client, f"http-{stamp}")
        product_ids.append(pid)
        category_product_id = pid
        results.append(("create_2_images_gallery_db", True, f"product_id={pid}"))
    except Exception as exc:
        results.append(("create_2_images_gallery_db", False, str(exc)))

    try:
        user_id = run_delivery_flow(client, stamp)
        results.append(("delivery_save_reset", True, f"user_id={user_id}"))
    except Exception as exc:
        results.append(("delivery_save_reset", False, str(exc)))

    try:
        ui_pid = run_playwright_create(base, f"ui-{stamp}")
        product_ids.append(ui_pid)
        results.append(("playwright_create_upload_save", True, f"product_id={ui_pid}"))
    except Exception as exc:
        results.append(("playwright_create_upload_save", False, str(exc)))

    db_results = asyncio.run(
        run_db_checks_and_cleanup(product_ids, user_id, category_product_id)
    )
    results.extend(db_results)

    failed = []
    for name, ok, info in results:
        suffix = f" ({info})" if info else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")
        if not ok:
            failed.append(name)
    return failed


@pytest.mark.e2e
def test_admin_ui_smoke() -> None:
    failed = run_admin_ui_smoke()
    assert not failed, f"failed checks: {', '.join(failed)}"


if __name__ == "__main__":
    raise SystemExit(0 if not run_admin_ui_smoke() else 1)
