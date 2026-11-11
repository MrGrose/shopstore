import json

from src.services.catalog.shoe_size_guide import (
    DEFAULT_JSON_PATH,
    brand_has_size_chart,
    eu_allowed_for_audience,
    format_cm_ru,
    get_brand_size_chart,
    normalize_brand,
    normalize_eu_simple,
    parse_eu_span,
)


def test_normalize_brand_lowercase() -> None:
    assert normalize_brand("  Nike  ") == "nike"


def test_normalize_eu_simple() -> None:
    assert normalize_eu_simple("42,5") == "42.5"


def test_format_cm_ru() -> None:
    assert format_cm_ru(26.0) == "26"
    assert format_cm_ru(26.5) == "26,5"


def test_get_brand_size_chart_nike() -> None:
    chart = get_brand_size_chart("Nike")
    assert chart is not None
    assert chart["brand"] == "Nike"
    assert "men" in chart["audiences"]
    assert chart["sections"]["men"]


def test_brand_has_size_chart_unknown() -> None:
    assert brand_has_size_chart("___no_such_brand___") is False


def test_parse_eu_span_formats() -> None:
    assert parse_eu_span("42.5") == (42.5, 42.5)
    assert parse_eu_span("17-18") == (17.0, 18.0)
    low, high = parse_eu_span("36 2/3") or (0.0, 0.0)
    assert low == high
    assert abs(low - (36 + 2 / 3)) < 1e-9


def test_json_rows_respect_audience_eu_range() -> None:
    payload = json.loads(DEFAULT_JSON_PATH.read_text(encoding="utf-8"))
    bad = [
        (row["brand"], row["audience"], row["eu"])
        for row in payload
        if not eu_allowed_for_audience(str(row["audience"]), str(row["eu"]))
    ]
    assert bad == []


def test_bullpadel_audience_ranges() -> None:
    chart = get_brand_size_chart("Bullpadel")
    assert chart is not None
    kids_eu = [float(row["eu"]) for row in chart["sections"]["kids"]]
    men_eu = [float(row["eu"]) for row in chart["sections"]["men"]]
    women_eu = [float(row["eu"]) for row in chart["sections"]["women"]]
    assert max(kids_eu) <= 40
    assert min(men_eu) >= 36
    assert min(women_eu) >= 34
    assert max(women_eu) <= 43.5
    men_48 = [row for row in chart["sections"]["men"] if row["eu"] == "48"]
    assert men_48
    assert men_48[0]["foot_length_cm"] == 30.0
    women_us = {row["eu"]: row["us"] for row in chart["sections"]["women"]}
    men_us = {row["eu"]: row["us"] for row in chart["sections"]["men"]}
    assert women_us["39"] != men_us["39"]
    assert women_us["39"] == "8"


def test_endless_has_women_chart() -> None:
    assert brand_has_size_chart("Endless") is True
    chart = get_brand_size_chart("Endless")
    assert chart is not None
    assert "women" in chart["audiences"]
    women_eu = [float(row["eu"]) for row in chart["sections"]["women"]]
    assert min(women_eu) >= 34
    assert max(women_eu) <= 43.5
