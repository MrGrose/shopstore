import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete

from src.jobs.dom_scheduler import (
    _load_priority_recoverable_incomplete,
    _load_scheduler_products,
    _merge_dom_candidate_groups,
    _priority_recovery_cap,
    enqueue_dom_scheduler,
    reserve_products_with_dedup,
)
from src.models.product import Product, ProductFeature, ProductImage
from src.repositories.session import async_session_maker
from src.services.catalog.importing.product_complete import validate_full_dom_details
from src.utils.html_text import is_manufacturer_imprint_description

_IMPRINT = (
    "TRADINTER S.L. Transpaderne, 29 4 Izsa., Building Barajas I, "
    "Madrid 28042, Spain www.bullpadel.com"
)
_VALID = (
    "Experience Unmatched Comfort with the Oneda Tank Top for Women. "
    "Designed specifically for the dynamic world of padel."
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _env(**overrides) -> MagicMock:
    values = {
        "dom_retry_cooldown_seconds": 0,
        "dom_max_attempts": 5,
        "dom_priority_recovery_limit": 20,
        "dom_rolling_batch_size": 100,
        "dom_rolling_fetch_multiplier": 3,
        "dom_refresh_stale_hours": 6,
        "dom_enqueue_lock_ttl_seconds": 60,
        "dom_queue_max_pending": 1000,
        "dom_owner_token_enqueue_enabled": False,
        "import_chunk_size": 1,
        "import_download_images": False,
        "catalog_dom_enrichment_func": "func",
        "catalog_dom_job_timeout": 600,
    }
    values.update(overrides)
    return MagicMock(**values)


def _recoverable(prefix: str, index: int, **fields) -> Product:
    product = Product(
        title=f"DOM pri {prefix} {index}",
        brand="TestBrand",
        sale_price=100,
        regular_price=100,
        supplier_price_eur=50,
        stock=10,
        is_active=True,
        external_id=f"{prefix}-ext-{index}",
        product_url=f"https://example.com/{prefix}/{index}",
        description_raw=_IMPRINT,
        dom_attempts=0,
        dom_full_at=_now() - timedelta(days=1),
        catalog_synced_at=datetime(1970, 1, 1) + timedelta(seconds=index),
    )
    for key, value in fields.items():
        setattr(product, key, value)
    product.images = [
        ProductImage(url=f"https://example.com/{prefix}/{index}.jpg", position=0),
    ]
    product.features = []
    return product


async def _insert(products: list[Product]) -> list[int]:
    async with async_session_maker() as session:
        session.add_all(products)
        await session.commit()
        for product in products:
            await session.refresh(product)
        return [int(product.id) for product in products]


async def _delete(product_ids: list[int]) -> None:
    if not product_ids:
        return
    async with async_session_maker() as session:
        await session.execute(
            delete(ProductFeature).where(ProductFeature.product_id.in_(product_ids))
        )
        await session.execute(
            delete(ProductImage).where(ProductImage.product_id.in_(product_ids))
        )
        await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.commit()


@pytest.fixture
def prefix() -> str:
    return f"dom-pri-{uuid.uuid4().hex[:12]}"


def test_python_imprint_matches_sql_markers_and_max_len() -> None:
    assert is_manufacturer_imprint_description(_IMPRINT) is True
    assert is_manufacturer_imprint_description("") is False
    assert is_manufacturer_imprint_description(None) is False
    assert is_manufacturer_imprint_description("x" * 150) is False
    long_tradinter = ("x" * 130) + " TRADINTER www.bullpadel.com"
    assert len(long_tradinter) >= 150
    assert is_manufacturer_imprint_description(long_tradinter) is False


def test_priority_recovery_cap_leaves_normal_batch_capacity() -> None:
    env = _env(dom_priority_recovery_limit=20)
    assert _priority_recovery_cap(100, env) == 20
    assert _priority_recovery_cap(10, env) == 5
    assert _priority_recovery_cap(4, env) == 2
    assert _priority_recovery_cap(1, env) == 0


def test_merge_priority_wins_and_dedups() -> None:
    priority = [{"id": 10, "dom_mode": "FULL", "src": "priority"}]
    stock_zero = [{"id": 11, "dom_mode": "FULL"}]
    window_full = [
        {"id": 10, "dom_mode": "LITE", "src": "window"},
        {"id": 12, "dom_mode": "FULL"},
    ]
    window_lite = [{"id": 13, "dom_mode": "LITE"}]
    merged = _merge_dom_candidate_groups(priority, stock_zero, window_full, window_lite)
    assert [row["id"] for row in merged] == [10, 11, 12, 13]
    assert merged[0]["src"] == "priority"
    assert merged[0]["dom_mode"] == "FULL"


def test_normal_scheduler_keeps_remaining_batch_capacity() -> None:
    env = _env()
    priority = [{"id": 1, "dom_mode": "FULL"}]
    window_full = [{"id": index, "dom_mode": "FULL"} for index in range(2, 8)]
    merged = _merge_dom_candidate_groups(priority, [], window_full, [])
    with patch(
        "src.jobs.dom_scheduler.try_acquire_dom_enqueue_lock",
        return_value=True,
    ):
        reserved, skipped = reserve_products_with_dedup(merged, env, 4)
    assert skipped == 0
    assert [row["id"] for row in reserved] == [1, 2, 3, 4]


def test_phase1_validation_failure_remains_intact() -> None:
    assert (
        validate_full_dom_details(
            {
                "description": _IMPRINT,
                "media_gallery": [{"url": "https://example.com/a.jpg"}],
            }
        )
        == "invalid_description"
    )


@pytest.mark.asyncio
async def test_priority_loader_selects_imprint_full_at_with_image(
    prefix: str,
) -> None:
    product = _recoverable(prefix, 1)
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(_env(), 20)
        matched = [row for row in payloads if row.get("id") == product.id]
        assert len(matched) == 1
        assert matched[0]["dom_mode"] == "FULL"
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_skips_empty_description_without_full_at(
    prefix: str,
) -> None:
    product = _recoverable(prefix, 1, description_raw=None, dom_full_at=None)
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(_env(), 20)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_skips_normal_incomplete_non_imprint(
    prefix: str,
) -> None:
    product = _recoverable(prefix, 1, description_raw=None, dom_full_at=None)
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(_env(), 20)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_skips_cooldown(prefix: str) -> None:
    product = _recoverable(prefix, 1, dom_last_attempt_at=_now())
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(
            _env(dom_retry_cooldown_seconds=3600), 20
        )
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_skips_max_attempts(prefix: str) -> None:
    product = _recoverable(prefix, 1, dom_attempts=5)
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(
            _env(dom_max_attempts=5), 20
        )
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_skips_active_processing_claim(prefix: str) -> None:
    now = _now()
    product = _recoverable(
        prefix,
        1,
        dom_processing_at=now,
        dom_processing_expires_at=now + timedelta(hours=1),
    )
    ids = await _insert([product])
    try:
        payloads = await _load_priority_recoverable_incomplete(_env(), 20)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_loader_respects_limit(prefix: str) -> None:
    products = [_recoverable(prefix, index) for index in range(3)]
    ids = await _insert(products)
    try:
        payloads = await _load_priority_recoverable_incomplete(_env(), 2)
        matched = [row for row in payloads if row.get("id") in set(ids)]
        assert len(matched) == 2
        assert all(row.get("dom_mode") == "FULL" for row in matched)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_selects_candidate_outside_normal_fetch_window(
    prefix: str,
) -> None:
    filler = Product(
        title=f"DOM pri {prefix} filler",
        brand="TestBrand",
        sale_price=100,
        regular_price=100,
        supplier_price_eur=50,
        stock=10,
        is_active=True,
        external_id=f"{prefix}-filler",
        product_url=f"https://example.com/{prefix}/filler",
        description_raw=None,
        dom_attempts=0,
        catalog_synced_at=_now() - timedelta(days=400),
    )
    hidden = _recoverable(prefix, 99, catalog_synced_at=_now() - timedelta(days=1))
    ids = await _insert([filler, hidden])
    try:
        window = await _load_scheduler_products(_env(), 1)
        window_ids = {int(product.id) for product in window}
        assert hidden.id not in window_ids
        payloads = await _load_priority_recoverable_incomplete(_env(), 500)
        assert any(row.get("id") == hidden.id for row in payloads)
        matched = [row for row in payloads if row.get("id") == hidden.id]
        assert matched and matched[0]["dom_mode"] == "FULL"
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_priority_candidate_uses_existing_reserve_claim_enqueue() -> None:
    env = _env(dom_rolling_batch_size=4, dom_priority_recovery_limit=20)
    priority = [{"id": 16879, "dom_mode": "FULL"}]
    claimed_arg: list = []

    async def fake_claim(reserved, settings, owner_token=None):
        claimed_arg.append([row.get("id") for row in reserved])
        return reserved, 0

    def fake_enqueue(claimed, settings, owner_token=None):
        return 1

    with (
        patch("src.jobs.dom_scheduler.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_scheduler.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_scheduler._load_priority_recoverable_incomplete",
            new_callable=AsyncMock,
            return_value=priority,
        ),
        patch(
            "src.jobs.dom_scheduler._load_scheduler_products",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._load_stock_zero_incomplete",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._split_scheduler_candidates",
            return_value=([], []),
        ),
        patch(
            "src.jobs.dom_scheduler.try_acquire_dom_enqueue_lock",
            return_value=True,
        ),
        patch(
            "src.jobs.dom_scheduler.claim_dom_processing_products",
            side_effect=fake_claim,
        ),
        patch(
            "src.jobs.dom_scheduler.enqueue_dom_product_chunks",
            side_effect=fake_enqueue,
        ) as enqueue_mock,
    ):
        result = await enqueue_dom_scheduler(limit=4, env=env)

    assert result["priority_eligible"] == 1
    assert result["priority_enqueued"] == 1
    assert claimed_arg == [[16879]]
    enqueue_mock.assert_called_once()
    assert enqueue_mock.call_args.args[0][0]["id"] == 16879
    assert enqueue_mock.call_args.args[0][0]["dom_mode"] == "FULL"
