from src.services.catalog.display.reconciler import CoverageReport


def test_blocks_activation_on_missing_resolution_integrity() -> None:
    report = CoverageReport(
        invalid_taxonomy=0,
        unexpected_unmapped=0,
        mapping_error=0,
        mapped=1,
        excluded=0,
        integrity_failures={"missing_resolution": 3},
    )
    assert report.blocks_activation is True


def test_blocks_activation_on_missing_placement_integrity() -> None:
    report = CoverageReport(
        invalid_taxonomy=0,
        unexpected_unmapped=0,
        mapping_error=0,
        mapped=1,
        excluded=0,
        integrity_failures={"missing_placement": 2},
    )
    assert report.blocks_activation is True
