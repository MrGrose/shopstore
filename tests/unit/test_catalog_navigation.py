from src.services.catalog.display.navigation import (
    _build_breadcrumbs,
    _url_params_for_scope,
)


def test_url_params_for_scope_mapping_keys() -> None:
    assert _url_params_for_scope(
        use_mapping_params=True,
        sub="rackets",
        category_type="pro",
    ) == {"section": "rackets", "node": "pro"}


def test_url_params_for_scope_legacy_keys() -> None:
    assert _url_params_for_scope(
        use_mapping_params=False,
        sub="rackets",
        category_type="pro",
    ) == {"sub": "rackets", "category_type": "pro"}


def test_build_breadcrumbs_sport_section_type() -> None:
    crumbs = _build_breadcrumbs(
        sport_type="Padel",
        sub="rackets",
        category_type="pro",
        use_mapping_params=True,
        section_label="Ракетки",
        type_label="Pro",
    )
    assert [item.label for item in crumbs] == ["Падел", "Ракетки", "Pro"]
    assert crumbs[1].url_params == {"section": "rackets"}
    assert crumbs[2].url_params == {"section": "rackets", "node": "pro"}
