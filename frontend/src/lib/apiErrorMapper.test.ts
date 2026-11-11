import { describe, expect, it } from "vitest";
import {
  extractRawMessage,
  getApiErrorCode,
  isAbortError,
  normalizeApiError,
  NETWORK_ERROR_MESSAGE,
  parseApiErrorDetail,
  SERVICE_UNAVAILABLE_MESSAGE,
  VALIDATION_ERROR_MESSAGE,
} from "./apiErrorMapper";

const TELEGRAM_MSG =
  "Вся коммуникация по заказу будет происходить через Telegram-бота. Для оформления заказа необходимо привязать личный кабинет к вашему Telegram-аккаунту.";

describe("parseApiErrorDetail", () => {
  it("reads FastAPI detail string", () => {
    expect(parseApiErrorDetail({ detail: "Неверный код" })).toBe("Неверный код");
  });

  it("reads FastAPI detail array", () => {
    const detail = [{ loc: ["body", "phone"], msg: "Обязательное поле", type: "value_error" }];
    expect(parseApiErrorDetail({ detail })).toEqual(detail);
  });

  it("reads message and error fallbacks", () => {
    expect(parseApiErrorDetail({ message: "Server busy" })).toBe("Server busy");
    expect(parseApiErrorDetail({ error: "bad gateway" })).toBe("bad gateway");
  });

  it("reads structured FastAPI detail with code and message", () => {
    const detail = {
      code: "telegram_required",
      message: "Привяжите Telegram",
    };
    expect(parseApiErrorDetail({ detail })).toEqual(detail);
    expect(extractRawMessage(detail)).toBe("Привяжите Telegram");
    expect(getApiErrorCode(detail)).toBe("telegram_required");
  });
});

describe("normalizeApiError", () => {
  it("maps network cause to network message", () => {
    const normalized = normalizeApiError({
      status: 0,
      cause: new TypeError("Failed to fetch"),
    });
    expect(normalized.userMessage).toBe(NETWORK_ERROR_MESSAGE);
  });

  it("maps 503 HTTP body to service unavailable", () => {
    const normalized = normalizeApiError({
      status: 503,
      body: { detail: "Internal Server Error" },
    });
    expect(normalized.userMessage).toBe(SERVICE_UNAVAILABLE_MESSAGE);
    expect(normalized.rawMessage).toBe("Internal Server Error");
  });

  it("preserves RU business detail", () => {
    const normalized = normalizeApiError({
      status: 400,
      body: { detail: "Промокод недействителен" },
    });
    expect(normalized.userMessage).toBe("Промокод недействителен");
    expect(normalized.apiDetail).toBe("Промокод недействителен");
  });

  it("maps pydantic array to validation message", () => {
    const normalized = normalizeApiError({
      status: 422,
      body: {
        detail: [{ loc: ["body", "email"], msg: "Field required", type: "missing" }],
      },
    });
    expect(normalized.userMessage).toBe(VALIDATION_ERROR_MESSAGE);
    expect(extractRawMessage(normalized.apiDetail)).toContain("Field required");
  });

  it("preserves login_unavailable", () => {
    const normalized = normalizeApiError({
      status: 403,
      body: { detail: "login_unavailable" },
    });
    expect(normalized.userMessage).toBe("login_unavailable");
  });

  it("maps telegram_required structured detail to business message", () => {
    const normalized = normalizeApiError({
      status: 409,
      body: {
        detail: {
          code: "telegram_required",
          message: TELEGRAM_MSG,
        },
      },
    });
    expect(normalized.userMessage).toBe(TELEGRAM_MSG);
    expect(getApiErrorCode(normalized.apiDetail)).toBe("telegram_required");
  });
});

describe("isAbortError", () => {
  it("detects AbortError", () => {
    expect(isAbortError(new DOMException("Aborted", "AbortError"))).toBe(true);
    expect(isAbortError(new Error("Failed to fetch"))).toBe(false);
  });
});
