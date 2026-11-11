import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { LoginUnavailableMessage } from "../components/auth/LoginUnavailableMessage";
import { SpacedOtpInput } from "../components/ui/input-otp";
import {
  LoginPageShell,
  LoginSubmitButton,
  loginInputStyle,
  loginLegalLinkStyle,
  loginLinkButtonStyle,
} from "../components/auth/LoginPageShell";
import { isLoginUnavailableError, isLoginUnavailableMessage } from "../../lib/storefront/authErrors";
import { openStoreLegal } from "../../lib/storefront/legal";
import { StorefrontApiError, storefrontApiFetch } from "../../lib/storefront/api";
import { mapApiErrorToUserMessage } from "../../lib/errorMessages";
import {
  completePhoneCall,
  getPhoneCallStatus,
  retryPhoneCall,
  startPhoneCall,
  switchPhoneCall,
  verifyPhoneCall,
  verifyPhoneCode,
  type PhoneCallFlow,
} from "../../lib/storefront/phoneAuth";
import { validateRuMobilePhone } from "../../lib/storefront/phone";
import {
  loginHintForNext,
  resolvePhonePostLogin,
  resolvePostLoginNavigation,
  runPostLoginEffect,
  safeLoginNext,
  type PostLoginEffect,
} from "../../lib/storefront/session";
import { invalidateUserQuery } from "../../hooks/useUser";

function formatPhoneForDisplay(value: string | null | undefined): string {
  const digits = String(value ?? "").replace(/\D/g, "");
  if (digits.length !== 11) return value ?? "";
  return `+${digits[0]} ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
}

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const next = safeLoginNext(searchParams.get("next"));
  const rawNext = searchParams.get("next");
  const [status, setStatus] = useState<string | null>(null);
  const [statusTone, setStatusTone] = useState<"success" | "error" | null>(null);
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [phoneFlow, setPhoneFlow] = useState<PhoneCallFlow | null>(null);
  const [phoneAuthMethod, setPhoneAuthMethod] = useState<"calls" | "code">("calls");
  const [phoneVerificationCodeEnabled, setPhoneVerificationCodeEnabled] = useState(false);
  const [retrySeconds, setRetrySeconds] = useState(0);
  const [flowExpiresSeconds, setFlowExpiresSeconds] = useState(0);
  const [verificationQr, setVerificationQr] = useState<string | null>(null);
  const [verificationQrExpanded, setVerificationQrExpanded] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [loginUnavailable, setLoginUnavailable] = useState(false);
  useEffect(() => {
    void storefrontApiFetch<{
      phone_verification_code_enabled?: boolean;
    }>("/storefront/social")
      .then((data) => {
        setPhoneVerificationCodeEnabled(data?.phone_verification_code_enabled === true);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const flowId = localStorage.getItem("phone_call_flow_id");
    if (!flowId) return;
    void getPhoneCallStatus(flowId)
      .then((flow) => {
        if (flow.status === "pending" || flow.status === "verified") {
          setPhoneFlow(flow);
          setOtpSent(true);
          setRetrySeconds(flow.retry_after);
        } else {
          localStorage.removeItem("phone_call_flow_id");
        }
      })
      .catch(() => localStorage.removeItem("phone_call_flow_id"));
  }, []);

  useEffect(() => {
    if (retrySeconds <= 0) return;
    const timer = window.setInterval(
      () => setRetrySeconds((seconds) => Math.max(0, seconds - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [retrySeconds]);

  useEffect(() => {
    setFlowExpiresSeconds(phoneFlow?.expires_in ?? 0);
  }, [phoneFlow?.flow_id, phoneFlow?.expires_in]);

  useEffect(() => {
    if (flowExpiresSeconds <= 0) return;
    const timer = window.setTimeout(
      () => setFlowExpiresSeconds((seconds) => Math.max(0, seconds - 1)),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [flowExpiresSeconds]);

  useEffect(() => {
    if (!phoneFlow) return;
    const expiresInMs = Math.max(0, phoneFlow.expires_in) * 1000;
    const timer = window.setTimeout(() => resetOtpMode(), expiresInMs);
    return () => window.clearTimeout(timer);
  }, [phoneFlow?.flow_id, phoneFlow?.expires_in]);

  useEffect(() => {
    if (phoneFlow?.channel !== "verification_number" || phoneFlow.status !== "pending") {
      return;
    }
    const timer = window.setInterval(() => {
      void getPhoneCallStatus(phoneFlow.flow_id).then(async (flow) => {
        setPhoneFlow(flow);
        if (flow.status === "verified") {
          await completePhoneCall(flow.flow_id);
          localStorage.removeItem("phone_call_flow_id");
          await afterLogin({ navigation: resolvePhonePostLogin(rawNext) });
        } else if (flow.status === "failed" || flow.status === "expired") {
          localStorage.removeItem("phone_call_flow_id");
          setStatus("Не удалось подтвердить номер. Попробуйте позже.");
          setStatusTone("error");
        }
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [phoneFlow?.channel, phoneFlow?.flow_id, phoneFlow?.status, rawNext]);

  useEffect(() => {
    const number = phoneFlow?.verification_phone_number;
    if (phoneFlow?.channel !== "verification_number" || !number) {
      setVerificationQr(null);
      setVerificationQrExpanded(false);
      return;
    }
    void QRCode.toDataURL(`tel:${number}`, {
      width: 192,
      margin: 1,
      color: { dark: "#0e0e0e", light: "#ffffff" },
      errorCorrectionLevel: "M",
    }).then(setVerificationQr);
  }, [phoneFlow?.channel, phoneFlow?.verification_phone_number]);

  async function requestPhoneCode() {
    const phoneError = validateRuMobilePhone(phone);
    if (phoneError) {
      setStatus(phoneError);
      setStatusTone("error");
      return;
    }
    setAuthLoading(true);
    setStatus(null);
    setStatusTone(null);
    setLoginUnavailable(false);
    try {
      const result = await startPhoneCall(phone);
      setPhoneFlow(result);
      setRetrySeconds(result.retry_after);
      localStorage.setItem("phone_call_flow_id", result.flow_id);
      setOtpSent(true);
      setOtpCode("");
      setStatus(null);
      setStatusTone(null);
    } catch (e) {
      if (isLoginUnavailableError(e)) {
        setLoginUnavailable(true);
        setStatus(null);
        setStatusTone(null);
        return;
      }
      const msg = mapApiErrorToUserMessage(e, {
        fallback: "Не удалось отправить код",
      });
      if (isLoginUnavailableMessage(msg)) {
        setLoginUnavailable(true);
        setStatus(null);
        setStatusTone(null);
        return;
      }
      setStatus(msg);
      setStatusTone("error");
    } finally {
      setAuthLoading(false);
    }
  }

  async function requestPhoneVerificationCode() {
    const phoneError = validateRuMobilePhone(phone);
    if (phoneError) {
      setStatus(phoneError);
      setStatusTone("error");
      return;
    }
    setAuthLoading(true);
    setStatus(null);
    setStatusTone(null);
    try {
      const result = await storefrontApiFetch<{ expires_in: number }>("/auth/phone/send-code", {
        method: "POST",
        body: JSON.stringify({ phone }),
      });
      setPhoneFlow(null);
      setOtpSent(true);
      setOtpCode("");
      setFlowExpiresSeconds(result.expires_in);
    } catch (e) {
      setStatus(mapApiErrorToUserMessage(e, { fallback: "Не удалось отправить код" }));
      setStatusTone("error");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSendPhoneCode(event: FormEvent) {
    event.preventDefault();
    await (phoneAuthMethod === "code" ? requestPhoneVerificationCode() : requestPhoneCode());
  }

  async function handleVerifyPhoneCode(event: FormEvent) {
    event.preventDefault();
    setAuthLoading(true);
    setStatus(null);
    setStatusTone(null);
    try {
      if (phoneAuthMethod === "code") {
        await verifyPhoneCode(phone, otpCode);
        await afterLogin({ navigation: resolvePhonePostLogin(rawNext) });
        return;
      }
      if (!phoneFlow) throw new Error("Подтверждение не найдено");
      await verifyPhoneCall(phoneFlow.flow_id, otpCode);
      localStorage.removeItem("phone_call_flow_id");
      await afterLogin({ navigation: resolvePhonePostLogin(rawNext) });
    } catch (e) {
      if (isLoginUnavailableError(e)) {
        setLoginUnavailable(true);
        setStatus(null);
        setStatusTone(null);
        return;
      }
      const msg = mapApiErrorToUserMessage(e, {
        fallback: "Неверный или устаревший код",
      });
      if (isLoginUnavailableMessage(msg)) {
        setLoginUnavailable(true);
        setStatus(null);
        setStatusTone(null);
        return;
      }
      setStatus(msg);
      setStatusTone("error");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleRetryPhoneCall() {
    if (!phoneFlow) return;
    setAuthLoading(true);
    setStatus(null);
    try {
      const flow = await retryPhoneCall(phoneFlow.flow_id);
      setPhoneFlow(flow);
      setRetrySeconds(flow.retry_after);
      setOtpCode("");
    } catch (e) {
      setStatus(mapApiErrorToUserMessage(e, { fallback: "Не удалось повторить звонок" }));
      setStatusTone("error");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSwitchPhoneCall() {
    if (!phoneFlow) return;
    setAuthLoading(true);
    setStatus(null);
    try {
      const flow = await switchPhoneCall(phoneFlow.flow_id);
      setPhoneFlow(flow);
      setRetrySeconds(flow.retry_after);
      setOtpCode("");
    } catch (e) {
      setStatus(mapApiErrorToUserMessage(e, { fallback: "Не удалось сменить способ" }));
      setStatusTone("error");
    } finally {
      setAuthLoading(false);
    }
  }

  function resetOtpMode() {
    setOtpSent(false);
    setOtpCode("");
    setStatus(null);
    setStatusTone(null);
    setPhoneFlow(null);
    setRetrySeconds(0);
    setFlowExpiresSeconds(0);
    localStorage.removeItem("phone_call_flow_id");
  }

  async function afterLogin(opts?: {
    navigation?: { path: string; effect?: PostLoginEffect };
  }) {
    await invalidateUserQuery(queryClient);
    window.dispatchEvent(new CustomEvent("telegram-auth-success"));
    setStatus("Вход выполнен.");
    setStatusTone("success");
    const { path, effect } =
      opts?.navigation ?? resolvePostLoginNavigation(next);
    window.setTimeout(() => {
      navigate(path, { replace: true });
      if (effect) {
        window.setTimeout(() => runPostLoginEffect(effect), 50);
      }
    }, 150);
  }

  const hasInlinePhoneStatus = phoneFlow && !loginUnavailable;
  const statusArea = hasInlinePhoneStatus ? null :
    loginUnavailable || isLoginUnavailableMessage(status) ? (
      <div className="text-[0.95rem] leading-relaxed" style={{ color: "var(--destructive)" }}>
        <LoginUnavailableMessage />
      </div>
    ) : status ? (
      <p
        style={{
          color:
            statusTone === "error"
              ? "var(--destructive)"
              : statusTone === "success"
                ? "var(--sp-green)"
                : "#6b6b6b",
          fontSize: "0.95rem",
          margin: 0,
        }}
      >
        {status}
      </p>
    ) : null;

  const legalFooter = (
    <>
      Продолжая, вы подтверждаете, что ознакомились с{" "}
      <button
        type="button"
        style={loginLegalLinkStyle}
        onClick={() => openStoreLegal("/privacy", "Политика конфиденциальности")}
      >
        Политикой конфиденциальности
      </button>
      .
    </>
  );

  let primaryAuth: ReactNode;

    const verificationPhone = phoneFlow?.verification_phone_number;
    const verificationPhoneDisplay = formatPhoneForDisplay(verificationPhone);
    const channelTitle =
      phoneFlow?.channel === "voice_code"
        ? "Сейчас вам позвонит робот"
        : phoneFlow?.channel === "verification_number"
          ? verificationPhoneDisplay
            ? `Позвоните на бесплатный номер ${verificationPhoneDisplay} или воспользуйтесь QR-кодом`
            : "Позвоните на бесплатный номер или воспользуйтесь QR-кодом"
          : "Вам поступит звонок";
    const channelText =
      phoneFlow?.channel === "voice_code"
        ? "Ответьте на звонок и введите код, который продиктует робот."
        : "Введите последние 4 цифры номера входящего звонка. Отвечать не нужно.";
    const phoneFlowMessage = status
      ? status
      : phoneFlow?.status === "failed"
        ? "Не удалось подтвердить номер. Попробуйте позже."
        : phoneFlow?.status === "expired"
          ? "Время входа истекло. Введите номер телефона ещё раз."
        : phoneFlow && !phoneFlow.call_started && phoneFlow.channel !== "verification_number"
          ? "Не удалось запустить звонок. Выберите следующий способ."
          : null;
    primaryAuth = (
      <form
        className="flex flex-col gap-3 w-full"
        onSubmit={otpSent ? handleVerifyPhoneCode : handleSendPhoneCode}
      >
        {!otpSent ? (
        <input
          type="tel"
          required
          autoComplete="tel"
          placeholder="Номер телефона"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          disabled={otpSent || authLoading}
          style={loginInputStyle}
        />
        ) : null}
        {phoneVerificationCodeEnabled && !otpSent ? (
          <button
            type="button"
            style={loginLinkButtonStyle}
            onClick={() => {
              setPhoneAuthMethod("code");
              resetOtpMode();
            }}
          >
            Войти по коду через Telegram
          </button>
        ) : null}
        {phoneAuthMethod === "code" && !otpSent ? (
          <button
            type="button"
            style={loginLinkButtonStyle}
            onClick={() => {
              setPhoneAuthMethod("calls");
              resetOtpMode();
            }}
          >
            Войти по звонку
          </button>
        ) : null}
        {phoneAuthMethod === "code" && otpSent ? (
          <div className="text-center text-sm text-muted-foreground">
            Введите код, отправленный в Telegram.
          </div>
        ) : null}
        {phoneAuthMethod === "code" && otpSent ? (
          <SpacedOtpInput
            tone="login"
            maxLength={6}
            value={otpCode}
            onChange={setOtpCode}
            disabled={authLoading}
            aria-label="6-значный код"
            className="mx-auto"
          />
        ) : null}
        {otpSent && phoneFlow ? (
          <div className="flex w-full flex-col items-center gap-3 text-center">
            <h2 className="text-xl font-semibold">{channelTitle}</h2>
            {phoneFlowMessage ? (
              <p
                className="max-w-[320px] text-sm leading-relaxed"
                style={{
                  color:
                    statusTone === "success" ? "var(--sp-green)" : "var(--destructive)",
                }}
              >
                {phoneFlowMessage}
              </p>
            ) : null}
            {phoneFlow.channel === "verification_number" ? (
              <div className="flex w-full flex-col items-center gap-4 rounded-2xl border border-black/5 bg-white/70 px-5 py-5 shadow-sm">
                <p className="max-w-[300px] text-sm leading-relaxed text-muted-foreground">
                  Отвечать и разговаривать не нужно.
                </p>
                {verificationQr ? (
                  <div className="hidden flex-col items-center gap-3 sm:flex">
                    <button
                      type="button"
                      className="cursor-zoom-in rounded-xl bg-white p-2 shadow-sm transition-transform hover:scale-[1.03]"
                      aria-label="Увеличить QR-код"
                      onClick={() => setVerificationQrExpanded(true)}
                    >
                      <img
                        src={verificationQr}
                        width={112}
                        height={112}
                        alt="QR-код для звонка на проверочный номер"
                      />
                    </button>
                    <p className="text-xs text-muted-foreground">
                      Нажмите на QR-код, чтобы увеличить
                    </p>
                  </div>
                ) : null}
                {verificationPhone ? (
                  <a
                    className="flex min-h-12 w-full items-center justify-center rounded-xl bg-primary px-5 text-base font-semibold text-white no-underline sm:hidden"
                    href={`tel:${verificationPhone}`}
                  >
                    Позвонить бесплатно
                  </a>
                ) : null}
                {retrySeconds > 0 ? (
                  <p className="text-sm tabular-nums text-muted-foreground">
                    Ожидаем звонок — {String(Math.floor(retrySeconds / 60)).padStart(2, "0")}:
                    {String(retrySeconds % 60).padStart(2, "0")}
                  </p>
                ) : phoneFlow.can_retry ? (
                  <button
                    type="button"
                    disabled={authLoading}
                    className="min-h-11 w-full rounded-xl border border-primary/20 bg-primary/5 px-5 text-sm font-semibold text-primary sm:max-w-[280px]"
                    onClick={() => void handleRetryPhoneCall()}
                  >
                    Повторить звонок
                  </button>
                ) : null}
                <p className="text-xs text-muted-foreground sm:hidden">
                  Номер откроется в приложении телефона.
                </p>
              </div>
            ) : phoneFlow.call_started ? (
              <p className="text-sm text-muted-foreground">{channelText}</p>
            ) : null}
            {verificationQr && verificationQrExpanded ? (
              <button
                type="button"
                className="fixed inset-0 z-50 hidden cursor-zoom-out items-center justify-center bg-black/55 p-6 backdrop-blur-sm sm:flex"
                aria-label="Закрыть увеличенный QR-код"
                onClick={() => setVerificationQrExpanded(false)}
              >
                <span className="flex max-w-sm flex-col items-center gap-4 rounded-3xl bg-white p-6 shadow-2xl">
                  <img
                    src={verificationQr}
                    width={300}
                    height={300}
                    alt="Увеличенный QR-код для звонка на проверочный номер"
                  />
                  <span className="text-sm text-muted-foreground">
                    Наведите камеру телефона на QR-код
                  </span>
                </span>
              </button>
            ) : null}
          </div>
        ) : null}
        {otpSent &&
        phoneFlow?.call_started &&
        phoneFlow.channel !== "verification_number" ? (
          <SpacedOtpInput
            tone="login"
            maxLength={4}
            value={otpCode}
            onChange={setOtpCode}
            disabled={authLoading}
            aria-label="4 цифры входящего звонка"
            className="mx-auto"
          />
        ) : null}
        {!phoneFlow ||
        (phoneFlow.call_started && phoneFlow.channel !== "verification_number") ? (
        <LoginSubmitButton disabled={authLoading}>
          {authLoading
            ? "Подождите…"
            : otpSent
              ? "Подтвердить код"
              : phoneAuthMethod === "code"
                ? "Отправить код"
                : "Позвонить"}
        </LoginSubmitButton>
        ) : null}
        {otpSent &&
        phoneFlow?.can_retry &&
        phoneFlow.channel !== "verification_number" ? (
          <button
            type="button"
            disabled={authLoading || retrySeconds > 0}
            style={{ ...loginLinkButtonStyle, opacity: authLoading ? 0.6 : 1 }}
            onClick={() => void handleRetryPhoneCall()}
          >
            {retrySeconds > 0 ? `Повторить через ${retrySeconds} сек.` : "Повторить звонок"}
          </button>
        ) : null}
        {otpSent && phoneFlow?.next_channel ? (
          <button
            type="button"
            disabled={authLoading || retrySeconds > 0}
            style={{
              ...loginLinkButtonStyle,
              opacity: authLoading || retrySeconds > 0 ? 0.6 : 1,
            }}
            onClick={() => void handleSwitchPhoneCall()}
          >
            {phoneFlow.next_channel === "voice_code"
              ? "Получить звонок с диктовкой кода"
              : "Позвонить на проверочный номер"}
          </button>
        ) : null}
        {otpSent && flowExpiresSeconds > 0 && flowExpiresSeconds <= 60 ? (
          <p className="text-center text-xs tabular-nums text-muted-foreground">
            Сеанс входа завершится через 00:{String(flowExpiresSeconds).padStart(2, "0")}
          </p>
        ) : null}
      </form>
    );

  return (
    <LoginPageShell
      hintText={loginHintForNext(next)}
      statusArea={statusArea}
      legalFooter={legalFooter}
    >
      {primaryAuth}
    </LoginPageShell>
  );
}
