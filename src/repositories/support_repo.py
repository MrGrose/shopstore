from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.order import Order, OrderStatus
from src.models.support import SupportMessage, SupportMessageAttachment, SupportTicket
from src.repositories.base_repo import CRUDBase
from src.utils.datetime_fmt import utc_now_naive


class CrudSupport(CRUDBase):
    # Инициализирует репозиторий обращений в поддержку.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Создаёт обращение и первое сообщение клиента.
    async def create_ticket_with_message(
        self,
        user_id: int,
        topic: str,
        body: str,
        order_id: int | None,
    ) -> tuple[SupportTicket, SupportMessage]:
        ticket = SupportTicket(
            user_id=user_id,
            order_id=order_id,
            topic=topic,
            status="waiting_staff",
        )
        self.session.add(ticket)
        await self.session.flush()
        message = SupportMessage(
            ticket_id=ticket.id,
            author_type="customer",
            author_user_id=user_id,
            body=body.strip(),
        )
        self.session.add(message)
        await self.session.flush()
        return ticket, message

    # Возвращает обращение по id.
    async def get_ticket_by_id(self, ticket_id: int) -> SupportTicket | None:
        return await self.session.get(SupportTicket, ticket_id)

    # Возвращает обращение с сообщениями и вложениями (selectinload, без N+1).
    async def get_ticket_with_messages(
        self, ticket_id: int
    ) -> tuple[SupportTicket | None, list[SupportMessage]]:
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket is None:
            return None, []
        result = await self.session.scalars(
            select(SupportMessage)
            .options(selectinload(SupportMessage.attachments))
            .where(SupportMessage.ticket_id == ticket_id)
            .order_by(SupportMessage.created_at.asc(), SupportMessage.id.asc())
        )
        return ticket, list(result.all())

    # Список обращений пользователя (новые сверху).
    async def list_tickets_for_user(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SupportTicket], int]:
        filters = [SupportTicket.user_id == user_id]
        total = await self.session.scalar(
            select(func.count(SupportTicket.id)).where(*filters)
        )
        offset = max(page - 1, 0) * page_size
        result = await self.session.scalars(
            select(SupportTicket)
            .where(*filters)
            .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.all()), int(total or 0)

    # Список обращений для админки.
    async def list_tickets_admin(
        self,
        order_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SupportTicket], int]:
        filters = []
        if order_id is not None:
            filters.append(SupportTicket.order_id == order_id)
        if status:
            filters.append(SupportTicket.status == status)
        total = await self.session.scalar(
            select(func.count(SupportTicket.id)).where(*filters)
        )
        offset = max(page - 1, 0) * page_size
        query = select(SupportTicket).order_by(
            SupportTicket.updated_at.desc(),
            SupportTicket.id.desc(),
        )
        if filters:
            query = query.where(*filters)
        query = query.offset(offset).limit(page_size)
        result = await self.session.scalars(query)
        return list(result.all()), int(total or 0)

    # Счётчики обращений по status для pill-фильтров админки.
    async def count_admin_tickets_grouped(
        self, order_id: int | None = None
    ) -> dict[str, int]:
        filters = []
        if order_id is not None:
            filters.append(SupportTicket.order_id == order_id)
        query = select(SupportTicket.status, func.count(SupportTicket.id)).group_by(
            SupportTicket.status
        )
        if filters:
            query = query.where(*filters)
        rows = await self.session.execute(query)
        return {str(status): int(count) for status, count in rows.all()}

    # Последние сообщения для набора обращений (batch, без N+1).
    async def get_last_messages_for_ticket_ids(
        self, ticket_ids: list[int]
    ) -> dict[int, SupportMessage]:
        if not ticket_ids:
            return {}
        result = await self.session.scalars(
            select(SupportMessage)
            .where(SupportMessage.ticket_id.in_(ticket_ids))
            .distinct(SupportMessage.ticket_id)
            .order_by(
                SupportMessage.ticket_id,
                SupportMessage.created_at.desc(),
                SupportMessage.id.desc(),
            )
        )
        return {row.ticket_id: row for row in result.all()}

    # Добавляет сообщение в обращение.
    async def add_message(
        self,
        ticket_id: int,
        author_type: str,
        author_user_id: int | None,
        body: str,
    ) -> SupportMessage:
        message = SupportMessage(
            ticket_id=ticket_id,
            author_type=author_type,
            author_user_id=author_user_id,
            body=body.strip(),
        )
        self.session.add(message)
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket is not None:
            ticket.updated_at = utc_now_naive()
        await self.session.flush()
        return message

    # Сохраняет строку вложения после успешного Storage.put.
    async def add_attachment(
        self,
        message_id: int,
        storage_key: str,
        content_type: str,
        byte_size: int,
    ) -> SupportMessageAttachment:
        row = SupportMessageAttachment(
            message_id=message_id,
            storage_key=storage_key,
            content_type=content_type,
            byte_size=byte_size,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # Возвращает вложение вместе с тикетом для authz/download.
    async def get_attachment_with_ticket(
        self, ticket_id: int, attachment_id: int
    ) -> tuple[SupportMessageAttachment, SupportTicket] | None:
        result = await self.session.execute(
            select(SupportMessageAttachment, SupportTicket)
            .join(
                SupportMessage, SupportMessage.id == SupportMessageAttachment.message_id
            )
            .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
            .where(
                SupportMessageAttachment.id == attachment_id,
                SupportTicket.id == ticket_id,
            )
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    # Ключи Storage по тикетам пользователя (перед GDPR CASCADE).
    async def list_storage_keys_for_user(self, user_id: int) -> list[str]:
        result = await self.session.scalars(
            select(SupportMessageAttachment.storage_key)
            .join(
                SupportMessage, SupportMessage.id == SupportMessageAttachment.message_id
            )
            .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
            .where(SupportTicket.user_id == user_id)
        )
        return [str(key) for key in result.all()]

    # Все storage_key support-вложений (для orphan cleanup).
    async def list_all_attachment_keys(self) -> set[str]:
        result = await self.session.scalars(
            select(SupportMessageAttachment.storage_key)
        )
        return {str(key) for key in result.all()}

    # Вложения закрытых тикетов старше cutoff.
    async def list_expired_attachments(
        self, cutoff: datetime, limit: int
    ) -> list[SupportMessageAttachment]:
        result = await self.session.scalars(
            select(SupportMessageAttachment)
            .join(
                SupportMessage, SupportMessage.id == SupportMessageAttachment.message_id
            )
            .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
            .where(
                SupportTicket.status == "closed",
                SupportTicket.closed_at.is_not(None),
                SupportTicket.closed_at <= cutoff,
            )
            .order_by(SupportMessageAttachment.id.asc())
            .limit(limit)
        )
        return list(result.all())

    # Удаляет строку вложения; сообщение не трогает.
    async def delete_attachment(self, attachment: SupportMessageAttachment) -> None:
        await self.session.delete(attachment)
        await self.session.flush()

    # Сохраняет результат доставки staff-ответа в Telegram.
    async def set_message_telegram_delivered(
        self, message_id: int, delivered: bool
    ) -> None:
        message = await self.session.get(SupportMessage, message_id)
        if message is None:
            return
        message.telegram_delivered = delivered
        await self.session.flush()

    # Обновляет статус обращения.
    async def update_ticket_status(
        self,
        ticket: SupportTicket,
        status: str,
        closed_by: str | None = None,
    ) -> None:
        ticket.status = status
        ticket.updated_at = utc_now_naive()
        if status == "closed":
            ticket.closed_at = utc_now_naive()
            ticket.closed_by = closed_by
        await self.session.flush()

    # Считает незакрытые обращения (для badge админки).
    async def count_open_tickets(self) -> int:
        value = await self.session.scalar(
            select(func.count(SupportTicket.id)).where(SupportTicket.status != "closed")
        )
        return int(value or 0)

    # Считает незакрытые обращения по заказам.
    async def count_open_tickets_by_order_ids(
        self, order_ids: list[int]
    ) -> dict[int, int]:
        if not order_ids:
            return {}
        result = await self.session.execute(
            select(SupportTicket.order_id, func.count(SupportTicket.id))
            .where(
                SupportTicket.order_id.in_(order_ids),
                SupportTicket.status != "closed",
            )
            .group_by(SupportTicket.order_id)
        )
        counts: dict[int, int] = {}
        for order_id, count in result.all():
            if order_id is not None:
                counts[int(order_id)] = int(count)
        return counts

    # Заказы пользователя для optional-select в поддержке.
    async def list_linkable_orders(self, user_id: int) -> list[Order]:
        since = utc_now_naive() - timedelta(hours=24)
        unpaid = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.payment_paid_at.is_(None),
                Order.status.in_([OrderStatus.CREATED, OrderStatus.PROCESSING]),
                Order.created_at >= since,
            )
            .order_by(Order.created_at.desc())
        )
        paid_active = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.payment_paid_at.isnot(None),
                Order.status.notin_([OrderStatus.COMPLETED, OrderStatus.CANCELLED]),
            )
            .order_by(Order.created_at.desc())
        )
        unpaid_rows = list((await self.session.scalars(unpaid)).all())
        paid_rows = list((await self.session.scalars(paid_active)).all())
        seen: set[int] = set()
        merged: list[Order] = []
        for row in unpaid_rows + paid_rows:
            if row.id in seen:
                continue
            seen.add(row.id)
            merged.append(row)
        return merged

    # Ключи Storage по списку тикетов.
    async def list_storage_keys_for_ticket_ids(
        self, ticket_ids: list[int]
    ) -> list[str]:
        if not ticket_ids:
            return []
        result = await self.session.scalars(
            select(SupportMessageAttachment.storage_key)
            .join(
                SupportMessage, SupportMessage.id == SupportMessageAttachment.message_id
            )
            .where(SupportMessage.ticket_id.in_(ticket_ids))
        )
        return [str(key) for key in result.all()]

    # Безвозвратно удаляет тикеты; messages/attachments — DB CASCADE.
    async def delete_tickets_by_ids(self, ticket_ids: list[int]) -> int:
        unique_ids = sorted(
            {int(ticket_id) for ticket_id in ticket_ids if int(ticket_id) > 0}
        )
        if not unique_ids:
            return 0
        result = await self.session.execute(
            delete(SupportTicket).where(SupportTicket.id.in_(unique_ids))
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    # Удаляет обращения пользователя и снимает ссылки author_user_id в чужих тикетах.
    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            update(SupportMessage)
            .where(SupportMessage.author_user_id == user_id)
            .values(author_user_id=None)
        )
        await self.session.execute(
            delete(SupportTicket).where(SupportTicket.user_id == user_id)
        )
        await self.session.flush()
