import { LOGIN_UNAVAILABLE_CODE } from "./storefront/authErrors";

export const GENERIC_ERROR_MESSAGE = "Что-то пошло не так. Попробуйте ещё раз.";
export const NETWORK_ERROR_MESSAGE =
  "Проверьте подключение к интернету и попробуйте снова.";
export const SERVICE_UNAVAILABLE_MESSAGE =
  "Сервис временно недоступен. Попробуйте позже.";
export const VALIDATION_ERROR_MESSAGE = "Проверьте введённые данные.";

export type PydanticIssue = { loc?: unknown[]; msg?: string; type?: string };
export type StructuredApiErrorDetail = { code?: string; message?: string };
export type ApiErrorDetail = string | PydanticIssue[] | StructuredApiErrorDetail;

export type MapApiErrorOptions = {
  fallback?: string;
  status?: number;
};

export type NormalizedApiError = {
  status: number;
  apiDetail: ApiErrorDetail | undefined;
  rawMessage: string;
  userMessage: string;
};

const TECHNICAL_PATTERNS: RegExp[] = [
  /^HTTP\s+\d{3}$/i,
  /^Failed to load\b/i,
  /^Internal Server Error$/i,
  /^Failed to fetch$/i,
  /^NetworkError/i,
  /^ECONNRESET$/i,
  /^ECONNREFUSED$/i,
  /^ETIMEDOUT$/i,
  /^timeout\b/i,
  /^Ошибка API$/,
  /^unknown$/i,
  /Traceback/i,
  /^\s*[\[{]/,
];

const PYDANTIC_EN_SNIPPETS = [
  "Field required",
  "String should have",
  "Input should be",
  "Value error",
  "ensure this value",
  "type=value_error",
];

const NETWORK_CAUSE_SNIPPETS = [
  "failed to fetch",
  "networkerror",
  "network error",
  "econnreset",
  "econnrefused",
  "etimedout",
  "timeout",
];

function hasCyrillic(text: string): boolean {
  return /[\u0400-\u04FF]/.test(text);
}

function looksLikePydanticEnglish(message: string): boolean {
  return PYDANTIC_EN_SNIPPETS.some((snippet) => message.includes(snippet));
}

function causeMessage(cause: unknown): string {
  if (cause instanceof Error) return cause.message.trim();
  if (typeof cause === "string") return cause.trim();
  return "";
}

// True для HTTP-кодов, EN Pydantic, JSON/traceback и прочего «технического» текста.
export function isTechnicalErrorMessage(message: string): boolean {
  const trimmed = String(message || "").trim();
  if (!trimmed) return true;
  if (trimmed === LOGIN_UNAVAILABLE_CODE) return false;
  if (TECHNICAL_PATTERNS.some((pattern) => pattern.test(trimmed))) return true;
  if (looksLikePydanticEnglish(trimmed)) return true;
  if (hasCyrillic(trimmed)) return false;
  return true;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function isNetworkCause(cause: unknown): boolean {
  const message = causeMessage(cause).toLowerCase();
  if (!message) return false;
  return NETWORK_CAUSE_SNIPPETS.some((snippet) => message.includes(snippet));
}

function isStructuredApiErrorDetail(value: unknown): value is StructuredApiErrorDetail {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.code === "string" || typeof record.message === "string";
}

// Достаёт detail/message/error из JSON-тела ответа API.
export function parseApiErrorDetail(body: unknown): ApiErrorDetail | undefined {
  if (body == null) return undefined;
  if (typeof body === "string") return body;
  if (Array.isArray(body)) return body as ApiErrorDetail;
  if (typeof body !== "object") return undefined;

  const record = body as Record<string, unknown>;
  if ("detail" in record) {
    const detail = record.detail;
    if (typeof detail === "string" || Array.isArray(detail)) {
      return detail as ApiErrorDetail;
    }
    if (isStructuredApiErrorDetail(detail)) {
      return detail;
    }
    if (detail != null) return String(detail);
  }
  if (typeof record.message === "string" && record.message.trim()) {
    return record.message.trim();
  }
  if (typeof record.error === "string" && record.error.trim()) {
    return record.error.trim();
  }
  return undefined;
}

// Собирает сырое текстовое представление detail до sanitization.
export function extractRawMessage(detail: unknown): string {
  if (!detail) return "Ошибка API";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const raw = String((item as PydanticIssue).msg || "");
          return raw.replace(/^Value error,\s*/i, "").trim() || raw;
        }
        return JSON.stringify(item);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (typeof detail === "object") {
    const structured = detail as StructuredApiErrorDetail;
    const message = String(structured.message || "").trim();
    if (message) return message;
    const code = String(structured.code || "").trim();
    if (code) return code;
  }
  return "Ошибка API";
}

// Возвращает machine-readable code из structured detail.
export function getApiErrorCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return undefined;
  const code = (detail as StructuredApiErrorDetail).code;
  return typeof code === "string" && code.trim() ? code.trim() : undefined;
}

export function mapHttpStatusToUserMessage(status: number): string {
  if (status === 401) return "Войдите в аккаунт, чтобы продолжить.";
  if (status === 403) return "Недостаточно прав для этого действия.";
  if (status === 404) return "Данные не найдены.";
  if (status === 422) return VALIDATION_ERROR_MESSAGE;
  if (status === 500 || status === 502 || status === 503 || status === 504) {
    return SERVICE_UNAVAILABLE_MESSAGE;
  }
  return GENERIC_ERROR_MESSAGE;
}

export function sanitizeApiErrorMessage(
  raw: string,
  status: number,
  options?: { fallback?: string },
): string {
  const fallback = options?.fallback ?? GENERIC_ERROR_MESSAGE;
  const trimmed = String(raw || "").trim();

  if (trimmed === LOGIN_UNAVAILABLE_CODE) return LOGIN_UNAVAILABLE_CODE;
  if (trimmed && !isTechnicalErrorMessage(trimmed)) return trimmed;
  if (status > 0) return mapHttpStatusToUserMessage(status);
  return fallback;
}

// Нормализует HTTP/network ошибку в userMessage + raw apiDetail.
export function normalizeApiError(input: {
  status: number;
  body?: unknown;
  cause?: unknown;
  fallback?: string;
}): NormalizedApiError {
  if (input.cause != null && isNetworkCause(input.cause)) {
    const rawMessage = causeMessage(input.cause) || "Failed to fetch";
    return {
      status: input.status,
      apiDetail: undefined,
      rawMessage,
      userMessage: NETWORK_ERROR_MESSAGE,
    };
  }

  const apiDetail = input.body != null ? parseApiErrorDetail(input.body) : undefined;
  const rawMessage = extractRawMessage(apiDetail);
  const userMessage = sanitizeApiErrorMessage(rawMessage, input.status, {
    fallback: input.fallback,
  });

  return {
    status: input.status,
    apiDetail,
    rawMessage,
    userMessage,
  };
}

function readStorefrontApiError(
  error: unknown,
): { message: string; status: number } | null {
  if (!error || typeof error !== "object") return null;
  const err = error as {
    name?: string;
    message?: string;
    userMessage?: string;
    status?: number;
  };
  if (err.name !== "StorefrontApiError") return null;
  return {
    message: String(err.userMessage ?? err.message ?? "").trim(),
    status: Number(err.status ?? 0),
  };
}

function extractStatus(error: unknown, status?: number): number | undefined {
  if (typeof status === "number" && status > 0) return status;
  const storefront = readStorefrontApiError(error);
  if (storefront && storefront.status > 0) return storefront.status;
  if (error instanceof Error) {
    const match = error.message.trim().match(/^HTTP\s+(\d{3})$/i);
    if (match) return Number(match[1]);
  }
  return undefined;
}

// Превращает API/сетевую ошибку в человекочитаемый RU-текст; business messages сохраняет.
export function mapApiErrorToUserMessage(
  error: unknown,
  options?: MapApiErrorOptions,
): string {
  const fallback = options?.fallback ?? GENERIC_ERROR_MESSAGE;

  if (typeof error === "string" && error.trim() === LOGIN_UNAVAILABLE_CODE) {
    return LOGIN_UNAVAILABLE_CODE;
  }

  const storefront = readStorefrontApiError(error);
  let message = "";
  if (storefront) {
    message = storefront.message;
  } else if (error instanceof Error) {
    message = error.message.trim();
  } else if (typeof error === "string") {
    message = error.trim();
  }

  if (message === LOGIN_UNAVAILABLE_CODE) return LOGIN_UNAVAILABLE_CODE;

  if (isNetworkCause(error) || (message && isNetworkCause(new Error(message)))) {
    return NETWORK_ERROR_MESSAGE;
  }

  if (message && !isTechnicalErrorMessage(message)) {
    return message;
  }

  const status = extractStatus(error, options?.status);
  if (status != null) {
    return mapHttpStatusToUserMessage(status);
  }

  return fallback;
}

// Текст для UI catch: sanitized StorefrontApiError или fallback mapper.
export function userFacingApiErrorMessage(
  error: unknown,
  fallback: string,
): string {
  const storefront = readStorefrontApiError(error);
  if (storefront?.message) return storefront.message;
  return mapApiErrorToUserMessage(error, { fallback });
}
