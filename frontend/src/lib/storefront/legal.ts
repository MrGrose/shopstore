import { storefrontApiFetchText } from "./api";

export const LEGAL_SLUGS = [
  "privacy",
  "terms",
  "consent",
  "returns",
  "referral-rules",
] as const;
export type LegalSlug = (typeof LEGAL_SLUGS)[number];

const LEGAL_TITLES: Record<LegalSlug, string> = {
  privacy: "Политика конфиденциальности",
  terms: "Публичная оферта",
  consent: "Согласие на обработку персональных данных",
  returns: "Возврат и обмен",
  "referral-rules": "Правила реферальной программы",
};

export function pathToLegalSlug(path: string): LegalSlug | null {
  const normalized = path.replace(/\?.*$/, "").replace(/\/$/, "") || "/";
  const slug = normalized.startsWith("/") ? normalized.slice(1) : normalized;
  return (LEGAL_SLUGS as readonly string[]).includes(slug) ? (slug as LegalSlug) : null;
}

export function legalTitleForPath(path: string, fallback = "Документы"): string {
  const slug = pathToLegalSlug(path);
  return slug ? LEGAL_TITLES[slug] : fallback;
}

export function openStoreLegal(path: string, title?: string) {
  window.dispatchEvent(
    new CustomEvent("store:legal:open", {
      detail: { path, title: title ?? legalTitleForPath(path) },
    }),
  );
}

export function resolveLegalFromHref(href: string): { path: string; title: string } | null {
  const raw = href.trim();
  if (!raw || raw.startsWith("mailto:") || raw.startsWith("tel:")) return null;
  try {
    const url = new URL(raw, window.location.origin);
    const slug = pathToLegalSlug(url.pathname);
    if (!slug) return null;
    return { path: `/${slug}`, title: LEGAL_TITLES[slug] };
  } catch {
    return null;
  }
}

export async function fetchLegalFragment(path: string): Promise<string> {
  const slug = pathToLegalSlug(path);
  if (!slug) throw new Error("Неизвестный документ");
  return storefrontApiFetchText(`/storefront/legal/${slug}`);
}
