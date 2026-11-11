/**
 * Русские подписи категорий — источник: src/utils/labels.py (GET /catalog/labels).
 */

export type CatalogLabelsConfig = {
  sport_types: Record<string, string>;
  category_l2: Record<string, string>;
  category_l3?: Record<string, string>;
  genders: Record<string, string>;
  filter_all: string;
  product_fallback: string;
};

import { storefrontApiFetch } from "./api";

export const CATALOG_LABELS_FALLBACK: CatalogLabelsConfig = {
  sport_types: {
    Padel: "Падел",
    Tennis: "Теннис",
    Running: "Бег",
  },
  category_l2: {},
  genders: {
    unisex: "Для всех",
    men: "Мужской",
    women: "Женский",
    boys: "Для мальчиков",
    girls: "Для девочек",
    kids: "Детский",
  },
  filter_all: "Все",
  product_fallback: "Товар",
};

export async function fetchCatalogLabels(): Promise<CatalogLabelsConfig> {
  try {
    const data = await storefrontApiFetch<CatalogLabelsConfig>("/catalog/labels");
    if (data) return { ...CATALOG_LABELS_FALLBACK, ...data };
  } catch {
    // ignore
  }
  return CATALOG_LABELS_FALLBACK;
}

export function labelSportType(labels: CatalogLabelsConfig, key: string): string {
  return labels.sport_types[key] ?? key;
}

export function labelCategoryL2(labels: CatalogLabelsConfig, key: string): string {
  return labels.category_l2[key] ?? key;
}

export function labelCategoryL3(labels: CatalogLabelsConfig, key: string): string {
  return labels.category_l3?.[key] ?? key;
}

export function labelGender(labels: CatalogLabelsConfig, key: string): string {
  return labels.genders[key] ?? key;
}

export type CatalogLabelItem = { key: string; label_ru: string };

export function parseCatalogLabelKeys(items: CatalogLabelItem[] | string[]): string[] {
  return normalizeCatalogLabelItems(items).map((x) => x.key);
}

/** API: string[] (legacy) или { key, label_ru }[] */
export function normalizeCatalogLabelItems(
  items: unknown,
  labels?: CatalogLabelsConfig,
): CatalogLabelItem[] {
  if (!Array.isArray(items)) return [];
  const cfg = labels ?? CATALOG_LABELS_FALLBACK;
  return items
    .map((raw) => {
      if (typeof raw === "string") {
        const key = raw.trim();
        if (!key) return null;
        return {
          key,
          label_ru: cfg.category_l2[key] ?? cfg.sport_types[key] ?? key,
        };
      }
      if (raw && typeof raw === "object" && "key" in raw) {
        const row = raw as CatalogLabelItem;
        const key = String(row.key || "").trim();
        if (!key) return null;
        return {
          key,
          label_ru: String(row.label_ru || "").trim() || cfg.category_l2[key] || key,
        };
      }
      return null;
    })
    .filter((x): x is CatalogLabelItem => x !== null);
}
