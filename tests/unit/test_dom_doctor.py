import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete

from src.jobs.dom_doctor import (
    _load_doctor_candidates,
    _reset_claimed_attempts,
    enqueue_dom_doctor,
)
from src.jobs.dom_scheduler import (
    _load_priority_recoverable_incomplete,
    _load_scheduler_products,
)
from src.models.product import Product, ProductFeature, ProductImage
from src.repositories.session import async_session_maker
from src.services.catalog.importing.product_complete import is_enrichment_hold

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
        "dom_doctor_batch_size": 50,
        "dom_enqueue_lock_ttl_seconds": 60,
        "dom_queue_max_pending": 1000,
        "dom_processing_claim_ttl_minutes": 15,
        "dom_owner_token_enqueue_enabled": False,
        "dom_priority_recovery_limit": 20,
        "dom_rolling_batch_size": 100,
        "dom_rolling_fetch_multiplier": 3,
        "dom_refresh_stale_hours": 6,
        "import_chunk_size": 1,
        "import_download_images": False,
        "catalog_dom_enrichment_func": "func",
        "catalog_dom_job_timeout": 600,
    }
    values.update(overrides)
    return MagicMock(**values)


def _hold_product(
    prefix: str,
    index: int,
    last_error: str = "invalid_description",
    **fields,
) -> Product:
    product = Product(
        title=f"DOM doctor {prefix} {index}",
        brand="TestBrand",
        sale_price=100,
        regular_price=100,
        supplier_price_eur=50,
        stock=10,
        is_active=True,
        external_id=f"{prefix}-ext-{index}",
        product_url=f"https://example.com/{prefix}/{index}",
        description_raw=_VALID,
        dom_attempts=5,
        dom_last_error=last_error,
        dom_last_attempt_at=_now() - timedelta(hours=7),
        deactivated_at=None,
    )
    for key, value in fields.items():
        setattr(product, key, value)
    product.images = []
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


async def _reload(product_id: int) -> Product:
    async with async_session_maker() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        session.expunge(product)
        return product


def _redis_mock() -> MagicMock:
    store: dict[str, str] = {}
    redis = MagicMock()

    def set_impl(key, value, nx=False, ex=None):
        if nx and key in store:
            return False
        store[key] = value
        return True

    redis.set.side_effect = set_impl
    redis.get.side_effect = lambda key: store.get(key)
    redis._store = store
    return redis


@pytest.fixture
def prefix() -> str:
    return f"dom-doc-{uuid.uuid4().hex[:12]}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    ["invalid_description", "invalid_gallery", "invalid_pdp"],
)
async def test_exhausted_invalid_errors_are_eligible(prefix: str, error: str) -> None:
    product = _hold_product(prefix, 1, last_error=error)
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(_env(), 50)
        assert any(row.get("id") == product.id for row in payloads)
        match = next(row for row in payloads if row.get("id") == product.id)
        assert match["dom_mode"] == "FULL"
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_attempts_below_max_excluded(prefix: str) -> None:
    product = _hold_product(prefix, 1, last_error="invalid_description", dom_attempts=4)
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(_env(), 50)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["not_found", "timeout", "captcha", "parser_error"])
async def test_non_hold_errors_excluded(prefix: str, error: str) -> None:
    product = _hold_product(prefix, 1, last_error=error)
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(_env(), 50)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_fresh_last_attempt_excluded(prefix: str) -> None:
    product = _hold_product(prefix, 1, dom_last_attempt_at=_now())
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(
            _env(dom_retry_cooldown_seconds=3600), 50
        )
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_active_processing_claim_excluded(prefix: str) -> None:
    now = _now()
    product = _hold_product(
        prefix,
        1,
        dom_processing_at=now,
        dom_processing_expires_at=now + timedelta(hours=1),
    )
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(_env(), 50)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_inactive_hold_excluded(prefix: str) -> None:
    product = _hold_product(prefix, 1, is_active=False)
    ids = await _insert([product])
    try:
        payloads = await _load_doctor_candidates(_env(), 50)
        assert all(row.get("id") != product.id for row in payloads)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_scheduler_does_not_load_hold(prefix: str) -> None:
    product = _hold_product(prefix, 1)
    ids = await _insert([product])
    try:
        env = _env()
        doctor = await _load_doctor_candidates(env, 50)
        assert any(row.get("id") == product.id for row in doctor)
        scheduler = await _load_scheduler_products(env, 50)
        assert all(item.id != product.id for item in scheduler)
        priority = await _load_priority_recoverable_incomplete(env, 20)
        assert all(row.get("id") != product.id for row in priority)
    finally:
        await _delete(ids)


@pytest.mark.asyncio
async def test_reset_only_after_successful_claim(prefix: str) -> None:
    product = _hold_product(prefix, 1)
    ids = await _insert([product])
    payload = {
        "id": ids[0],
        "item_id": product.external_id,
        "dom_mode": "FULL",
        "product_url": product.product_url,
    }
    try:
        reset_before = await _reset_claimed_attempts([payload])
        assert reset_before == 0
        loaded = await _reload(ids[0])
        assert loaded.dom_attempts == 5
        assert loaded.dom_last_error == "invalid_description"

        env = _env()
        claimed, skipped = await _claim(payload, env)
        assert skipped == 0
        assert len(claimed) == 1
        reset_after = await _reset_claimed_attempts(claimed)
        assert reset_after == 1
        loaded = await _reload(ids[0])
        assert loaded.dom_attempts == 0
        assert loaded.dom_last_error == "invalid_description"
        assert loaded.is_active is True
        assert loaded.deactivated_at is None
    finally:
        await _delete(ids)


async def _claim(payload: dict, env: MagicMock) -> tuple[list[dict], int]:
    from src.jobs.dom_processing_claim import claim_dom_processing_products

    return await claim_dom_processing_products([payload], env)


def test_valid_full_after_doctor_clears_hold() -> None:
    product = _hold_product("pred", 1, last_error=None, dom_attempts=0)
    assert is_enrichment_hold(product, 5) is False


def test_invalid_full_after_doctor_is_retry_not_hold() -> None:
    product = _hold_product("pred", 1, last_error="invalid_description", dom_attempts=1)
    assert is_enrichment_hold(product, 5) is False


def test_exhausted_hold_predicate_still_true() -> None:
    product = _hold_product("pred", 1)
    assert is_enrichment_hold(product, 5) is True


@pytest.mark.asyncio
async def test_overloaded_queue_skips_claim_reset_enqueue() -> None:
    env = _env()
    with (
        patch("src.jobs.dom_doctor.load_settings", return_value=env),
        patch("src.jobs.dom_doctor.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_doctor.dom_queue_overloaded", return_value=True),
        patch(
            "src.jobs.dom_doctor._load_doctor_candidates",
            new_callable=AsyncMock,
        ) as load_mock,
        patch(
            "src.jobs.dom_doctor.claim_dom_processing_products",
            new_callable=AsyncMock,
        ) as claim_mock,
        patch(
            "src.jobs.dom_doctor._reset_claimed_attempts",
            new_callable=AsyncMock,
        ) as reset_mock,
        patch("src.jobs.dom_doctor.enqueue_dom_product_chunks") as enqueue_mock,
    ):
        result = await enqueue_dom_doctor(env=env)
    assert result["skipped"] is True
    assert result["reason"] == "dom_queue_overloaded"
    assert result["claimed"] == 0
    assert result["enqueued"] == 0
    assert result["errors"] == 0
    load_mock.assert_not_called()
    claim_mock.assert_not_called()
    reset_mock.assert_not_called()
    enqueue_mock.assert_not_called()


@pytest.mark.asyncio
async def test_empty_selection_skips() -> None:
    env = _env()
    with (
        patch("src.jobs.dom_doctor.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_doctor.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_doctor._load_doctor_candidates",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_doctor.claim_dom_processing_products",
            new_callable=AsyncMock,
        ) as claim_mock,
        patch("src.jobs.dom_doctor.enqueue_dom_product_chunks") as enqueue_mock,
    ):
        result = await enqueue_dom_doctor(env=env)
    assert result["reason"] == "empty_selection"
    assert result["skipped"] is True
    claim_mock.assert_not_called()
    enqueue_mock.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_payload_full_and_batch_limit() -> None:
    env = _env(dom_doctor_batch_size=50)
    candidates = [
        {
            "id": index,
            "item_id": f"doc-{index}",
            "dom_mode": "FULL",
            "product_url": f"https://example.com/{index}",
        }
        for index in range(1, 61)
    ]
    reserved_holder: list[list[dict]] = []

    def fake_reserve(rows, settings, batch_size, owner_token=None):
        taken = rows[:batch_size]
        reserved_holder.append(taken)
        return taken, 0

    async def fake_claim(reserved, settings, owner_token=None):
        return reserved, 0

    with (
        patch("src.jobs.dom_doctor.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_doctor.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_doctor._load_doctor_candidates",
            new_callable=AsyncMock,
            return_value=candidates,
        ) as load_mock,
        patch(
            "src.jobs.dom_doctor.reserve_products_with_dedup",
            side_effect=fake_reserve,
        ),
        patch(
            "src.jobs.dom_doctor.claim_dom_processing_products",
            side_effect=fake_claim,
        ),
        patch(
            "src.jobs.dom_doctor._reset_claimed_attempts",
            new_callable=AsyncMock,
            return_value=50,
        ) as reset_mock,
        patch(
            "src.jobs.dom_doctor.enqueue_dom_product_chunks",
            return_value=2,
        ) as enqueue_mock,
    ):
        result = await enqueue_dom_doctor(env=env)

    load_mock.assert_called_once()
    assert load_mock.call_args.args[1] == 50
    assert len(reserved_holder[0]) == 50
    reset_mock.assert_awaited_once()
    assert reset_mock.await_args.args[0] == reserved_holder[0]
    enqueue_mock.assert_called_once()
    enqueued = enqueue_mock.call_args.args[0]
    assert len(enqueued) == 50
    assert all(row["dom_mode"] == "FULL" for row in enqueued)
    assert result["eligible"] == 60
    assert result["claimed"] == 50
    assert result["enqueued"] == 2
    assert result["enqueued_products"] == 50
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_duplicate_doctor_one_claim_enqueue() -> None:
    env = _env()
    product = {
        "id": 91001,
        "item_id": "doc-dup-sku",
        "dom_mode": "FULL",
        "product_url": "https://example.com/doc-dup",
    }
    redis = _redis_mock()
    claim_calls: list[list[dict]] = []
    enqueue_calls: list[list[dict]] = []

    async def fake_claim(reserved, settings, owner_token=None):
        claim_calls.append(list(reserved))
        return reserved, 0

    def fake_enqueue(claimed, settings, owner_token=None):
        enqueue_calls.append(list(claimed))
        return 1

    with (
        patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis),
        patch("src.jobs.dom_doctor.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_doctor.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_doctor._load_doctor_candidates",
            new_callable=AsyncMock,
            return_value=[product],
        ),
        patch(
            "src.jobs.dom_doctor.claim_dom_processing_products",
            side_effect=fake_claim,
        ),
        patch(
            "src.jobs.dom_doctor._reset_claimed_attempts",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "src.jobs.dom_doctor.enqueue_dom_product_chunks",
            side_effect=fake_enqueue,
        ),
    ):
        first = await enqueue_dom_doctor(env=env)
        second = await enqueue_dom_doctor(env=env)

    assert first["claimed"] == 1
    assert first["enqueued"] == 1
    assert second["claimed"] == 0
    assert second["skipped_locked"] == 1
    assert second["reason"] == "empty_claim"
    assert len(claim_calls) == 1
    assert len(enqueue_calls) == 1


@pytest.mark.asyncio
async def test_enqueue_failure_after_claim_is_logged_not_retried_inline() -> None:
    env = _env()
    product = {
        "id": 91002,
        "item_id": "doc-fail-sku",
        "dom_mode": "FULL",
        "product_url": "https://example.com/doc-fail",
    }
    with (
        patch("src.jobs.dom_doctor.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_doctor.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_doctor._load_doctor_candidates",
            new_callable=AsyncMock,
            return_value=[product],
        ),
        patch(
            "src.jobs.dom_doctor.reserve_products_with_dedup",
            return_value=([product], 0),
        ),
        patch(
            "src.jobs.dom_doctor.claim_dom_processing_products",
            new_callable=AsyncMock,
            return_value=([product], 0),
        ),
        patch(
            "src.jobs.dom_doctor._reset_claimed_attempts",
            new_callable=AsyncMock,
            return_value=1,
        ) as reset_mock,
        patch(
            "src.jobs.dom_doctor.enqueue_dom_product_chunks",
            side_effect=RuntimeError("rq down"),
        ),
    ):
        result = await enqueue_dom_doctor(env=env)
    assert result["claimed"] == 1
    assert result["errors"] == 1
    assert result["reason"] == "enqueue_failed"
    assert result["enqueued"] == 0
    reset_mock.assert_awaited_once()
