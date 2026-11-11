from decimal import ROUND_HALF_UP, Decimal

MAX_MONEY = Decimal("99999999.99")


# Нормализует историческую цену поставщика с ошибочным масштабом x100.
def normalize_supplier_eur(value: Decimal) -> Decimal:
    if value >= Decimal("100000"):
        return (value / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return value


# Считает итоговую цену товара в RUB.
def calculate_price_rub(
    supplier_price_eur: Decimal,
    eur_rate: Decimal,
    margin_percent: Decimal,
) -> Decimal:
    margin_multiplier = Decimal("1") + (margin_percent / Decimal("100"))
    result = (supplier_price_eur * eur_rate * margin_multiplier).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if result > MAX_MONEY:
        raise ValueError(
            "Итоговая цена превышает допустимый лимит Numeric(10,2): "
            f"supplier_price_eur={supplier_price_eur}, eur_rate={eur_rate}, "
            f"margin_percent={margin_percent}, result={result}, "
            f"max_allowed={MAX_MONEY}"
        )
    return result


# Возвращает стоимость доставки в RUB.
def calculate_delivery_rub(delivery_fee_eur: Decimal, eur_rate: Decimal) -> Decimal:
    result = (delivery_fee_eur * eur_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if result > MAX_MONEY:
        raise ValueError("Стоимость доставки превышает допустимый лимит Numeric(10,2)")
    return result
