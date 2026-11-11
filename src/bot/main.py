import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from src.content.bot_texts import (
    BOT_BUTTON_OPEN_STORE,
    BOT_BUTTON_ORDERS,
    BOT_BUTTON_SUPPORT,
    BOT_COMMAND_START_DESCRIPTION,
    BOT_DEFAULT_USERNAME,
    BOT_LOGIN_UNAVAILABLE,
    BOT_MENU_BUTTON_STORE,
    BOT_PHONE_LINK_OK,
    BOT_REDIRECT_TO_ACCOUNT,
    BOT_TG_LINK_ERR,
    BOT_TG_LINK_OK,
    BOT_WELCOME_NEW_USER,
    account_orders_url,
    account_support_url,
    bot_welcome_returning_user,
)
from src.core.config import settings
from src.core.redis import async_redis
from src.core.user_access import user_is_active
from src.repositories.session import async_session_maker
from src.services.auth.telegram_link import TelegramLinkService
from src.services.identity_service import IdentityService
from src.services.user_service import UserService
from src.utils.phone import normalize_ru_mobile_phone
from src.utils.urls import normalize_mini_app_url


# Inline-клавиатура бота: магазин, заказы и поддержка в Mini App.
def build_bot_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_url = normalize_mini_app_url(settings.TG_MINI_APP_URL)
    rows.append(
        [
            InlineKeyboardButton(
                text=BOT_BUTTON_OPEN_STORE,
                web_app=WebAppInfo(url=mini_app_url),
            )
        ]
    )
    link_row: list[InlineKeyboardButton] = []
    orders_url = account_orders_url()
    if orders_url:
        link_row.append(
            InlineKeyboardButton(
                text=BOT_BUTTON_ORDERS,
                web_app=WebAppInfo(url=orders_url),
            )
        )
    support_url = account_support_url()
    if support_url:
        link_row.append(
            InlineKeyboardButton(
                text=BOT_BUTTON_SUPPORT,
                web_app=WebAppInfo(url=support_url),
            )
        )
    if link_row:
        rows.append(link_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Клавиатура при произвольном тексте: заказы, поддержка, магазин в одну строку.
def build_bot_redirect_keyboard() -> InlineKeyboardMarkup:
    mini_app_url = normalize_mini_app_url(settings.TG_MINI_APP_URL)
    row: list[InlineKeyboardButton] = []
    orders_url = account_orders_url()
    if orders_url:
        row.append(
            InlineKeyboardButton(
                text=BOT_BUTTON_ORDERS,
                web_app=WebAppInfo(url=orders_url),
            )
        )
    support_url = account_support_url()
    if support_url:
        row.append(
            InlineKeyboardButton(
                text=BOT_BUTTON_SUPPORT,
                web_app=WebAppInfo(url=support_url),
            )
        )
    row.append(
        InlineKeyboardButton(
            text=BOT_MENU_BUTTON_STORE,
            web_app=WebAppInfo(url=mini_app_url),
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=[row])


# Регистрирует меню команд и кнопку ☰ с Mini App в Telegram.
async def setup_bot_telegram_ui(bot: Bot) -> None:
    mini_app_url = normalize_mini_app_url(settings.TG_MINI_APP_URL)
    await bot.set_my_commands(
        [
            BotCommand(
                command="start",
                description=BOT_COMMAND_START_DESCRIPTION,
            ),
        ],
        scope=BotCommandScopeDefault(),
    )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=BOT_MENU_BUTTON_STORE,
            web_app=WebAppInfo(url=mini_app_url),
        ),
    )


# Извлекает реферальный код из /start <code>.
def _referral_code_from_start(message: Message) -> str | None:
    if not message.text:
        return None
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    code = parts[1].strip()
    return code or None


# Извлекает одноразовый токен привязки Telegram из /start.
def _telegram_link_token_from_start(message: Message) -> str | None:
    code = _referral_code_from_start(message)
    if not code or not code.startswith("link_"):
        return None
    token = code.removeprefix("link_").strip()
    return token or None


# Отправляет welcome и клавиатуру входа в магазин / ЛК.
async def handle_start(message: Message) -> None:
    link_token = _telegram_link_token_from_start(message)
    if link_token and message.from_user:
        await _handle_telegram_link(message, link_token)
        return
    welcome_text = BOT_WELCOME_NEW_USER
    if message.from_user:
        referral_code = _referral_code_from_start(message)
        async with async_session_maker() as session:
            user_service = UserService(session)
            existing_user = await user_service.get_by_telegram_id(message.from_user.id)
            user = await user_service.upsert_telegram_user(
                telegram_id=message.from_user.id,
                telegram_username=message.from_user.username,
                name=_build_display_name(message),
                referral_code=referral_code,
            )
            if existing_user:
                username = user.name or BOT_DEFAULT_USERNAME
                welcome_text = bot_welcome_returning_user(username)
                logging.info(
                    "Новый пользователь запустил бота: tg_id=%s",
                    message.from_user.id,
                )
            else:
                logging.info(
                    "Новый пользователь создан из запуска бота: tg_id=%s",
                    message.from_user.id,
                )
            if not user_is_active(user):
                await message.answer(BOT_LOGIN_UNAVAILABLE)
                return
    keyboard = build_bot_keyboard()
    await message.answer(
        welcome_text,
        reply_markup=keyboard,
    )


# Проверяет токен и привязывает Telegram к указанному аккаунту.
async def _handle_telegram_link(message: Message, token: str) -> None:
    user_id = await TelegramLinkService(
        async_redis(),
        ttl_seconds=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    ).consume_token(token)
    if user_id is None:
        await message.answer(
            BOT_TG_LINK_ERR,
        )
        return
    async with async_session_maker() as session:
        user_service = UserService(session)
        user = await user_service.get_user(user_id)
        if user is None:
            await message.answer(
                "Не удалось найти аккаунт. Создайте новую ссылку в личном кабинете."
            )
            return
        try:
            user = await IdentityService(session).link_telegram_to_user(
                user,
                telegram_id=message.from_user.id,
                telegram_username=message.from_user.username,
                name=_build_display_name(message),
            )
            user = await user_service.refresh_user_role_from_telegram_allowlist(user)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    confirmation = await message.answer(
        BOT_TG_LINK_OK,
    )
    asyncio.create_task(_delete_message_after(confirmation, 5))


# Удаляет временное подтверждение через заданное число секунд.
async def _delete_message_after(message: Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        logging.warning("Не удалось удалить временное сообщение Telegram")


# Принимает только собственный Telegram contact и привязывает его телефон.
async def handle_contact(message: Message) -> None:
    if not message.from_user or not message.contact:
        return
    try:
        contact = message.contact
        if contact.user_id != message.from_user.id:
            await message.answer(
                "Не удалось подтвердить этот номер. Отправьте свой контакт из Telegram."
            )
            return
        try:
            phone_e164 = normalize_ru_mobile_phone(contact.phone_number)
        except ValueError:
            await message.answer(
                "Не удалось распознать номер телефона. "
                "Попробуйте отправить контакт ещё раз."
            )
            return
        async with async_session_maker() as session:
            identity_service = IdentityService(session)
            user = await identity_service.resolve_user_by_telegram_id(
                message.from_user.id
            )
            if user is None:
                await message.answer(
                    "Сначала откройте магазин из этого бота, "
                    "затем отправьте контакт ещё раз."
                )
                return
            try:
                await identity_service.link_phone_to_user(user, phone_e164)
            except ValueError as exc:
                await message.answer(str(exc))
                return
        confirmation = await message.answer(
            BOT_PHONE_LINK_OK,
        )
        asyncio.create_task(_delete_message_after(confirmation, 5))
    finally:
        try:
            await message.delete()
        except Exception:
            logging.warning("Не удалось удалить сообщение с контактом из Telegram")


# Перенаправляет произвольный текст клиента в ЛК вместо чата поддержки.
async def handle_client_text(message: Message) -> None:
    if message.from_user:
        async with async_session_maker() as session:
            user = await UserService(session).get_by_telegram_id(message.from_user.id)
            if user and not user_is_active(user):
                await message.answer(BOT_LOGIN_UNAVAILABLE)
                return
    await message.answer(
        BOT_REDIRECT_TO_ACCOUNT,
        reply_markup=build_bot_redirect_keyboard(),
    )


# Возвращает отображаемое имя пользователя из Telegram-профиля.
def _build_display_name(message: Message) -> str | None:
    if not message.from_user:
        return None
    chunks = [message.from_user.first_name, message.from_user.last_name]
    parts = [part for part in chunks if part]
    return " ".join(parts) if parts else None


# Запускает Telegram-бота в режиме long polling.
async def main() -> None:
    if not settings.TG_BOT_SHOP:
        raise RuntimeError("TG_BOT_SHOP не задан")
    if not settings.TG_MINI_APP_URL:
        raise RuntimeError("TG_MINI_APP_URL не задан")

    logging.basicConfig(level=logging.INFO)
    dp = Dispatcher()
    dp.message.register(handle_start, CommandStart())
    dp.message.register(handle_contact, F.contact)
    dp.message.register(handle_client_text, F.text, ~F.text.startswith("/"))

    proxy = settings.TG_BOT_PROXY.strip()
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(token=settings.TG_BOT_SHOP, session=session)
    if proxy:
        logging.info("Telegram bot uses proxy: %s", proxy.split("@")[-1])
    await setup_bot_telegram_ui(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
