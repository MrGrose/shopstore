/**
 * HTTP-клиент витрины. Поведение как src/static/site/js/storefront-api.js + tg-login.js.
 * Визуал не трогаем — только контракт с бэкендом.
 */

import {
  extractRawMessage,
  isAbortError,
  normalizeApiError,
  type ApiErrorDetail,
} from "../apiErrorMapper";

export type StorefrontApiErrorDetail =
  | string
  | Array<{ loc?: unknown[]; msg?: string; type?: string }>
  | { code?: string; message?: string };

export function formatStorefrontApiDetail(detail: unknown): string {
  return extractRawMessage(detail);
}

export class StorefrontApiError extends Error {
  public readonly userMessage: string;

  constructor(
    userMessage: string,
    public readonly status: number,
    public readonly apiDetail?: StorefrontApiErrorDetail,
    public readonly rawMessage?: string,
  ) {
    super(userMessage);
    this.name = "StorefrontApiError";
    this.userMessage = userMessage;
  }
}

function authHeaders(options: RequestInit = {}): HeadersInit {
  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("access_token")
      : null;
  const headers = new Headers(options.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isFormData && options.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

function throwStorefrontApiError(status: number, body: unknown): never {
  const normalized = normalizeApiError({ status, body });
  throw new StorefrontApiError(
    normalized.userMessage,
    normalized.status,
    normalized.apiDetail as StorefrontApiErrorDetail | undefined,
    normalized.rawMessage,
  );
}

async function storefrontRequest(path: string, options: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(path, {
      ...options,
      credentials: "include",
      headers: authHeaders(options),
    });
  } catch (cause) {
    if (isAbortError(cause)) throw cause;
    const normalized = normalizeApiError({ status: 0, cause });
    throw new StorefrontApiError(
      normalized.userMessage,
      normalized.status,
      normalized.apiDetail as StorefrontApiErrorDetail | undefined,
      normalized.rawMessage,
    );
  }
}

export async function storefrontApiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T | null> {
  const response = await storefrontRequest(path, options);

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: ApiErrorDetail;
    };
    throwStorefrontApiError(response.status, body);
  }

  if (response.status === 204) return null;
  return response.json() as Promise<T>;
}

export async function storefrontApiFetchText(
  path: string,
  options: RequestInit = {},
): Promise<string> {
  const response = await storefrontRequest(path, options);

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throwStorefrontApiError(response.status, body);
  }

  return response.text();
}

export async function storefrontApiFetchBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const response = await storefrontRequest(path, options);

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throwStorefrontApiError(response.status, body);
  }

  return response.blob();
}
