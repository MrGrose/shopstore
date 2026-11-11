import logging
from unittest.mock import patch

from src.services.catalog.read.caches import invalidate_catalog_read_caches


@patch(
    "src.services.catalog.read.caches.invalidate_catalog_version",
    return_value=7,
)
def test_invalidate_catalog_read_caches_increments_version(
    mock_invalidate_version,
    caplog,
):
    caplog.set_level(logging.INFO)

    result = invalidate_catalog_read_caches(reason="test_reason")

    mock_invalidate_version.assert_called_once_with()
    assert result == {
        "catalog_version": 7,
        "facets": 0,
        "count": 0,
        "subcategories": 0,
    }
    message = caplog.records[-1].getMessage()
    assert "catalog_cache_invalidate" in message
    assert "catalog_version=7" in message
    assert "duration_ms=" in message
    assert "reason=test_reason" in message
    assert "caller=" in message


@patch(
    "src.services.catalog.read.caches.invalidate_catalog_version",
    return_value=3,
)
def test_invalidate_catalog_read_caches_selective_flags_still_increment(
    mock_invalidate_version,
    caplog,
):
    caplog.set_level(logging.INFO)

    result = invalidate_catalog_read_caches(
        facets=False,
        count=True,
        subcategories=False,
        reason="count_only",
    )

    mock_invalidate_version.assert_called_once_with()
    assert result["catalog_version"] == 3
    message = caplog.records[-1].getMessage()
    assert "catalog_version=3" in message
    assert "reason=count_only" in message


def test_invalidate_catalog_read_caches_skipped_when_all_false(caplog):
    caplog.set_level(logging.INFO)

    with patch(
        "src.services.catalog.read.caches.invalidate_catalog_version"
    ) as mock_invalidate_version:
        result = invalidate_catalog_read_caches(
            facets=False,
            count=False,
            subcategories=False,
            reason="noop",
        )

    mock_invalidate_version.assert_not_called()
    assert result["catalog_version"] == 0
    message = caplog.records[-1].getMessage()
    assert "skipped=all" in message
