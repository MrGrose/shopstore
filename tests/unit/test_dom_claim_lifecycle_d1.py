from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs import catalog_import_job

_CHUNK = [{"id": 1, "product_url": "https://example.com/p", "title": "Test"}]
_ENRICHED_CHUNK = [{**_CHUNK[0], "import_source": "dom"}]
_METRICS = {"total": 1, "success": 1, "failed": 0, "failed_products": []}
_IMPORT_RESULT = {
    "created": 0,
    "updated": 1,
    "skipped": 0,
    "deactivated": 0,
    "stock_boundary_flipped_ids": [],
}


def _dom_patches():
    session = MagicMock()
    session.ctx = MagicMock()
    session.close = AsyncMock()
    session.telemetry.log_dom_chunk = MagicMock()
    session.throttle = None
    return {
        "open_dom_chunk": patch(
            "src.scraper.dom_session.open_dom_chunk",
            new_callable=AsyncMock,
            return_value=session,
        ),
        "enrich": patch(
            "src.scraper.enrichment.product_dom.enrich_products_with_dom",
            new_callable=AsyncMock,
            return_value=dict(_METRICS),
        ),
        "record_dom_status": patch(
            "src.jobs.catalog_import_job.record_dom_status",
            new_callable=AsyncMock,
        ),
        "release_redis": patch(
            "src.jobs.catalog_import_job.release_dom_enqueue_locks",
        ),
        "release_db": patch(
            "src.jobs.catalog_import_job.release_dom_processing_claims_by_products",
            new_callable=AsyncMock,
        ),
        "filter_held": patch(
            "src.jobs.catalog_import_job.filter_held_dom_processing_products",
            new_callable=AsyncMock,
            side_effect=lambda products, owner_token=None: products,
        ),
        "invalidate_boundary": patch(
            "src.jobs.catalog_import_job._invalidate_dom_import_stock_boundary",
        ),
        "load_settings": patch("src.scraper.config.settings.load_settings"),
        "recovery_proxy": patch(
            "src.scraper.infrastructure.browser_manager.build_recovery_proxy_pool",
            return_value=None,
        ),
    }


def _start_patches(patches: dict) -> dict[str, MagicMock]:
    started = {name: p.start() for name, p in patches.items()}
    started["load_settings"].return_value = MagicMock(headless=True)
    return started


def _stop_patches(patches: dict) -> None:
    for p in patches.values():
        p.stop()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_success_releases_after_import_products(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["enrich"].return_value = dict(_METRICS)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    svc.import_products = AsyncMock(return_value=dict(_IMPORT_RESULT))
    call_order: list[str] = []

    async def track_import(*args, **kwargs):
        call_order.append("import_products")
        return dict(_IMPORT_RESULT)

    svc.import_products.side_effect = track_import

    def track_release_redis(chunk, owner_token=None):
        call_order.append("release_redis")

    def track_release_db(chunk, owner_token=None):
        call_order.append("release_db")

    mocks["release_redis"].side_effect = track_release_redis
    mocks["release_db"].side_effect = track_release_db

    async def track_status(*args, **kwargs):
        call_order.append("record_dom_status")

    mocks["record_dom_status"].side_effect = track_status

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        chunk = list(_ENRICHED_CHUNK)
        result = catalog_import_job.run_catalog_dom_enrichment_chunk(chunk)

    _stop_patches(patches)

    assert result["updated"] == 1
    assert call_order.index("import_products") < call_order.index("release_redis")
    assert call_order.index("record_dom_status") < call_order.index("import_products")
    mocks["release_redis"].assert_called_once_with(chunk, None)
    mocks["release_db"].assert_called_once_with(chunk, None)


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_dom_enrich_failure_releases_once(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["enrich"].side_effect = RuntimeError("dom failed")

    with pytest.raises(RuntimeError, match="dom failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()
    mocks["record_dom_status"].assert_not_called()
    mock_session_maker.assert_not_called()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_record_dom_status_failure_releases_once(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["record_dom_status"].side_effect = RuntimeError("status failed")

    with pytest.raises(RuntimeError, match="status failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_ENRICHED_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()
    mock_session_maker.assert_not_called()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_import_products_failure_releases_once(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    svc.import_products = AsyncMock(side_effect=RuntimeError("import failed"))

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        with pytest.raises(RuntimeError, match="import failed"):
            catalog_import_job.run_catalog_dom_enrichment_chunk(list(_ENRICHED_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_empty_enriched_products_releases_after_status(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    call_order: list[str] = []

    async def track_status(*args, **kwargs):
        call_order.append("record_dom_status")

    mocks["record_dom_status"].side_effect = track_status

    def append_release_redis(chunk, owner_token=None):
        call_order.append("release_redis")

    mocks["release_redis"].side_effect = append_release_redis
    mocks["release_db"].side_effect = AsyncMock(
        side_effect=lambda chunk, owner_token=None: call_order.append("release_db")
    )

    result = catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    assert result["updated"] == 0
    assert call_order == ["record_dom_status", "release_redis", "release_db"]
    mocks["record_dom_status"].assert_called_once()
    mock_session_maker.assert_not_called()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_no_double_release(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    svc.import_products = AsyncMock(return_value=dict(_IMPORT_RESULT))

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_ENRICHED_CHUNK))

    _stop_patches(patches)

    assert mocks["release_redis"].call_count == 1
    assert mocks["release_db"].call_count == 1


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_release_not_called_before_import_starts(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    release_before_import = False

    async def track_import(*args, **kwargs):
        if mocks["release_redis"].called or mocks["release_db"].called:
            nonlocal release_before_import
            release_before_import = True
        return dict(_IMPORT_RESULT)

    svc.import_products.side_effect = track_import

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_ENRICHED_CHUNK))

    _stop_patches(patches)

    assert not release_before_import
    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


def test_session_open_failure_still_releases_once() -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["open_dom_chunk"].side_effect = RuntimeError("session open failed")

    with pytest.raises(RuntimeError, match="session open failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()
    mocks["enrich"].assert_not_called()


def test_redis_release_failure_still_releases_db() -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["release_redis"].side_effect = RuntimeError("redis release failed")

    with pytest.raises(RuntimeError, match="redis release failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


def test_db_release_failure_still_releases_redis() -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["release_db"].side_effect = RuntimeError("db release failed")

    with pytest.raises(RuntimeError, match="db release failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_release_failure_does_not_mask_job_exception(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    mocks["enrich"].side_effect = RuntimeError("dom failed")
    mocks["release_redis"].side_effect = RuntimeError("redis release failed")

    with pytest.raises(RuntimeError, match="dom failed"):
        catalog_import_job.run_catalog_dom_enrichment_chunk(list(_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_success_body_release_failure_raises(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    svc.import_products = AsyncMock(return_value=dict(_IMPORT_RESULT))
    mocks["release_db"].side_effect = RuntimeError("db release failed")

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        with pytest.raises(RuntimeError, match="db release failed"):
            catalog_import_job.run_catalog_dom_enrichment_chunk(list(_ENRICHED_CHUNK))

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once()
    mocks["release_db"].assert_called_once()


@patch("src.jobs.catalog_import_job.async_session_maker")
def test_release_passes_owner_token(mock_session_maker) -> None:
    patches = _dom_patches()
    mocks = _start_patches(patches)
    session = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = session
    svc = MagicMock()
    svc.import_products = AsyncMock(return_value=dict(_IMPORT_RESULT))
    owner_token = "owner-token-abc"

    with patch(
        "src.jobs.catalog_import_job.ProductImportService",
        return_value=svc,
    ):
        catalog_import_job.run_catalog_dom_enrichment_chunk(
            list(_ENRICHED_CHUNK),
            owner_token=owner_token,
        )

    _stop_patches(patches)

    mocks["release_redis"].assert_called_once_with(list(_ENRICHED_CHUNK), owner_token)
    mocks["release_db"].assert_called_once_with(list(_ENRICHED_CHUNK), owner_token)
