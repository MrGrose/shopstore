import { StorefrontApiError } from "./api";

export const LOGIN_UNAVAILABLE_CODE = "login_unavailable";

function matchesLoginUnavailable(value: unknown): boolean {
  return value === LOGIN_UNAVAILABLE_CODE;
}

export function isLoginUnavailableError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return typeof error === "string" && matchesLoginUnavailable(error);
  }
  const err = error as {
    message?: string;
    apiDetail?: unknown;
  };
  if (matchesLoginUnavailable(err.message)) return true;
  if (matchesLoginUnavailable(err.apiDetail)) return true;
  if (error instanceof StorefrontApiError) {
    return (
      matchesLoginUnavailable(error.message) ||
      matchesLoginUnavailable(error.apiDetail)
    );
  }
  return false;
}

export function isLoginUnavailableMessage(message: string | null | undefined): boolean {
  return matchesLoginUnavailable(message?.trim());
}
