export type StorefrontIdentity = {
  provider: string;
  provider_user_id?: string | null;
  email?: string | null;
  telegram_username?: string | null;
  created_at?: string | null;
};

export type StorefrontUser = {
  id: number;
  telegram_id?: number | null;
  telegram_username?: string | null;
  email?: string | null;
  name?: string | null;
  avatar?: string | null;
  role?: string;
  referral_code?: string | null;
  referrer_id?: number | null;
  created_at?: string | null;
  can_be_referred?: boolean;
  has_referral_program?: boolean;
  identities?: StorefrontIdentity[];
};

export function hasAuthToken(): boolean {
  if (typeof localStorage !== "undefined" && localStorage.getItem("access_token")) {
    return true;
  }
  if (typeof document === "undefined") return false;
  return document.cookie
    .split(";")
    .some((part) => part.trim().startsWith("access_token="));
}

export function loginHintForNext(nextPath: string): string {
  if (nextPath.startsWith("/internal/admin")) {
    return "Войдите как администратор";
  }
  if (nextPath.startsWith("/orders") || nextPath.startsWith("/account")) {
    return "Войдите, чтобы открыть личный кабинет";
  }
  if (nextPath.startsWith("/checkout")) {
    return "Войдите, чтобы оформить заказ";
  }
  return "Войдите, чтобы продолжить";
}

async function fetchWithStorefrontSession(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("access_token")
      : null;
  return fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers as Record<string, string> | undefined),
    },
  });
}

export async function clearAuthSession(): Promise<void> {
  localStorage.removeItem("access_token");
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
  } catch {
    // ignore
  }
}

export async function fetchCurrentUser(): Promise<StorefrontUser | null> {
  if (!hasAuthToken()) return null;

  const res = await fetchWithStorefrontSession("/users/me");
  if (res.ok) {
    return (await res.json()) as StorefrontUser;
  }

  if (res.status === 401 || res.status === 404) {
    await clearAuthSession();
    return null;
  }

  return null;
}

export function safeLoginNext(raw: string | null | undefined): string {
  const next = (raw ?? "/catalog").trim();
  if (!next.startsWith("/") || next.startsWith("//")) return "/catalog";
  return next;
}

export type PostLoginEffect = "checkout";

/** Stub routes (/checkout) → catalog + cart drawer. */
export function resolvePostLoginNavigation(next: string): {
  path: string;
  effect?: PostLoginEffect;
} {
  const normalized = safeLoginNext(next);
  const pathOnly = normalized.split("?")[0] ?? normalized;
  if (pathOnly === "/account" || pathOnly.startsWith("/account/")) {
    return { path: normalized };
  }
  if (pathOnly === "/orders" || pathOnly.startsWith("/orders/")) {
    return { path: "/account?tab=orders" };
  }
  if (pathOnly === "/checkout" || pathOnly.startsWith("/checkout/")) {
    return { path: "/catalog", effect: "checkout" };
  }
  return { path: normalized };
}

// Post-login навигация после phone verify: next приоритетнее, иначе /account.
export function resolvePhonePostLogin(rawNext: string | null | undefined): {
  path: string;
  effect?: PostLoginEffect;
} {
  const hasExplicitNext = rawNext != null && rawNext.trim() !== "";
  if (hasExplicitNext) {
    return resolvePostLoginNavigation(safeLoginNext(rawNext));
  }
  return { path: "/account" };
}

export function runPostLoginEffect(effect?: PostLoginEffect): void {
  if (effect === "checkout") {
    window.dispatchEvent(new CustomEvent("store:checkout:open"));
  }
}
