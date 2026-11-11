import { storefrontApiFetch } from "./api";
import { normalizeRuMobilePhone } from "./phone";
import type { StorefrontUser } from "./session";

export type PhoneAuthChannel =
  | "flash_call"
  | "voice_code"
  | "verification_number";

export type PhoneCallFlow = {
  flow_id: string;
  channel: PhoneAuthChannel;
  status: "pending" | "verified" | "failed" | "expired" | "cancelled" | "used";
  expires_in: number;
  retry_after: number;
  can_retry: boolean;
  call_started: boolean;
  next_channel?: PhoneAuthChannel | null;
  verification_phone_number?: string | null;
};

export type PhoneLoginResult = {
  access_token: string;
  is_new_user: boolean;
  user?: StorefrontUser;
};

function rememberLogin(data: PhoneLoginResult): PhoneLoginResult {
  if (data?.access_token) localStorage.setItem("access_token", data.access_token);
  return data;
}

// Запускает первый звонок phone auth flow.
export async function startPhoneCall(phone: string): Promise<PhoneCallFlow> {
  const normalized = normalizeRuMobilePhone(phone);
  if (!normalized) throw new Error("Укажите российский мобильный номер (+79991234567)");
  return storefrontApiFetch<PhoneCallFlow>("/auth/phone/start", {
    method: "POST",
    body: JSON.stringify({ phone: normalized }),
  });
}

// Загружает состояние flow и обновляет статус проверочного звонка.
export function getPhoneCallStatus(flowId: string): Promise<PhoneCallFlow> {
  return storefrontApiFetch<PhoneCallFlow>(`/auth/phone/${flowId}`);
}

// Повторяет текущий способ после cooldown.
export function retryPhoneCall(flowId: string): Promise<PhoneCallFlow> {
  return storefrontApiFetch<PhoneCallFlow>(`/auth/phone/${flowId}/retry`, {
    method: "POST",
  });
}

// Вручную включает следующий способ каскада.
export function switchPhoneCall(flowId: string): Promise<PhoneCallFlow> {
  return storefrontApiFetch<PhoneCallFlow>(`/auth/phone/${flowId}/switch`, {
    method: "POST",
  });
}

// Проверяет четырёхзначный код и выполняет login.
export async function verifyPhoneCall(
  flowId: string,
  code: string,
): Promise<PhoneLoginResult> {
  const data = await storefrontApiFetch<PhoneLoginResult>(
    `/auth/phone/${flowId}/verify`,
    { method: "POST", body: JSON.stringify({ code: code.trim() }) },
  );
  return rememberLogin(data);
}

// Завершает подтверждённый звонок на проверочный номер.
export async function completePhoneCall(flowId: string): Promise<PhoneLoginResult> {
  const data = await storefrontApiFetch<PhoneLoginResult>(
    `/auth/phone/${flowId}/complete`,
    { method: "POST" },
  );
  return rememberLogin(data);
}

// Проверяет verification code через Telegram Gateway и сохраняет сессию.
export async function verifyPhoneCode(
  phone: string,
  code: string,
): Promise<PhoneLoginResult> {
  const data = await storefrontApiFetch<PhoneLoginResult>("/auth/phone/verify", {
    method: "POST",
    body: JSON.stringify({ phone: normalizeRuMobilePhone(phone), code: code.trim() }),
  });
  return rememberLogin(data);
}
