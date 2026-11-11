import type {
  CatalogSubCategoryItem,
  CatalogTaxonomy,
  CatalogTaxonomySport,
} from "./catalog";
import {
  CATALOG_ALL_TOP,
  SPORT_TO_SLUG,
  SLUG_TO_SPORT,
  type CatalogSport,
  type CatalogSportSlug,
  type CatalogTopScope,
} from "./catalogNavigation";

export type SubCategorySlug = string;

export type ProductTypeOption = {
  key: string;
  label: string;
};

export function sportScopeToSlug(top: CatalogTopScope | null | undefined): CatalogSportSlug | null {
  if (!top || top === CATALOG_ALL_TOP) return null;
  return SPORT_TO_SLUG[top as CatalogSport] ?? null;
}

export function getTaxonomySport(
  taxonomy: CatalogTaxonomy | null | undefined,
  sport: CatalogSportSlug | null,
): CatalogTaxonomySport | null {
  if (!taxonomy || !sport) return null;
  return taxonomy.sports.find((item) => item.slug === sport) ?? null;
}

/** Mapping sports expose section/node chips in taxonomy before navigation API responds. */
export function taxonomyUsesMappingSections(
  taxonomy: CatalogTaxonomy | null | undefined,
  sport: CatalogSportSlug | null,
): boolean {
  const sportDef = getTaxonomySport(taxonomy, sport);
  return Boolean(sportDef?.sections?.length);
}

export function sportLabelFromTaxonomy(
  taxonomy: CatalogTaxonomy | null | undefined,
  sport: CatalogSport,
): string {
  const sportDef = getTaxonomySport(taxonomy, SPORT_TO_SLUG[sport]);
  return sportDef?.label?.trim() || "";
}

// Мгновенное меню подкатегорий из taxonomy (порядок как в CATALOG_SUBCATEGORIES).
export function subcategoriesFromTaxonomy(
  taxonomy: CatalogTaxonomy | null | undefined,
  sport: CatalogSportSlug | null,
): CatalogSubCategoryItem[] {
  const sportDef = getTaxonomySport(taxonomy, sport);
  if (!sportDef) return [];
  if (sportDef.sections?.length) {
    return sportDef.sections.map((section) => ({
      slug: section.slug,
      label: section.label,
      type_level: "chip" as const,
      types: section.chips.map((chip) => ({
        key: chip.display_key,
        label_ru: chip.label,
        count: 0,
      })),
    }));
  }
  return sportDef.subcategories.map((sub) => ({
    slug: sub.slug,
    label: sub.label,
    types: [],
  }));
}

export function pruneCatalogSubcategories<T extends { slug: string; types: Array<{ count: number }> }>(
  items: T[],
): T[] {
  return items.map((sub) => ({
    ...sub,
    types: sub.types.filter((type) => type.count > 0),
  }));
}

export function parseProductTypeFromSearchParams(
  params: URLSearchParams | { get: (key: string) => string | null },
): string {
  const node = params.get("node")?.trim();
  if (node) return node;
  return params.get("category_type")?.trim() ?? params.get("type")?.trim() ?? "";
}

export function normalizeSubCategorySlug(
  sport: CatalogSportSlug | null,
  raw: string,
  taxonomy?: CatalogTaxonomy | null,
): SubCategorySlug | "" {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  if (!sport) return trimmed;
  const sportKey = SLUG_TO_SPORT[sport];
  const alias = taxonomy?.sub_slug_aliases[sportKey]?.[trimmed];
  return alias ?? trimmed;
}

export function parseSubCategoryFromSearchParams(
  params: URLSearchParams | { get: (key: string) => string | null },
  sport?: CatalogSportSlug | null,
  taxonomy?: CatalogTaxonomy | null,
): SubCategorySlug | "" {
  const section = params.get("section")?.trim();
  if (section) return normalizeSubCategorySlug(sport ?? null, section, taxonomy);
  const raw = params.get("sub")?.trim() ?? "";
  return normalizeSubCategorySlug(sport ?? null, raw, taxonomy);
}
