from unittest.mock import MagicMock, patch

import pytest

from src.jobs.orders.supplier_availability_scheduler import main


def test_main_enqueues_requested_order(capsys: pytest.CaptureFixture[str]) -> None:
    job = MagicMock(id="supplier-availability-123")
    with patch(
        "src.jobs.orders.supplier_availability_scheduler.enqueue_supplier_availability",
        return_value=job,
    ) as enqueue:
        result = main(["--order-id", "123"])

    assert result == 0
    enqueue.assert_called_once_with(123)
    assert capsys.readouterr().out.strip() == "Enqueued supplier-availability-123"


def test_main_reports_disabled_kill_switch() -> None:
    with (
        patch(
            "src.jobs.orders.supplier_availability_scheduler."
            "enqueue_supplier_availability",
            return_value=None,
        ),
        pytest.raises(SystemExit, match="2"),
    ):
        main(["--order-id", "123"])
