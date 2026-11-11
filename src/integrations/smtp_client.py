import asyncio
import logging
import smtplib
from email.message import EmailMessage

from src.core.config import settings

logger = logging.getLogger(__name__)


# Синхронная отправка письма через smtplib.
def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM.strip()
    msg["To"] = to_email
    msg.set_content(body)

    host = settings.SMTP_HOST.strip()
    port = settings.SMTP_PORT
    user = settings.SMTP_USER.strip()
    password = settings.SMTP_PASSWORD

    if settings.SMTP_USE_TLS:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


# Отправляет plain-text письмо через SMTP.
async def send_plain_email(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_configured:
        if settings.is_dev:
            logger.warning(
                "SMTP не настроен (dev): письмо для %s — %s",
                to_email,
                body,
            )
            return
        raise RuntimeError("SMTP не настроен")
    await asyncio.to_thread(_send_email_sync, to_email, subject, body)
