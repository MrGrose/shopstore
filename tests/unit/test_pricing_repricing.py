from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.models.pricing import MarginRule, PricingRecalculationJob, PricingSettings
from src.models.product import Product
from src.repositories.pricing_repo import PricingRepository
from src.services.pricing.repricing import (
    _job_versions_match,
    _process_products,
    enqueue_repricing_job,
    run_repricing_job,
)
from src.services.pricing.service import PricingService


# Собирает правило для SQL и version-тестов.
def _rule(slug: str = "balls", active: bool = True) -> MarginRule:
    return MarginRule(
        id=7,
        sport_type="Padel",
        subcategory_slug=slug,
        margin_percent=30,
        is_active=active,
        updated_at=datetime(2026, 7, 14, 12, 0, 0),
    )


# Финальный exact query содержит все storefront visibility ограничения.
def test_repricing_filters_hidden_inactive_and_out_of_stock_products() -> None:
    rule = _rule()
    filters = PricingRepository._group_filters(rule, [rule], storefront_only=True)
    statement = select(Product.id).where(*filters)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "products.is_active IS true" in sql
    assert "products.catalog_in_stock IS true" in sql
    assert "storefront_mapping_releases.status = 'active'" in sql
    assert "product_storefront_placements" in sql
    assert "NOT (EXISTS" in sql
    assert "catalog_hidden_brands" in sql
    assert "products.category_l2 IN ('Padel balls', 'Giant balls')" in sql


# Изменение версии правила делает старый job устаревшим.
def test_job_version_change_is_superseded() -> None:
    rule = _rule()
    settings = PricingSettings(
        updated_at=datetime(2026, 7, 14, 11, 0, 0),
    )
    job = PricingRecalculationJob(
        rule_version=rule.updated_at,
        settings_version=settings.updated_at,
        margin_percent=rule.margin_percent,
    )

    assert _job_versions_match(job, rule, settings) is True
    rule.updated_at = datetime(2026, 7, 14, 12, 1, 0)
    assert _job_versions_match(job, rule, settings) is False


class _NestedTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class _SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


# Ошибка одного товара сохраняется и не останавливает остальные товары batch.
@pytest.mark.asyncio
async def test_product_error_does_not_stop_repricing_batch() -> None:
    session = SimpleNamespace(
        begin_nested=lambda: _NestedTransaction(),
        flush=AsyncMock(),
    )
    repo = SimpleNamespace(save_recalculation_error=AsyncMock())
    service = Mock()
    service.verify_loaded_storefront_price.side_effect = [True, ValueError("bad"), True]
    job = PricingRecalculationJob(
        id=5,
        rule_version=datetime(2026, 7, 14, 12, 0, 0),
    )
    products = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]

    updated, errors = await _process_products(
        session,
        repo,
        service,
        job,
        object(),
        [],
        products,
    )

    assert updated == 2
    assert errors == 1
    repo.save_recalculation_error.assert_awaited_once_with(5, 2, "bad")


# RQ получает retry-настройки для временных ошибок worker.
def test_enqueue_repricing_job_configures_retry() -> None:
    queue = Mock()
    queue.enqueue.return_value = SimpleNamespace(id="rq-17")

    with patch("src.services.pricing.repricing.get_pricing_queue", return_value=queue):
        assert enqueue_repricing_job(17) == "rq-17"

    retry = queue.enqueue.call_args.kwargs["retry"]
    assert retry.max == 3
    assert retry.intervals == [30, 120, 300]


# Повторный запуск продолжает с cursor и фиксирует каждый завершённый batch.
@pytest.mark.asyncio
async def test_repricing_retry_resumes_from_cursor_and_commits_batch() -> None:
    version = datetime(2026, 7, 14, 12, 0, 0)
    rule = _rule()
    settings = PricingSettings(updated_at=version)
    job = PricingRecalculationJob(
        id=17,
        margin_rule_id=rule.id,
        status="queued",
        margin_percent=rule.margin_percent,
        rule_version=version,
        settings_version=version,
        total_count=6,
        processed_count=4,
        updated_count=1,
        error_count=0,
        cursor_product_id=10,
    )
    products = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
    session = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        flush=AsyncMock(),
        begin_nested=lambda: _NestedTransaction(),
    )
    repo = SimpleNamespace(
        get_recalculation_job=AsyncMock(return_value=job),
        get_settings_for_update=AsyncMock(return_value=settings),
        get_margin_rules_for_update=AsyncMock(return_value=[rule]),
        load_repricing_batch=AsyncMock(side_effect=[products, []]),
        save_recalculation_error=AsyncMock(),
    )
    service = MagicMock()
    service.verify_loaded_storefront_price.side_effect = [True, False]

    with (
        patch(
            "src.services.pricing.repricing.async_session_maker",
            return_value=_SessionContext(session),
        ),
        patch("src.services.pricing.repricing.PricingRepository", return_value=repo),
        patch("src.services.pricing.repricing.PricingService", return_value=service),
        patch("src.services.pricing.repricing.invalidate_catalog_read_caches"),
    ):
        result = await run_repricing_job(job.id, batch_size=1000)

    assert result == "succeeded"
    assert repo.load_repricing_batch.await_args_list[0].args[2] == 10
    assert repo.load_repricing_batch.await_args_list[1].args[2] == 12
    assert job.processed_count == 6
    assert job.updated_count == 2
    assert job.cursor_product_id == 12
    assert session.commit.await_count == 3


# Ошибка Redis не оставляет созданный DB job навсегда в queued.
@pytest.mark.asyncio
async def test_enqueue_failure_marks_pricing_job_failed() -> None:
    rule = _rule()
    settings = PricingSettings(updated_at=rule.updated_at)
    job = PricingRecalculationJob(id=18, status="queued")
    service = PricingService(AsyncMock())
    service.get_settings = AsyncMock(return_value=settings)
    service.repo = SimpleNamespace(
        get_margin_rules=AsyncMock(return_value=[rule]),
        count_group_products=AsyncMock(return_value=32),
        create_recalculation_job=AsyncMock(return_value=job),
        mark_recalculation_enqueue_failed=AsyncMock(),
        set_recalculation_rq_job_id=AsyncMock(),
    )

    with patch(
        "src.services.pricing.repricing.enqueue_repricing_job",
        side_effect=ConnectionError("redis unavailable"),
    ):
        with pytest.raises(ValueError, match="очередь Redis"):
            await service.enqueue_margin_rule_recalculation(rule)

    message = service.repo.mark_recalculation_enqueue_failed.await_args.args[1]
    assert "redis unavailable" in message
    service.repo.set_recalculation_rq_job_id.assert_not_awaited()


# Repository сохраняет терминальный статус и время ошибки enqueue.
@pytest.mark.asyncio
async def test_mark_recalculation_enqueue_failed_sets_terminal_state() -> None:
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())
    repo = PricingRepository(session)
    job = PricingRecalculationJob(status="queued")

    await repo.mark_recalculation_enqueue_failed(job, "redis unavailable")

    assert job.status == "failed"
    assert job.error_message == "redis unavailable"
    assert job.finished_at is not None
    session.commit.assert_awaited_once()
