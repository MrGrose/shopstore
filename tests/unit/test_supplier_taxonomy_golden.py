import json
from pathlib import Path

import pytest

from src.services.catalog.categories.pipeline import (
    resolve_catalog_fields_from_supplier_snapshot,
)
from src.utils.labels import translate_category_l2

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures/supplier_taxonomy_golden.json"
)

_CATALOG_KEYS = (
    "sport_type",
    "category_l1",
    "category_l2",
    "category_l3",
    "trade_group",
)


def _golden_cases() -> list[tuple[str, dict, dict, str | None, str | None]]:
    if not _FIXTURE_PATH.is_file():
        return []
    rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    cases: list[tuple[str, dict, dict, str | None, str | None]] = []
    for row in rows:
        snapshot = row.get("snapshot")
        expected = row.get("expected")
        if not snapshot or not expected:
            continue
        cases.append(
            (
                str(row.get("id") or "?"),
                snapshot,
                expected,
                row.get("title"),
                row.get("gender"),
            )
        )
    return cases


_GOLDEN_CASES = _golden_cases()


@pytest.mark.parametrize(
    ("case_id", "snapshot", "expected", "title", "gender"),
    _GOLDEN_CASES,
    ids=[case[0] for case in _GOLDEN_CASES],
)
def test_supplier_taxonomy_golden(
    case_id: str,
    snapshot: dict,
    expected: dict,
    title: str | None,
    gender: str | None,
) -> None:
    if not _GOLDEN_CASES:
        pytest.skip(f"fixture missing: {_FIXTURE_PATH}")
    got = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title=title,
        gender=gender,
    )
    mismatches = {
        key: {"expected": expected.get(key), "got": got.get(key)}
        for key in _CATALOG_KEYS
        if (got.get(key) or None) != (expected.get(key) or None)
    }
    assert not mismatches, f"{case_id}: {mismatches}"


def test_supplier_taxonomy_tshirt_storefront_label() -> None:
    if not _GOLDEN_CASES:
        pytest.skip(f"fixture missing: {_FIXTURE_PATH}")
    row = next(case for case in _GOLDEN_CASES if case[0] == "padel-tshirt")
    got = resolve_catalog_fields_from_supplier_snapshot(
        row[1],
        title=row[3],
        gender=row[4],
    )
    assert translate_category_l2(got["category_l2"]) == "Футболки и топы"
