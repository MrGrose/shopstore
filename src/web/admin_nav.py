from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.models.order import Order
from src.models.support import SupportTicket
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker


# Счётчики для меню админки.
async def fetch_admin_nav_badges(session: AsyncSession) -> dict[str, int]:
    queues = await CrudOrder(session=session, model=Order).admin_orders_queues()
    orders_action = sum(int(value) for value in queues.values())
    open_support = await session.scalar(
        select(func.count(SupportTicket.id)).where(SupportTicket.status != "closed")
    )
    return {
        "orders_action": orders_action,
        "open_support_tickets": int(open_support or 0),
    }


# На каждый запрос админки (кроме логина) кладёт в request.state бейджи для _nav.html.
class AdminNavMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/internal/admin") and not path.startswith(
            "/internal/admin/login"
        ):
            async with async_session_maker() as session:
                badges = await fetch_admin_nav_badges(session)
                request.state.admin_nav_orders_action = badges["orders_action"]
                request.state.admin_nav_open_support = badges["open_support_tickets"]
        return await call_next(request)
