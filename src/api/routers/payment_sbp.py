import base64
import json
import logging

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.deps import get_db
from src.services.payment_service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/sbp", tags=["payments"])


# Проверяет RSA-SHA1 подпись тела callback (payment-sign).
def verify_sbp_callback_signature(
    body: bytes, signature_b64: str, public_key_pem: str
) -> bool:
    pem = public_key_pem.strip()
    if not pem:
        return False
    if "BEGIN PUBLIC KEY" not in pem:
        pem = f"-----BEGIN PUBLIC KEY-----\n{pem}\n-----END PUBLIC KEY-----"
    try:
        public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except (ValueError, TypeError):
        return False
    try:
        public_key.verify(signature, body, padding.PKCS1v15(), hashes.SHA1())
    except InvalidSignature:
        return False
    return True


# Публичный webhook SBP по изменению статуса оплаты.
@router.post("/callback", status_code=status.HTTP_200_OK)
async def sbp_payment_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    body = await request.body()
    signature = (
        request.headers.get("payment-sign") or request.headers.get("Payment-Sign") or ""
    ).strip()
    if not settings.SBP_SKIP_SIGNATURE_VERIFY:
        public_key = settings.SBP_WEBHOOK_PUBLIC_KEY.strip()
        if not signature or not verify_sbp_callback_signature(
            body, signature, public_key
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Неверная подпись callback",
            )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректное тело callback",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректное тело callback",
        )
    service = PaymentService(db)
    try:
        await service.handle_sbp_callback(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"status": "ok"}
