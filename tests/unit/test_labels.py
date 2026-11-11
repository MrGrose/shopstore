import pytest

from src.utils.labels import (
    is_redundant_surface_option,
    translate_feature_name,
    translate_feature_value,
)


@pytest.mark.parametrize(
    ("category_l2", "values", "expected"),
    [
        ("Padel rackets", ["full-surface"], True),
        ("Padel racket", ["full surface"], True),
        ("Padel rackets", ["full-surface", "rough-surface"], False),
        ("Tennis rackets", ["full-surface"], False),
        ("Padel rackets", ["unstrung"], False),
        ("Shoes", ["full-surface"], False),
        ("Padel rackets", [], False),
    ],
)
def test_is_redundant_surface_option(
    category_l2: str,
    values: list[str],
    expected: bool,
) -> None:
    assert is_redundant_surface_option(category_l2, "option1", values) is expected


def test_is_redundant_surface_option_ignores_non_option1() -> None:
    assert (
        is_redundant_surface_option("Padel rackets", "option2", ["full-surface"])
        is False
    )


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("Court type", "Carpet shoe", "Кроссовки для ковра"),
        ("Court type", "All court shoe", "Кроссовки для всех покрытий"),
        ("Court type", "Clay court shoe", "Кроссовки для грунта"),
        ("Court type", "Neutral running shoe", "Нейтральные кроссовки"),
        ("Arm Protection", "light", "Лёгкая"),
        ("Spin", "a lot of", "Высокое"),
        ("Control", "maximum", "Максимальный"),
        (
            "Game Strength",
            "Club player, Tournament player, Beginners",
            "Клубный уровень, Турнирный уровень, Для начинающих",
        ),
        ("Bag Capacity", "7-9 tennis rackets", "7–9 ракеток"),
        ("Game type", "Power", "Мощность"),
        ("Inner material", "cork", "пробка"),
        ("Outsole", "Kunststoff", "пластик"),
        ("Outsole", "Phylon", "филон"),
        ("Colour", "pastel pink", "пастельно-розовый"),
        ("Length", "12 m", "12 м"),
        ("Impact surface material", "Fiberglass", "стекловолокно"),
        ("Impact surface material", "Carbon, 2D carbon", "карбон, 2D карбон"),
        ("Sustainability", "maximum", "Максимальная"),
        ("Separate shoe compartment", "wine red", "бордовый"),
        ("Material", "100% Merino Blend", "100% смесь мериноса"),
    ],
)
def test_translate_feature_value(name: str, value: str, expected: str) -> None:
    assert translate_feature_value(name, value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Arm Protection", "Защита от вибраций"),
        ("Game Strength", "Уровень игры"),
        ("Bag Capacity", "Вместимость"),
        ("Impact surface material", "Материал ударной поверхности"),
    ],
)
def test_translate_feature_name(name: str, expected: str) -> None:
    assert translate_feature_name(name) == expected
