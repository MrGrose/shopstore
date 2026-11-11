import { describe, expect, it } from "vitest";
import { StorefrontApiError } from "./storefront/api";
import { LOGIN_UNAVAILABLE_CODE } from "./storefront/authErrors";
import {
  GENERIC_ERROR_MESSAGE,
  mapApiErrorToUserMessage,
  mapHttpStatusToUserMessage,
  NETWORK_ERROR_MESSAGE,
  SERVICE_UNAVAILABLE_MESSAGE,
  VALIDATION_ERROR_MESSAGE,
} from "./errorMessages";

const PRESERVED_BUSINESS_MESSAGES = [
  "Недостаточно товара на складе",
  "Промокод недействителен",
  "Часть товаров недоступна.",
  "Неверный код",
  "Подпись Telegram не прошла проверку",
  "Telegram-сессия устарела",
];

describe("mapHttpStatusToUserMessage", () => {
  it("maps 404 to not found", () => {
    expect(mapHttpStatusToUserMessage(404)).toBe("Данные не найдены.");
  });

  it("maps 500 to service unavailable RU", () => {
    expect(mapHttpStatusToUserMessage(500)).toBe(SERVICE_UNAVAILABLE_MESSAGE);
  });

  it("maps 422 to validation RU", () => {
    expect(mapHttpStatusToUserMessage(422)).toBe(VALIDATION_ERROR_MESSAGE);
  });
});

describe("mapApiErrorToUserMessage", () => {
  it("maps HTTP 500 technical message to service unavailable RU", () => {
    expect(
      mapApiErrorToUserMessage(new Error("HTTP 500"), {
        fallback: "Не удалось загрузить корзину",
      }),
    ).toBe(SERVICE_UNAVAILABLE_MESSAGE);
  });

  it("maps HTTP 404 technical message to not found", () => {
    expect(
      mapApiErrorToUserMessage(null, {
        status: 404,
        fallback: "Не удалось загрузить товар",
      }),
    ).toBe("Данные не найдены.");
  });

  it("maps Failed to fetch to network RU", () => {
    expect(mapApiErrorToUserMessage(new TypeError("Failed to fetch"))).toBe(
      NETWORK_ERROR_MESSAGE,
    );
  });

  it.each(PRESERVED_BUSINESS_MESSAGES)("preserves business message: %s", (text) => {
    const err = new StorefrontApiError(text, 400);
    expect(mapApiErrorToUserMessage(err)).toBe(text);
  });

  it("preserves RU business message even with 500 status", () => {
    const err = new StorefrontApiError("Подпись Telegram не прошла проверку", 500);
    expect(mapApiErrorToUserMessage(err)).toBe("Подпись Telegram не прошла проверку");
  });

  it("preserves login_unavailable code for LoginUnavailableMessage flow", () => {
    expect(mapApiErrorToUserMessage(LOGIN_UNAVAILABLE_CODE)).toBe(LOGIN_UNAVAILABLE_CODE);
    expect(
      mapApiErrorToUserMessage(
        new StorefrontApiError(LOGIN_UNAVAILABLE_CODE, 403),
      ),
    ).toBe(LOGIN_UNAVAILABLE_CODE);
  });

  it("maps English Pydantic message to validation RU via status", () => {
    const err = new StorefrontApiError("Field required", 422);
    expect(mapApiErrorToUserMessage(err)).toBe(VALIDATION_ERROR_MESSAGE);
  });

  it("maps unknown technical message to fallback", () => {
    expect(
      mapApiErrorToUserMessage(new Error("unknown"), {
        fallback: "Не удалось загрузить корзину",
      }),
    ).toBe("Не удалось загрузить корзину");
  });
});
