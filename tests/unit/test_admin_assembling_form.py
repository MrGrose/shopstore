from pathlib import Path


def test_orders_page_passes_start_assembling_flag_to_detail() -> None:
    template = (
        Path(__file__).resolve().parents[2] / "src/templates/site/admin/orders.html"
    ).read_text(encoding="utf-8")

    assert "start_assembling_allowed=detail.start_assembling_allowed" in template
