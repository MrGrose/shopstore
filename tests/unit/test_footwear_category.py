from src.utils.labels import is_footwear_category


def test_is_footwear_category_l2() -> None:
    assert is_footwear_category("Tennis shoes", None) is True


def test_is_footwear_category_l3() -> None:
    assert is_footwear_category("Tennis shoes", "All court shoes") is True
    assert is_footwear_category(None, "All court shoes") is True


def test_is_footwear_category_negative() -> None:
    assert is_footwear_category("Tennis rackets", None) is False
