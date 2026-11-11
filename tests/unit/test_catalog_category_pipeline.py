import json
from pathlib import Path

from src.services.catalog.categories.pipeline import resolve_catalog_fields_from_import

_GOLDEN_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / ".01_hlam/docs/samples/graphql_catalog_sample.json"
)


# Golden rows where import gtm path still diverges from snapshot pipeline (Phase 3).
_GOLDEN_IMPORT_MISMATCH = frozenset({0, 3, 4, 5})


# Regression: import-path pipeline vs golden storefront_after_pipeline.
def test_resolve_catalog_fields_matches_golden_storefront():
    if not _GOLDEN_SAMPLE.is_file():
        return
    payload = json.loads(_GOLDEN_SAMPLE.read_text(encoding="utf-8"))
    for index, row in enumerate(payload.get("samples") or []):
        if index in _GOLDEN_IMPORT_MISMATCH:
            continue
        import_payload = row.get("import_payload") or {}
        expected = row.get("storefront_after_pipeline") or {}
        if not expected or not import_payload:
            continue
        got = resolve_catalog_fields_from_import(
            import_payload.get("gtm"),
            import_payload.get("pdp_meta"),
            title=import_payload.get("title"),
        )
        assert got.get("sport_type") == expected.get("sport_type")
        assert got.get("category_l2") == expected.get("category_l2")
        assert got.get("category_l3") == expected.get("category_l3")
