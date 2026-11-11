from src.repositories.product_repo import aggregate_product_color_facet_counts


def test_duplicate_product_variant_and_feature_same_color_counts_once() -> None:
    rows = [
        (1, "black"),  # variant
        (1, "black"),  # feature
    ]
    assert aggregate_product_color_facet_counts(rows) == {"black": 1}


def test_multiple_products_distinct_count() -> None:
    rows = [
        (1, "black"),  # variant only
        (2, "black"),  # feature only
        (3, "black"),  # variant + feature (deduped below)
        (3, "black"),
    ]
    assert aggregate_product_color_facet_counts(rows) == {"black": 3}


def test_compound_colors_remain_separate_values() -> None:
    rows = [
        (1, "black"),
        (1, "black, black"),
        (2, "black, white"),
        (3, "black"),
        (3, "black, black"),
    ]
    assert aggregate_product_color_facet_counts(rows) == {
        "black": 2,
        "black, black": 2,
        "black, white": 1,
    }


def test_filter_count_parity_semantics_single_key() -> None:
    """One product_id per color key even when listed in both sources."""
    variant_rows = [(1, "black"), (2, "black"), (3, "black")]
    feature_rows = [(1, "black"), (2, "black"), (3, "black")]
    merged = aggregate_product_color_facet_counts([*variant_rows, *feature_rows])
    assert merged["black"] == 3


def test_black_and_black_black_are_not_merged() -> None:
    rows = [
        (10, "black"),
        (11, "black, black"),
    ]
    counts = aggregate_product_color_facet_counts(rows)
    assert counts == {"black": 1, "black, black": 1}
