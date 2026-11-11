import json
from pathlib import Path

import pytest

from src.services.catalog.categories.pipeline import (
    resolve_catalog_fields_from_supplier_snapshot,
)

_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2]
    / ".01_hlam/docs/samples/graphql_catalog_sample.json"
)

_CATALOG_KEYS = (
    "sport_type",
    "category_l1",
    "category_l2",
    "category_l3",
    "trade_group",
)


def _golden_cases() -> list[tuple[str, dict, dict, str | None, str | None]]:
    if not _GOLDEN_PATH.is_file():
        return []
    payload = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    cases: list[tuple[str, dict, dict, str | None, str | None]] = []
    for row in payload.get("samples") or []:
        snapshot = row.get("supplier_snapshot_for_db")
        expected = row.get("storefront_after_pipeline") or {}
        import_payload = row.get("import_payload") or {}
        if not snapshot or not expected:
            continue
        item_id = import_payload.get("item_id") or row.get("graphql_raw_node", {}).get(
            "handle"
        )
        title = import_payload.get("title")
        gender = (import_payload.get("pdp_meta") or {}).get("gender")
        cases.append((str(item_id or "?"), snapshot, expected, title, gender))
    return cases


_GOLDEN_CASES = _golden_cases()


@pytest.mark.parametrize(
    ("item_id", "snapshot", "expected", "title", "gender"),
    _GOLDEN_CASES,
    ids=[case[0] for case in _GOLDEN_CASES],
)
def test_pipeline_matches_golden_sample(
    item_id: str,
    snapshot: dict,
    expected: dict,
    title: str | None,
    gender: str | None,
) -> None:
    if not _GOLDEN_CASES:
        pytest.skip(f"golden sample missing or empty: {_GOLDEN_PATH}")
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
    assert not mismatches, f"{item_id}: {mismatches}"
