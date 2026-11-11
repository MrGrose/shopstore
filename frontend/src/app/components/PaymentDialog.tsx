import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import QRCode from "qrcode";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import { storefrontApiFetch } from "../../lib/storefront/api";
import { moneyRub } from "../../lib/storefront/checkoutUi";
import {
  formatCountdown,
  isPaymentExhaustedState,
  isPaymentFinalErrorState,
  isPaymentSuccessState,
  isPaymentWaitingState,
  PAYMENT_NETWORK_RETRY_DELAYS_MS,
  PAYMENT_POLL_INTERVAL_MS,
  qrCountdownMs,
} from "../../lib/storefront/paymentStatus";
import { orderPaymentExhaustedText } from "../../lib/storefront/orderPaymentUi";
import { useStorefrontCompact, useStorefrontBottomNav } from "../../lib/storefront/useStorefrontSurface";
import { MINIAPP_BOTTOM_NAV_OFFSET } from "../../lib/storefront/miniApp";
import { miniAppPillClass } from "../../lib/storefront/miniAppUi";

type PaymentInitResponse = {
  order_id: number;
  provider: string;
  payment_attempt_id: number;
  payment_state: string;
  payment_qr_payload?: string | null;
  qr_expires_at?: string | null;
  is_paid: boolean;
  is_test_mode?: boolean;
  payment_attempts_exhausted?: boolean;
  payment_attempts_limit?: number;
};

type PaymentStatusResponse = {
  order_id: number;
  status: string;
  payment_attempt_id: number;
  payment_state: string;
  is_paid: boolean;
  qr_expires_at?: string | null;
};

type Props = {
  orderId: number;
  totalAmount: number | string;
  open: boolean;
  onClose: () => void;
  onPaid?: () => void;
  title?: string;
};

export function PaymentDialog({
  orderId,
  totalAmount,
  open,
  onClose,
  onPaid,
  title,
}: Props) {
  const compact = useStorefrontCompact();
  const bottomNav = useStorefrontBottomNav();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [qrPayload, setQrPayload] = useState<string | null>(null);
  const [paid, setPaid] = useState(false);
  const [paymentAttemptId, setPaymentAttemptId] = useState<number | null>(null);
  const paymentAttemptIdRef = useRef<number | null>(null);
  const [qrExpiresAt, setQrExpiresAt] = useState<string | null>(null);
  const [countdownLabel, setCountdownLabel] = useState<string | null>(null);
  const pollingRef = useRef(false);
  const expiryHandledRef = useRef(false);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
  }, []);

  const pollStatus = useCallback(async () => {
    const attemptId = paymentAttemptIdRef.current;
    if (!pollingRef.current || !attemptId) return;
    let lastError: unknown = null;
    for (let attempt = 0; attempt <= PAYMENT_NETWORK_RETRY_DELAYS_MS.length; attempt += 1) {
      if (!pollingRef.current) return;
      try {
        const data = await storefrontApiFetch<PaymentStatusResponse>(
          `/orders/${orderId}/payment/status?payment_attempt_id=${attemptId}`,
        );
        if (!data) return;
        if (isPaymentSuccessState(data.payment_state, data.is_paid)) {
          setPaid(true);
          stopPolling();
          onPaid?.();
          return;
        }
        if (isPaymentFinalErrorState(data.payment_state)) {
          stopPolling();
          setQrDataUrl(null);
          setQrPayload(null);
          setError("Оплата не прошла. Попробуйте снова.");
          return;
        }
        if (!isPaymentWaitingState(data.payment_state)) {
          stopPolling();
          setError("Не удалось завершить оплату. Попробуйте позже.");
          return;
        }
        lastError = null;
        break;
      } catch (e) {
        lastError = e;
        const delay = PAYMENT_NETWORK_RETRY_DELAYS_MS[attempt];
        if (delay && pollingRef.current) {
          await new Promise((resolve) => window.setTimeout(resolve, delay));
        }
      }
    }
    if (lastError && pollingRef.current) {
      setError(userFacingApiErrorMessage(lastError, "Не удалось проверить статус оплаты"));
    }
  }, [onPaid, orderId, stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollingRef.current = true;
    const tick = async () => {
      while (pollingRef.current) {
        await pollStatus();
        if (!pollingRef.current) break;
        await new Promise((resolve) => window.setTimeout(resolve, PAYMENT_POLL_INTERVAL_MS));
      }
    };
    void tick();
  }, [pollStatus, stopPolling]);

  const bootstrapQr = useCallback(
    async (payload: string, attemptId: number, expiresAt: string | null) => {
      paymentAttemptIdRef.current = attemptId;
      setPaymentAttemptId(attemptId);
      setQrExpiresAt(expiresAt);
      expiryHandledRef.current = false;
      setQrPayload(payload);
      const url = await QRCode.toDataURL(payload, {
        margin: 1,
        width: compact ? 220 : 260,
      });
      setQrDataUrl(url);
      startPolling();
    },
    [compact, startPolling],
  );

  const initPayment = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPaid(false);
    setQrDataUrl(null);
    setQrPayload(null);
    setPaymentAttemptId(null);
    paymentAttemptIdRef.current = null;
    setQrExpiresAt(null);
    expiryHandledRef.current = false;
    try {
      const data = await storefrontApiFetch<PaymentInitResponse>(
        `/orders/${orderId}/payment/init`,
        { method: "POST" },
      );
      if (!data) {
        throw new Error("Пустой ответ сервера");
      }
      if (isPaymentSuccessState(data.payment_state, data.is_paid)) {
        setPaid(true);
        onPaid?.();
        return;
      }
      if (isPaymentExhaustedState(data.payment_state) || data.payment_attempts_exhausted) {
        setError(orderPaymentExhaustedText(data.payment_attempts_limit));
        return;
      }
      if (!data.payment_qr_payload) {
        if (isPaymentFinalErrorState(data.payment_state)) {
          setError(
            isPaymentExhaustedState(data.payment_state)
              ? orderPaymentExhaustedText(data.payment_attempts_limit)
              : "Оплата не прошла. Попробуйте снова.",
          );
          return;
        }
        throw new Error("QR-код не получен");
      }
      await bootstrapQr(
        data.payment_qr_payload,
        data.payment_attempt_id,
        data.qr_expires_at ?? null,
      );
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось инициализировать оплату"));
    } finally {
      setLoading(false);
    }
  }, [bootstrapQr, onPaid, orderId]);

  const handleQrExpired = useCallback(async () => {
    if (expiryHandledRef.current) return;
    const attemptId = paymentAttemptIdRef.current;
    if (!attemptId) return;
    expiryHandledRef.current = true;
    stopPolling();
    setQrDataUrl(null);
    setQrPayload(null);
    setCountdownLabel(null);
    try {
      const data = await storefrontApiFetch<PaymentStatusResponse>(
        `/orders/${orderId}/payment/status?payment_attempt_id=${attemptId}`,
      );
      if (data && isPaymentSuccessState(data.payment_state, data.is_paid)) {
        setPaid(true);
        onPaid?.();
        return;
      }
      if (data && isPaymentFinalErrorState(data.payment_state)) {
        setError("Время QR истекло. Оплата не прошла — попробуйте снова.");
        return;
      }
      setError("Время QR истекло. Нажмите «Повторить» для новой попытки.");
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Время QR истекло. Попробуйте снова."));
    }
  }, [onPaid, orderId, stopPolling]);

  useEffect(() => {
    if (!open) {
      stopPolling();
      return;
    }
    void initPayment();
    return () => stopPolling();
  }, [open, initPayment, stopPolling]);

  useEffect(() => {
    if (!qrExpiresAt || paid) {
      setCountdownLabel(null);
      return;
    }
    const tick = () => {
      const remaining = qrCountdownMs(qrExpiresAt);
      if (remaining === null) return;
      if (remaining <= 0) {
        setCountdownLabel("0:00");
        void handleQrExpired();
        return;
      }
      setCountdownLabel(formatCountdown(remaining));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [handleQrExpired, paid, qrExpiresAt]);

  const dialogTitle = paid
    ? "Оплата подтверждена"
    : title || `Оплата заказа №${orderId}`;

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby="payment-dialog-title"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className={
            compact
              ? "fixed inset-0 z-[130] flex items-end justify-center px-3"
              : "fixed inset-0 z-[130] flex items-center justify-center p-4"
          }
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.45)",
            backdropFilter: "blur(6px)",
            ...(compact && bottomNav
              ? { paddingBottom: `calc(${MINIAPP_BOTTOM_NAV_OFFSET} + 0.5rem)` }
              : {}),
          }}
          onClick={onClose}
        >
          <motion.div
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 12, opacity: 0 }}
            className={`relative w-full border border-sp-border bg-sp-surface ${compact ? "max-w-none p-4" : "max-w-md p-6"}`}
            style={{
              borderRadius: compact ? "16px" : "var(--sp-radius-card)",
              boxShadow: "var(--sp-shadow-hover)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3
              id="payment-dialog-title"
              className={`m-0 font-semibold text-sp-text-primary ${compact ? "mb-2 text-[16px]" : "mb-3 text-[20px]"}`}
            >
              {dialogTitle}
            </h3>

            {paid ? (
              <p className="m-0 mb-4 text-sp-text-secondary text-[14px]">
                Спасибо! Оплата заказа #{orderId} успешно подтверждена.
              </p>
            ) : (
              <>
                <p className="m-0 mb-3 text-sp-text-secondary text-[14px]">
                  Сумма к оплате:{" "}
                  <span className="font-semibold text-sp-text-primary">{moneyRub(totalAmount)}</span>
                </p>
                {loading ? (
                  <p className="m-0 mb-4 text-sp-text-secondary text-[14px]">Подготовка QR-кода…</p>
                ) : null}
                {error ? (
                  <p className="m-0 mb-4 text-[14px]" style={{ color: "#ff8b8b" }}>
                    {error}
                  </p>
                ) : null}
                {countdownLabel && qrDataUrl ? (
                  <p className="m-0 mb-3 text-sp-text-secondary text-[13px]">
                    QR действует: <span className="font-medium text-sp-text-primary">{countdownLabel}</span>
                  </p>
                ) : null}
                {qrDataUrl ? (
                  <div className="flex flex-col items-center gap-3 mb-4">
                    <img
                      src={qrDataUrl}
                      alt="QR-код для оплаты СБП"
                      className="rounded-lg border border-sp-border bg-white p-2"
                    />
                    {qrPayload ? (
                      <a
                        href={qrPayload}
                        className="text-[13px] font-medium text-sp-blue underline"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Открыть приложение банка
                      </a>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}

            <div className="flex flex-col gap-2">
              {!paid && error ? (
                <button
                  type="button"
                  onClick={() => void initPayment()}
                  className={compact ? miniAppPillClass(true) : "w-full py-3 font-semibold text-white sp-transition"}
                  style={
                    compact
                      ? undefined
                      : {
                          background: "var(--sp-blue)",
                          borderRadius: "var(--sp-radius-pill)",
                          border: "none",
                        }
                  }
                >
                  Повторить
                </button>
              ) : null}
              <button
                type="button"
                onClick={onClose}
                className={
                  compact
                    ? `${miniAppPillClass(false)} w-full border border-sp-border`
                    : "w-full py-3 font-semibold sp-transition border border-sp-border text-sp-text-primary"
                }
                style={
                  compact
                    ? undefined
                    : { borderRadius: "var(--sp-radius-pill)", background: "transparent" }
                }
              >
                {paid ? "Закрыть" : "Отмена"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
