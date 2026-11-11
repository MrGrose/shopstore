from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from src.jobs import dom_enqueue_lock, dom_processing_claim, dom_scheduler
from src.jobs.dom_product_payload import enqueue_dom_product_chunks

_PRODUCT = {"id": 1, "item_id": "sku-1", "product_url": "https://example.com/p"}
_OWNER_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_OWNER_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _redis_mock() -> MagicMock:
    store: dict[str, str] = {}

    redis = MagicMock()

    def set_impl(key, value, nx=False, ex=None):
        if nx and key in store:
            return False
        store[key] = value
        return True

    def get_impl(key):
        return store.get(key)

    def delete_impl(*keys):
        count = 0
        for key in keys:
            if key in store:
                del store[key]
                count += 1
        return count

    redis.set.side_effect = set_impl
    redis.get.side_effect = get_impl
    redis.delete.side_effect = delete_impl
    redis._store = store

    def run_script(keys=None, args=None, **kwargs):
        key = keys[0]
        token = args[0]
        if store.get(key) == token:
            del store[key]
            return 1
        return 0

    script_obj = MagicMock(side_effect=run_script)
    redis.register_script.return_value = script_obj
    return redis


def _session_maker_mock() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    return session_cm, session


def test_redis_acquire_second_token_fails() -> None:
    dom_enqueue_lock._compare_and_del_script = None
    redis = _redis_mock()
    with patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis):
        assert dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600, _OWNER_A)
        assert not dom_enqueue_lock.try_acquire_dom_enqueue_lock(
            _PRODUCT, 600, _OWNER_B
        )


def test_redis_release_wrong_token_keeps_lock() -> None:
    dom_enqueue_lock._compare_and_del_script = None
    redis = _redis_mock()
    key = dom_enqueue_lock.product_enqueue_lock_key(_PRODUCT)
    assert key is not None
    with patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis):
        dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600, _OWNER_A)
        dom_enqueue_lock.release_dom_enqueue_lock(_PRODUCT, _OWNER_B)
    assert redis._store.get(key) == _OWNER_A


def test_redis_release_correct_token_deletes_lock() -> None:
    dom_enqueue_lock._compare_and_del_script = None
    redis = _redis_mock()
    key = dom_enqueue_lock.product_enqueue_lock_key(_PRODUCT)
    assert key is not None
    with patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis):
        dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600, _OWNER_A)
        dom_enqueue_lock.release_dom_enqueue_lock(_PRODUCT, _OWNER_A)
    assert key not in redis._store


@pytest.mark.asyncio
async def test_db_release_includes_owner_token_filter() -> None:
    session_cm, session = _session_maker_mock()
    with patch(
        "src.jobs.dom_processing_claim.async_session_maker",
        return_value=session_cm,
    ):
        await dom_processing_claim.release_dom_processing_claims_by_products(
            [_PRODUCT], _OWNER_A
        )

    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "dom_processing_owner_token" in str(compiled)
    assert compiled.params["dom_processing_owner_token_1"] == _OWNER_A


@pytest.mark.asyncio
async def test_db_claim_sets_owner_token() -> None:
    session_cm, session = _session_maker_mock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [1]
    session.execute = AsyncMock(return_value=result)
    env = MagicMock(dom_processing_claim_ttl_minutes=15)

    with patch(
        "src.jobs.dom_processing_claim.async_session_maker",
        return_value=session_cm,
    ):
        claimed, skipped = await dom_processing_claim.claim_dom_processing_products(
            [_PRODUCT], env, _OWNER_A
        )

    assert skipped == 0
    assert claimed == [_PRODUCT]
    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "dom_processing_owner_token" in str(compiled)
    assert compiled.params["dom_processing_owner_token"] == _OWNER_A


@pytest.mark.asyncio
async def test_scheduler_uses_one_token_per_batch_when_flag_enabled() -> None:
    env = MagicMock(
        dom_rolling_batch_size=2,
        dom_rolling_fetch_multiplier=3,
        dom_queue_max_pending=1000,
        dom_owner_token_enqueue_enabled=True,
        dom_priority_recovery_limit=20,
        import_chunk_size=1,
        import_download_images=False,
        catalog_dom_enrichment_func=(
            "src.jobs.catalog_import_job.run_catalog_dom_enrichment_chunk"
        ),
        catalog_dom_job_timeout=600,
    )
    products = [
        {"id": 1, "dom_mode": "FULL"},
        {"id": 2, "dom_mode": "LITE"},
    ]
    enqueue_tokens: list[str] = []
    claim_tokens: list[str] = []

    async def fake_claim(reserved, settings, owner_token):
        claim_tokens.append(owner_token)
        return reserved, 0

    def fake_enqueue(claimed, settings, owner_token):
        enqueue_tokens.append(owner_token)
        return len(claimed)

    with (
        patch("src.jobs.dom_scheduler.load_settings", return_value=env),
        patch("src.jobs.dom_scheduler.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_scheduler.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_scheduler._load_scheduler_products",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._load_stock_zero_incomplete",
            new_callable=AsyncMock,
            return_value=products,
        ),
        patch(
            "src.jobs.dom_scheduler._load_priority_recoverable_incomplete",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._split_scheduler_candidates",
            return_value=([], []),
        ),
        patch(
            "src.jobs.dom_scheduler.reserve_products_with_dedup",
            return_value=(products, 0),
        ) as reserve_mock,
        patch(
            "src.jobs.dom_scheduler.claim_dom_processing_products",
            side_effect=fake_claim,
        ),
        patch(
            "src.jobs.dom_scheduler.enqueue_dom_product_chunks",
            side_effect=fake_enqueue,
        ),
        patch(
            "src.jobs.dom_scheduler.uuid.uuid4",
            return_value=MagicMock(hex=_OWNER_A),
        ),
    ):
        result = await dom_scheduler.enqueue_dom_scheduler(env=env)

    assert result["enqueued_jobs"] == 2
    reserve_token = reserve_mock.call_args.args[3]
    assert reserve_token == _OWNER_A
    assert claim_tokens == [_OWNER_A]
    assert enqueue_tokens == [_OWNER_A]


@pytest.mark.asyncio
async def test_scheduler_flag_false_uses_legacy_tokenless_path() -> None:
    env = MagicMock(
        dom_rolling_batch_size=2,
        dom_rolling_fetch_multiplier=3,
        dom_queue_max_pending=1000,
        dom_owner_token_enqueue_enabled=False,
        dom_priority_recovery_limit=20,
        import_chunk_size=1,
        import_download_images=False,
        catalog_dom_enrichment_func="func",
        catalog_dom_job_timeout=600,
    )
    products = [{"id": 1, "dom_mode": "FULL"}]
    enqueue_tokens: list[str | None] = []

    def fake_enqueue(claimed, settings, owner_token=None):
        enqueue_tokens.append(owner_token)
        return len(claimed)

    with (
        patch("src.jobs.dom_scheduler.get_catalog_queue_stats", return_value={}),
        patch("src.jobs.dom_scheduler.dom_queue_overloaded", return_value=False),
        patch(
            "src.jobs.dom_scheduler._load_scheduler_products",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._load_stock_zero_incomplete",
            new_callable=AsyncMock,
            return_value=products,
        ),
        patch(
            "src.jobs.dom_scheduler._load_priority_recoverable_incomplete",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.jobs.dom_scheduler._split_scheduler_candidates",
            return_value=([], []),
        ),
        patch(
            "src.jobs.dom_scheduler.reserve_products_with_dedup",
            return_value=(products, 0),
        ) as reserve_mock,
        patch(
            "src.jobs.dom_scheduler.claim_dom_processing_products",
            new_callable=AsyncMock,
            return_value=(products, 0),
        ) as claim_mock,
        patch(
            "src.jobs.dom_scheduler.enqueue_dom_product_chunks",
            side_effect=fake_enqueue,
        ),
        patch("src.jobs.dom_scheduler.uuid.uuid4") as uuid_mock,
    ):
        await dom_scheduler.enqueue_dom_scheduler(env=env)

    uuid_mock.assert_not_called()
    assert reserve_mock.call_args.args[3] is None
    claim_mock.assert_awaited_once()
    assert claim_mock.await_args.args[2] is None
    assert enqueue_tokens == [None]


def test_enqueue_dom_product_chunks_legacy_two_arg_when_no_token() -> None:
    queue = MagicMock()
    job = MagicMock(id="job-1")
    queue.enqueue.return_value = job
    env = MagicMock(
        import_chunk_size=10,
        import_download_images=True,
        catalog_dom_enrichment_func="func",
        catalog_dom_job_timeout=600,
    )
    products = [{"id": 1}, {"id": 2}]

    with patch(
        "src.jobs.dom_product_payload.get_catalog_dom_queue",
        return_value=queue,
    ):
        jobs = enqueue_dom_product_chunks(products, env)

    assert jobs == 1
    queue.enqueue.assert_called_once_with(
        "func",
        products,
        True,
        job_timeout=600,
    )


def test_enqueue_dom_product_chunks_passes_owner_token_when_set() -> None:
    queue = MagicMock()
    job = MagicMock(id="job-1")
    queue.enqueue.return_value = job
    env = MagicMock(
        import_chunk_size=10,
        import_download_images=True,
        catalog_dom_enrichment_func="func",
        catalog_dom_job_timeout=600,
    )
    products = [{"id": 1}, {"id": 2}]

    with patch(
        "src.jobs.dom_product_payload.get_catalog_dom_queue",
        return_value=queue,
    ):
        jobs = enqueue_dom_product_chunks(products, env, _OWNER_A)

    assert jobs == 1
    queue.enqueue.assert_called_once_with(
        "func",
        products,
        True,
        _OWNER_A,
        job_timeout=600,
    )


def test_legacy_redis_acquire_uses_placeholder_value() -> None:
    dom_enqueue_lock._compare_and_del_script = None
    redis = _redis_mock()
    key = dom_enqueue_lock.product_enqueue_lock_key(_PRODUCT)
    with patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis):
        assert dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600)
    assert redis._store[key] == "1"


@pytest.mark.asyncio
async def test_legacy_db_claim_sets_null_owner_token() -> None:
    session_cm, session = _session_maker_mock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [1]
    session.execute = AsyncMock(return_value=result)
    env = MagicMock(dom_processing_claim_ttl_minutes=15)

    with patch(
        "src.jobs.dom_processing_claim.async_session_maker",
        return_value=session_cm,
    ):
        claimed, skipped = await dom_processing_claim.claim_dom_processing_products(
            [_PRODUCT], env
        )

    assert skipped == 0
    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert compiled.params["dom_processing_owner_token"] is None


def test_tokenless_release_deletes_lock() -> None:
    redis = _redis_mock()
    key = dom_enqueue_lock.product_enqueue_lock_key(_PRODUCT)
    with patch("src.jobs.dom_enqueue_lock.sync_redis", return_value=redis):
        dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600, _OWNER_A)
        dom_enqueue_lock.release_dom_enqueue_lock(_PRODUCT)
    assert key not in redis._store
