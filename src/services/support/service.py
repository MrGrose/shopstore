import logging
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.support_texts import SUPPORT_TOPIC_LABELS, support_topic_label
from src.core.config import settings
from src.core.user_roles import UserRole
from src.models.support import SupportMessage, SupportTicket
from src.models.user import User
from src.repositories.support_repo import CrudSupport
from src.schemas.support import (
    SupportAttachmentSchema,
    SupportLinkableOrderSchema,
    SupportMessageAdminSchema,
    SupportMessageSchema,
    SupportTicketCreateSchema,
    SupportTicketDetailAdminSchema,
    SupportTicketDetailSchema,
    SupportTicketListItemSchema,
    SupportTicketListPageSchema,
)
from src.services.notifications.inline_dispatcher import notification_uses_outbox
from src.services.support.notification_service import SupportNotificationService
from src.storage import get_storage
from src.utils.datetime_fmt import utc_now_naive
from src.utils.images import ALLOWED_IMAGE_TYPES

logger = logging.getLogger(__name__)

VALID_TOPICS = frozenset(SUPPORT_TOPIC_LABELS.keys())
SUPPORT_KEY_PREFIX = "support/"
_SUPPORT_MAX_EDGE = 1920
_SUPPORT_JPEG_QUALITIES = (85, 70, 55)
_SUPPORT_TARGET_BYTES = 800 * 1024
_SUPPORT_BODY_MAX_LENGTH = 4000
_ORPHAN_MIN_AGE = timedelta(hours=1)
_PILLOW_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


# UTC-aware mtime; неизвестная метка → None (orphan не удаляем).
def _utc_mtime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SupportService:
    # Инициализирует сервис поддержки.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CrudSupport(session)

    # Нормализует page_size для API и админки.
    def _normalize_page_size(self, page_size: int, admin: bool = False) -> int:
        default = (
            settings.SUPPORT_ADMIN_TICKETS_PAGE_SIZE_DEFAULT
            if admin
            else settings.SUPPORT_TICKETS_PAGE_SIZE_DEFAULT
        )
        max_size = settings.SUPPORT_TICKETS_PAGE_SIZE_MAX
        size = page_size or default
        return max(1, min(size, max_size))

    # Превью последнего сообщения для списка.
    def _message_preview(self, message: SupportMessage | None) -> str | None:
        if message is None:
            return None
        preview = message.body.strip()
        if not preview:
            return "Фото"
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return preview

    # Собирает элементы списка без N+1.
    def _build_list_items(
        self,
        tickets: list[SupportTicket],
        last_by_ticket: dict[int, SupportMessage],
    ) -> list[SupportTicketListItemSchema]:
        items: list[SupportTicketListItemSchema] = []
        for ticket in tickets:
            items.append(
                SupportTicketListItemSchema(
                    id=ticket.id,
                    topic=ticket.topic,
                    topic_label=support_topic_label(ticket.topic),
                    status=ticket.status,
                    order_id=ticket.order_id,
                    created_at=ticket.created_at,
                    updated_at=ticket.updated_at,
                    last_message_preview=self._message_preview(
                        last_by_ticket.get(ticket.id)
                    ),
                )
            )
        return items

    # Список обращений текущего клиента с пагинацией.
    async def list_tickets_for_user(
        self,
        user_id: int,
        page: int = 1,
        page_size: int | None = None,
    ) -> SupportTicketListPageSchema:
        size = self._normalize_page_size(page_size or 0, admin=False)
        safe_page = max(page, 1)
        tickets, total = await self.repo.list_tickets_for_user(
            user_id,
            page=safe_page,
            page_size=size,
        )
        last_by_ticket = await self.repo.get_last_messages_for_ticket_ids(
            [ticket.id for ticket in tickets]
        )
        return SupportTicketListPageSchema(
            items=self._build_list_items(tickets, last_by_ticket),
            total=total,
            page=safe_page,
            page_size=size,
        )

    # Список обращений для админки с пагинацией.
    async def list_tickets_admin(
        self,
        order_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> SupportTicketListPageSchema:
        size = self._normalize_page_size(page_size or 0, admin=True)
        safe_page = max(page, 1)
        tickets, total = await self.repo.list_tickets_admin(
            order_id=order_id,
            status=status,
            page=safe_page,
            page_size=size,
        )
        last_by_ticket = await self.repo.get_last_messages_for_ticket_ids(
            [ticket.id for ticket in tickets]
        )
        return SupportTicketListPageSchema(
            items=self._build_list_items(tickets, last_by_ticket),
            total=total,
            page=safe_page,
            page_size=size,
        )

    # Счётчики обращений по status для pill-фильтров админки.
    async def get_admin_status_counts(
        self, order_id: int | None = None
    ) -> dict[str, int]:
        grouped = await self.repo.count_admin_tickets_grouped(order_id=order_id)
        counts = {
            code: grouped.get(code, 0)
            for code in ("waiting_staff", "waiting_customer", "closed")
        }
        counts[""] = sum(grouped.values())
        return counts

    # Детали обращения для клиента.
    async def get_ticket_for_user(
        self,
        user_id: int,
        ticket_id: int,
    ) -> SupportTicketDetailSchema | None:
        ticket, messages = await self.repo.get_ticket_with_messages(ticket_id)
        if ticket is None or ticket.user_id != user_id:
            return None
        return self._to_detail(ticket, messages, admin=False)

    # Детали обращения для админки.
    async def get_ticket_admin(
        self, ticket_id: int
    ) -> SupportTicketDetailAdminSchema | None:
        ticket, messages = await self.repo.get_ticket_with_messages(ticket_id)
        if ticket is None:
            return None
        return self._to_detail(ticket, messages, admin=True)

    # Собирает schema вложений без storage_key и без public URL.
    def _attachment_schemas(
        self, message: SupportMessage
    ) -> list[SupportAttachmentSchema]:
        return [
            SupportAttachmentSchema(
                id=row.id,
                content_type=row.content_type,
                byte_size=row.byte_size,
            )
            for row in message.attachments
        ]

    # Собирает schema сообщения клиента.
    def _customer_message_schema(self, row: SupportMessage) -> SupportMessageSchema:
        return SupportMessageSchema(
            id=row.id,
            author_type=row.author_type,
            author_user_id=row.author_user_id,
            body=row.body,
            created_at=row.created_at,
            attachments=self._attachment_schemas(row),
        )

    # Собирает schema сообщения для админки.
    def _admin_message_schema(self, row: SupportMessage) -> SupportMessageAdminSchema:
        return SupportMessageAdminSchema(
            id=row.id,
            author_type=row.author_type,
            author_user_id=row.author_user_id,
            body=row.body,
            created_at=row.created_at,
            telegram_delivered=row.telegram_delivered,
            attachments=self._attachment_schemas(row),
        )

    # Собирает schema деталей обращения (admin — с флагом доставки TG).
    def _to_detail(
        self,
        ticket: SupportTicket,
        messages: list[SupportMessage],
        admin: bool = False,
    ) -> SupportTicketDetailSchema | SupportTicketDetailAdminSchema:
        base = {
            "id": ticket.id,
            "topic": ticket.topic,
            "topic_label": support_topic_label(ticket.topic),
            "status": ticket.status,
            "order_id": ticket.order_id,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "closed_at": ticket.closed_at,
        }
        if admin:
            return SupportTicketDetailAdminSchema(
                **base,
                messages=[self._admin_message_schema(row) for row in messages],
            )
        return SupportTicketDetailSchema(
            **base,
            messages=[self._customer_message_schema(row) for row in messages],
        )

    # Проверяет, что заказ принадлежит пользователю и доступен для привязки.
    async def _validate_linkable_order(
        self,
        user_id: int,
        order_id: int | None,
    ) -> None:
        if order_id is None:
            return
        linkable = await self.repo.list_linkable_orders(user_id)
        allowed_ids = {row.id for row in linkable}
        if order_id not in allowed_ids:
            raise ValueError("Выбранный заказ недоступен для обращения")

    # Проверяет текст и число файлов: текст без файлов — 1–4000, photo-only — "".
    def _normalize_body_and_uploads(
        self,
        body: str,
        uploads: list[tuple[bytes, str]] | None,
        empty_error: str,
    ) -> tuple[str, list[tuple[bytes, str, str]]]:
        files = uploads or []
        text = body.strip()
        if len(text) > _SUPPORT_BODY_MAX_LENGTH:
            raise ValueError("Текст сообщения слишком длинный")
        max_files = settings.SUPPORT_ATTACHMENT_MAX_FILES
        if len(files) > max_files:
            raise ValueError(f"Можно прикрепить не больше {max_files} фото")
        if not text and not files:
            raise ValueError(empty_error)
        verified = [
            self._verify_support_image(content, declared) for content, declared in files
        ]
        return text, verified

    # Pillow verify + whitelist; сжимает в JPEG 1920px без EXIF.
    def _verify_support_image(
        self, content: bytes, declared_type: str
    ) -> tuple[bytes, str, str]:
        max_upload = settings.SUPPORT_ATTACHMENT_MAX_UPLOAD_BYTES
        if len(content) > max_upload:
            raise ValueError("Изображение слишком большое")
        declared = (declared_type or "").split(";")[0].strip().lower()
        if declared and declared not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Разрешены изображения в формате JPG, PNG или WebP")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                fmt = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Некорректное изображение") from exc
        if fmt not in _PILLOW_FORMATS:
            raise ValueError("Разрешены изображения в формате JPG, PNG или WebP")
        return self._normalize_support_photo(content)

    # Resize + JPEG; ориентацию берём из EXIF и сразу выбрасываем GPS.
    def _normalize_support_photo(self, content: bytes) -> tuple[bytes, str, str]:
        with Image.open(BytesIO(content)) as src:
            image = ImageOps.exif_transpose(src)
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
            image = image.copy()
        longest = max(image.size)
        if longest > _SUPPORT_MAX_EDGE:
            ratio = _SUPPORT_MAX_EDGE / longest
            image = image.resize(
                (
                    max(1, round(image.width * ratio)),
                    max(1, round(image.height * ratio)),
                ),
                Image.Resampling.LANCZOS,
            )
        encoded = b""
        for quality in _SUPPORT_JPEG_QUALITIES:
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=quality, optimize=True)
            encoded = buf.getvalue()
            if len(encoded) <= _SUPPORT_TARGET_BYTES:
                break
        return encoded, "image/jpeg", ".jpg"

    # Пишет объекты support/{ticket_id}/{uuid}.ext и строки БД. Без public_url.
    async def _store_attachments(
        self,
        ticket_id: int,
        message_id: int,
        verified: list[tuple[bytes, str, str]],
    ) -> list[str]:
        storage = get_storage()
        stored: list[str] = []
        try:
            for content, mime, ext in verified:
                key = f"{SUPPORT_KEY_PREFIX}{ticket_id}/{uuid.uuid4()}{ext}"
                stored.append(key)
                storage.put(key, content, mime)
                await self.repo.add_attachment(message_id, key, mime, len(content))
        except Exception:
            self._delete_stored_keys(stored)
            raise
        return stored

    # Удаляет объекты Storage; отсутствие ключа — успех.
    def _delete_stored_keys(self, keys: list[str]) -> None:
        if not keys:
            return
        storage = get_storage()
        for key in keys:
            try:
                storage.delete(key)
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception("Не удалось удалить support-объект %s", key)

    # Создаёт новое обращение.
    async def create_ticket(
        self,
        user_id: int,
        payload: SupportTicketCreateSchema,
        uploads: list[tuple[bytes, str]] | None = None,
    ) -> SupportTicketDetailSchema:
        topic = payload.topic.strip().lower()
        if topic not in VALID_TOPICS:
            raise ValueError("Недопустимая тема обращения")
        body, verified = self._normalize_body_and_uploads(
            payload.body,
            uploads,
            "Введите текст обращения",
        )
        await self._validate_linkable_order(user_id, payload.order_id)
        stored_keys: list[str] = []
        try:
            ticket, message = await self.repo.create_ticket_with_message(
                user_id=user_id,
                topic=topic,
                body=body,
                order_id=payload.order_id,
            )
            stored_keys = await self._store_attachments(ticket.id, message.id, verified)
            user = await self.session.get(User, user_id)
            await SupportNotificationService(self.session).notify_support_group(
                ticket_id=ticket.id,
                topic=topic,
                user=user,
                order_id=payload.order_id,
                body=body,
                is_new_ticket=True,
                message_id=message.id,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self._delete_stored_keys(stored_keys)
            raise
        detail = await self.get_ticket_for_user(user_id, ticket.id)
        if detail is None:
            raise ValueError("Обращение не найдено")
        return detail

    # Добавляет сообщение клиента.
    async def add_customer_message(
        self,
        user_id: int,
        ticket_id: int,
        body: str,
        uploads: list[tuple[bytes, str]] | None = None,
    ) -> SupportTicketDetailSchema:
        text, verified = self._normalize_body_and_uploads(
            body,
            uploads,
            "Введите сообщение",
        )
        ticket = await self.repo.get_ticket_by_id(ticket_id)
        if ticket is None or ticket.user_id != user_id:
            raise ValueError("Обращение не найдено")
        if ticket.status == "closed":
            raise ValueError("Обращение закрыто. Создайте новое.")
        stored_keys: list[str] = []
        try:
            message = await self.repo.add_message(
                ticket_id=ticket_id,
                author_type="customer",
                author_user_id=user_id,
                body=text,
            )
            stored_keys = await self._store_attachments(ticket.id, message.id, verified)
            await self.repo.update_ticket_status(ticket, "waiting_staff")
            user = await self.session.get(User, user_id)
            await SupportNotificationService(self.session).notify_support_group(
                ticket_id=ticket.id,
                topic=ticket.topic,
                user=user,
                order_id=ticket.order_id,
                body=text,
                is_new_ticket=False,
                message_id=message.id,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self._delete_stored_keys(stored_keys)
            raise
        detail = await self.get_ticket_for_user(user_id, ticket_id)
        if detail is None:
            raise ValueError("Обращение не найдено")
        return detail

    # Ответ сотрудника из админки; возвращает (detail, tg_delivered).
    async def add_staff_reply(
        self,
        ticket_id: int,
        staff_user: User,
        body: str,
        uploads: list[tuple[bytes, str]] | None = None,
    ) -> tuple[SupportTicketDetailAdminSchema, bool | None]:
        text, verified = self._normalize_body_and_uploads(
            body,
            uploads,
            "Введите ответ",
        )
        ticket = await self.repo.get_ticket_by_id(ticket_id)
        if ticket is None:
            raise ValueError("Обращение не найдено")
        if ticket.status == "closed":
            raise ValueError("Обращение закрыто")
        stored_keys: list[str] = []
        try:
            message = await self.repo.add_message(
                ticket_id=ticket_id,
                author_type="staff",
                author_user_id=staff_user.id,
                body=text,
            )
            stored_keys = await self._store_attachments(ticket.id, message.id, verified)
            await self.repo.update_ticket_status(ticket, "waiting_customer")
            customer = await self.session.get(User, ticket.user_id)
            scheduled = await SupportNotificationService(
                self.session
            ).notify_customer_staff_reply(
                user=customer,
                ticket_id=ticket_id,
                body=text,
                message_id=message.id,
            )
            tg_delivered: bool | None
            if notification_uses_outbox():
                tg_delivered = None
            else:
                tg_delivered = scheduled
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self._delete_stored_keys(stored_keys)
            raise
        if tg_delivered is False:
            logger.warning(
                "Ответ поддержки сохранён, TG клиенту не доставлен: ticket_id=%s",
                ticket_id,
            )
        detail = await self.get_ticket_admin(ticket_id)
        if detail is None:
            raise ValueError("Обращение не найдено")
        return detail, tg_delivered

    # Закрывает обращение (клиент или staff).
    async def close_ticket(
        self,
        ticket_id: int,
        actor_user_id: int,
        closed_by: str,
        is_staff: bool = False,
    ) -> SupportTicketDetailSchema:
        ticket = await self.repo.get_ticket_by_id(ticket_id)
        if ticket is None:
            raise ValueError("Обращение не найдено")
        if not is_staff and ticket.user_id != actor_user_id:
            raise ValueError("Обращение не найдено")
        if ticket.status == "closed":
            raise ValueError("Обращение уже закрыто")
        await self.repo.update_ticket_status(ticket, "closed", closed_by=closed_by)
        await self.session.commit()
        if is_staff:
            detail = await self.get_ticket_admin(ticket_id)
        else:
            detail = await self.get_ticket_for_user(actor_user_id, ticket_id)
        if detail is None:
            raise ValueError("Обращение не найдено")
        return detail

    # True, если пользователь — владелец тикета или admin.
    def _can_access_ticket(self, user: User, ticket: SupportTicket) -> bool:
        if ticket.user_id == user.id:
            return True
        return str(user.role or "").strip().lower() == UserRole.ADMIN.value

    # True для ключей support/{ticket_id}/..., без path traversal.
    def _is_support_storage_key(self, key: str, ticket_id: int) -> bool:
        prefix = f"{SUPPORT_KEY_PREFIX}{ticket_id}/"
        if not key.startswith(prefix):
            return False
        rest = key[len(prefix) :]
        if not rest or "/" in rest or ".." in rest:
            return False
        return True

    # Читает байты вложения для owner/admin. Чужой/битый ключ — None.
    async def read_attachment_file(
        self,
        user: User,
        ticket_id: int,
        attachment_id: int,
    ) -> tuple[bytes, str] | None:
        loaded = await self.repo.get_attachment_with_ticket(ticket_id, attachment_id)
        if loaded is None:
            return None
        attachment, ticket = loaded
        if not self._can_access_ticket(user, ticket):
            return None
        if not self._is_support_storage_key(attachment.storage_key, ticket.id):
            logger.warning(
                "Support attachment %s имеет некорректный ключ %s",
                attachment.id,
                attachment.storage_key,
            )
            return None
        try:
            data = get_storage().read(attachment.storage_key)
        except FileNotFoundError:
            return None
        return data, attachment.content_type

    # Безвозвратно удаляет выбранные обращения: Storage, затем CASCADE.
    async def admin_delete_tickets_by_ids(self, ticket_ids: list[int]) -> int:
        unique_ids = sorted(
            {int(ticket_id) for ticket_id in ticket_ids if int(ticket_id) > 0}
        )
        if not unique_ids:
            raise ValueError("Не выбраны обращения")
        keys = set(await self.repo.list_storage_keys_for_ticket_ids(unique_ids))
        storage = get_storage()
        for ticket_id in unique_ids:
            prefix = f"{SUPPORT_KEY_PREFIX}{ticket_id}/"
            for key in storage.iter_keys(prefix):
                text_key = str(key)
                if text_key.startswith(prefix):
                    keys.add(text_key)
        self._delete_stored_keys(sorted(keys))
        try:
            deleted = await self.repo.delete_tickets_by_ids(unique_ids)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            logger.exception("Не удалось удалить обращения %s", unique_ids)
            raise ValueError("Не удалось удалить обращения")
        return deleted

    # Удаляет support-объекты пользователя, затем CASCADE тикетов.
    async def delete_for_user(self, user_id: int) -> None:
        keys = await self.repo.list_storage_keys_for_user(user_id)
        self._delete_stored_keys(keys)
        await self.repo.delete_for_user(user_id)

    # Retention: Storage.delete → delete row. Сообщения и тикеты не трогает.
    async def purge_expired_attachments(self, limit: int = 100) -> dict[str, int]:
        cutoff = utc_now_naive() - timedelta(
            days=settings.SUPPORT_ATTACHMENT_RETENTION_DAYS
        )
        rows = await self.repo.list_expired_attachments(cutoff, limit)
        purged = 0
        for attachment in rows:
            self._delete_stored_keys([attachment.storage_key])
            await self.repo.delete_attachment(attachment)
            purged += 1
        if purged:
            await self.session.commit()
        orphans = await self._purge_orphan_support_objects()
        return {"purged": purged, "orphans": orphans, "candidates": len(rows)}

    # Удаляет support/ объекты без строки в БД; свежие (окно put→commit) не трогает.
    async def _purge_orphan_support_objects(self) -> int:
        db_keys = await self.repo.list_all_attachment_keys()
        storage = get_storage()
        cutoff = datetime.now(UTC) - _ORPHAN_MIN_AGE
        removed = 0
        for key, mtime in storage.iter_key_mtimes(SUPPORT_KEY_PREFIX):
            if not str(key).startswith(SUPPORT_KEY_PREFIX):
                continue
            if key in db_keys:
                continue
            aware = _utc_mtime(mtime)
            if aware is None or aware > cutoff:
                continue
            self._delete_stored_keys([key])
            removed += 1
        return removed

    # Заказы для optional-select.
    async def list_linkable_orders(
        self, user_id: int
    ) -> list[SupportLinkableOrderSchema]:
        rows = await self.repo.list_linkable_orders(user_id)
        return [
            SupportLinkableOrderSchema(
                id=row.id,
                status=str(row.status),
                total_amount=str(row.total_amount),
                created_at=row.created_at,
            )
            for row in rows
        ]

    # Счётчик незакрытых обращений для nav badge.
    async def count_open_tickets(self) -> int:
        return await self.repo.count_open_tickets()

    # Счётчики незакрытых обращений по заказам.
    async def count_open_tickets_by_order_ids(
        self, order_ids: list[int]
    ) -> dict[int, int]:
        return await self.repo.count_open_tickets_by_order_ids(order_ids)

    # Карточка обращения для админки с данными клиента.
    async def get_admin_ticket_context(
        self,
        ticket_id: int,
    ) -> dict[str, object] | None:
        ticket = await self.repo.get_ticket_by_id(ticket_id)
        if ticket is None:
            return None
        detail = await self.get_ticket_admin(ticket_id)
        if detail is None:
            return None
        customer = await self.session.get(User, ticket.user_id)
        return {
            "ticket": detail,
            "customer": customer,
        }
