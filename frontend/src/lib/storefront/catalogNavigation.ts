export const CATALOG_SPORTS = ["Padel", "Tennis", "Running"] as const;

export type CatalogSport = (typeof CATALOG_SPORTS)[number];

export const CATALOG_ALL_TOP = "All" as const;
export const CATALOG_ALL_LABEL_RU = "Все товары" as const;

export type CatalogTopScope = CatalogSport | typeof CATALOG_ALL_TOP;

export type CatalogSportSlug = "padel" | "tennis" | "running";

export type CatalogRouteSlug = CatalogSportSlug | "all";

export const SPORT_TO_SLUG: Record<CatalogSport, CatalogSportSlug> = {
  Padel: "padel",
  Tennis: "tennis",
  Running: "running",
};

export const SLUG_TO_SPORT: Record<CatalogSportSlug, CatalogSport> = {
  padel: "Padel",
  tennis: "Tennis",
  running: "Running",
};

export function isCatalogRouteSlug(slug: string | undefined): slug is CatalogRouteSlug {
  return slug != null && (slug in SLUG_TO_SPORT || slug === "all");
}

export function storefrontHomePath(): string {
  return "/";
}

export function catalogSportPath(sport: CatalogSport): string {
  return `/catalog/${SPORT_TO_SLUG[sport]}`;
}

export function catalogAllPath(): string {
  return "/catalog";
}

export function productPath(productId: number | string): string {
  return `/catalog/product/${productId}`;
}

/** Catalog listing routes (/catalog, /catalog/:sport) — not PDP. */
export function isCatalogListingPath(pathname: string): boolean {
  if (!pathname.startsWith("/catalog")) return false;
  if (pathname.startsWith("/catalog/product/")) return false;
  return true;
}

export function resolveCatalogTopFromSlug(slug: CatalogRouteSlug): CatalogTopScope {
  if (slug === "all") return CATALOG_ALL_TOP;
  return SLUG_TO_SPORT[slug];
}

export function navLabelToCatalogSport(label: string): CatalogSport | null {
  if (label === "Падел" || label === "Padel") return "Padel";
  if (label === "Теннис" || label === "Tennis") return "Tennis";
  if (label === "Бег" || label === "Running") return "Running";
  return null;
}
