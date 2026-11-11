from src.services.catalog.read.scope import (
    join_facet_list_param,
    merge_facet_list_param,
    normalize_facet_list_for_cache,
    parse_facet_list_param,
    parse_facet_query_param,
)


def test_parse_single_brand_backward_compat():
    assert parse_facet_list_param("Nike") == ["Nike"]


def test_parse_comma_separated_dedupes():
    assert parse_facet_list_param("Nike, Adidas ,Nike") == ["Nike", "Adidas"]


def test_parse_decimal_size_single_value():
    assert parse_facet_list_param("1,18") == ["1,18"]
    assert parse_facet_list_param("1,05") == ["1,05"]
    assert parse_facet_query_param(["1,18"]) == ["1,18"]


def test_parse_multi_sizes_with_pipe():
    assert parse_facet_list_param("1,18|1,05") == ["1,18", "1,05"]
    assert join_facet_list_param(["1,18", "1,05"]) == "1,18|1,05"


def test_parse_repeated_query_values():
    assert parse_facet_query_param(["Nike", "Adidas"]) == ["Nike", "Adidas"]


def test_parse_mixed_comma_and_repeated():
    assert parse_facet_query_param(["Nike,Adidas", "Bullpadel"]) == [
        "Nike",
        "Adidas",
        "Bullpadel",
    ]


def test_parse_empty_values_ignored():
    assert parse_facet_query_param(["", "  ", "Nike", ""]) == ["Nike"]
    assert parse_facet_list_param("") is None
    assert parse_facet_list_param("  ,  , ") is None
    assert parse_facet_query_param(None) is None
    assert parse_facet_query_param([]) is None


def test_parse_duplicates_deduped():
    assert parse_facet_query_param(["Nike", "Adidas", "Nike"]) == ["Nike", "Adidas"]
    assert parse_facet_query_param(["Nike,Adidas", "Adidas"]) == ["Nike", "Adidas"]


def test_merge_repeated_query_values():
    assert merge_facet_list_param("Nike", ["Adidas", "Nike"]) == ["Nike", "Adidas"]


def test_normalize_sorts_for_cache():
    values = normalize_facet_list_for_cache(["Adidas", "Nike", "Nike"])
    assert values == ["Adidas", "Nike"]


def test_cache_key_equivalent_formats():
    comma = normalize_facet_list_for_cache(parse_facet_list_param("Nike,Adidas"))
    pipe = normalize_facet_list_for_cache(parse_facet_list_param("Nike|Adidas"))
    reversed_comma = normalize_facet_list_for_cache(
        parse_facet_list_param("Adidas,Nike")
    )
    repeated = normalize_facet_list_for_cache(
        parse_facet_query_param(["Nike", "Adidas"])
    )
    mixed = normalize_facet_list_for_cache(
        parse_facet_query_param(["Nike,Adidas", "Bullpadel", "Bullpadel"])
    )
    size_repeated = normalize_facet_list_for_cache(
        parse_facet_query_param(["1,18", "1,05"])
    )

    assert comma == ["Adidas", "Nike"]
    assert pipe == comma
    assert reversed_comma == comma
    assert repeated == comma
    assert mixed == ["Adidas", "Bullpadel", "Nike"]
    assert size_repeated == ["1,05", "1,18"]


def test_join_roundtrip():
    joined = join_facet_list_param(["Nike", "Adidas"])
    assert joined == "Nike|Adidas"
    assert parse_facet_list_param(joined) == ["Nike", "Adidas"]
    assert parse_facet_list_param(join_facet_list_param(["1,18"])) == ["1,18"]


def test_parse_color_compound_value_opaque():
    assert parse_facet_list_param("black, black", facet_key="color") == ["black, black"]


def test_parse_color_multi_pipe():
    assert parse_facet_list_param("Black|Blue", facet_key="color") == [
        "Black",
        "Blue",
    ]


def test_parse_facet_query_param_color_compound():
    assert parse_facet_query_param(["black, black"], facet_key="color") == [
        "black, black"
    ]
