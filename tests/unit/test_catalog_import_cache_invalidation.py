from unittest.mock import patch

from src.jobs import catalog_import_job


@patch("src.jobs.catalog_import_job.invalidate_if_catalog_boundary_changed")
@patch("src.jobs.catalog_import_job._run_import")
def test_graphql_import_chunk_does_not_invalidate_on_stock_boundary(
    mock_run_import,
    mock_boundary_invalidate,
) -> None:
    mock_run_import.return_value = {
        "created": 0,
        "updated": 1,
        "skipped": 0,
        "deactivated": 0,
        "stock_boundary_flipped_ids": [42],
    }

    result = catalog_import_job.run_catalog_import_chunk([{"title": "x"}])

    assert result["updated"] == 1
    mock_boundary_invalidate.assert_not_called()


@patch("src.jobs.catalog_import_job.invalidate_if_catalog_boundary_changed")
def test_dom_import_stock_boundary_helper(mock_boundary_invalidate) -> None:
    catalog_import_job._invalidate_dom_import_stock_boundary(
        {"stock_boundary_flipped_ids": [7]}
    )
    mock_boundary_invalidate.assert_called_once_with([7], reason="dom_stock_boundary")
