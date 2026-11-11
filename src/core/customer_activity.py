# Статус активности клиента по числу заказов.
def customer_activity_status(orders_count: int) -> str:
    if orders_count <= 0:
        return "inactive"
    if orders_count == 1:
        return "new"
    return "active"
