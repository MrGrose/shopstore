from types import SimpleNamespace

from src.web.templating import templates


def _render_supplier_check(**overrides: object) -> str:
    values: dict[str, object] = {
        "html_validation": None,
        "challenge": None,
        "found": True,
        "status_text": "вариант найден, 4 шт.",
        "price_prefix_text": "Цена TP: 119.90 EUR",
        "price_delta_text": "дешевле на 10.00 EUR",
        "price_delta_tone": "lower",
    }
    values.update(overrides)
    row = SimpleNamespace(supplier_check=SimpleNamespace(**values))
    template = templates.env.get_template(
        "site/admin/partials/_order_availability_stock_check.html"
    )
    return str(template.module.availability_supplier_check(row))


def test_supplier_check_renders_success_and_price_delta() -> None:
    rendered = _render_supplier_check()
    assert "вариант найден, 4 шт." in rendered
    assert "Цена TP: 119.90 EUR" in rendered
    assert "дешевле на 10.00 EUR" in rendered


def test_supplier_check_renders_login_warning() -> None:
    rendered = _render_supplier_check(
        html_validation="login",
        challenge="login",
        found=False,
    )
    assert "Сессия TP недействительна" in rendered
    assert "storage state" in rendered


def test_supplier_check_renders_captcha_warning() -> None:
    rendered = _render_supplier_check(
        html_validation="no_product_data",
        challenge="captcha",
        found=False,
    )
    assert "Предупреждение автопроверки" in rendered
    assert "captcha" in rendered


def test_supplier_check_renders_generic_server_error() -> None:
    rendered = _render_supplier_check(
        html_validation="status=502",
        challenge="server_error",
        found=False,
    )
    assert "ошибку сервера" in rendered
    assert "Автопроверка" in rendered
    assert "HTTP 500" not in rendered
