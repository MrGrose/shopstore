from src.services.catalog.read.scope import (
    build_facet_filters_excluding,
    join_facet_list_param,
    parse_facet_list_param,
)


def test_brand_options_exclude_brand_keep_gender_color_size():
    brands = parse_facet_list_param("Nike,Adidas")
    genders = parse_facet_list_param("Мужской")
    colors = parse_facet_list_param("Чёрный")
    sizes = parse_facet_list_param("L")

    out = build_facet_filters_excluding(brands, genders, colors, sizes, "brand")
    assert out == (None, genders, colors, sizes)


def test_gender_options_exclude_gender_keep_brand():
    brands = parse_facet_list_param("Nike,Adidas")
    genders = parse_facet_list_param("Мужской")

    out = build_facet_filters_excluding(brands, genders, None, None, "gender")
    assert out == (brands, None, None, None)


def test_color_size_counts_scenario_brand_plus_gender():
    """brand=Nike,Adidas + gender=Мужской → color/size запросы включают brand+gender."""
    brands = parse_facet_list_param(join_facet_list_param(["Nike", "Adidas"]))
    genders = parse_facet_list_param("Мужской")

    color_filters = build_facet_filters_excluding(brands, genders, None, None, "color")
    size_filters = build_facet_filters_excluding(brands, genders, None, None, "size")

    assert color_filters[0] == brands
    assert color_filters[1] == genders
    assert color_filters[2] is None
    assert size_filters[0] == brands
    assert size_filters[1] == genders
    assert size_filters[3] is None


def test_brand_options_unchanged_when_only_brand_selection_changes():
    """Self-filter excluded: смена выбранных brand не меняет query для списка brand."""
    before = build_facet_filters_excluding(
        parse_facet_list_param("Nike"),
        None,
        None,
        None,
        "brand",
    )
    after = build_facet_filters_excluding(
        parse_facet_list_param("Nike,Adidas"),
        None,
        None,
        None,
        "brand",
    )
    assert before == after == (None, None, None, None)
