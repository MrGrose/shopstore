import { Link } from "react-router";

import type { CatalogSubCategoryItem, CatalogTaxonomy, CatalogNavigationLink } from "../../../lib/storefront/catalog";
import {
  getTaxonomySport,
  sportLabelFromTaxonomy,
  sportScopeToSlug,
} from "../../../lib/storefront/catalogCategoryFilter";
import {
  CATALOG_ALL_LABEL_RU,
  CATALOG_ALL_TOP,
  catalogAllPath,
  catalogSportPath,
  type CatalogSport,
  type CatalogTopScope,
} from "../../../lib/storefront/catalogNavigation";
import { buildCatalogSearchParams } from "../../../lib/storefront/catalogFilterParams";
import {
  CATALOG_LABELS_FALLBACK,
  labelSportType,
  type CatalogLabelsConfig,
} from "../../../lib/storefront/catalogLabels";

export type CatalogBreadcrumbSegment = {
  label: string;
  to: string | null;
};

export type CatalogBreadcrumbScope = {
  subCategory: string;
  productType: string;
  category: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  sortPrice: string;
};

// Есть ли в URL scope кроме top-категории (для linkable sport crumb).
export function hasCatalogBreadcrumbScope(scope: CatalogBreadcrumbScope): boolean {
  return Boolean(
    scope.subCategory ||
      scope.productType ||
      scope.category ||
      scope.brand ||
      scope.gender ||
      scope.color ||
      scope.size ||
      scope.priceMin ||
      scope.priceMax ||
      scope.sortPrice,
  );
}

// Собирает path витрины из canonical url_params navigation API.
export function buildCatalogPathFromUrlParams(
  top: CatalogTopScope,
  urlParams: Record<string, string>,
): string {
  const base =
    top === CATALOG_ALL_TOP ? catalogAllPath() : catalogSportPath(top as CatalogSport);
  const qs = new URLSearchParams(urlParams).toString();
  return qs ? `${base}?${qs}` : base;
}

// Строит trail из breadcrumbs navigation API с теми же правилами link/null, что legacy trail.
export function buildCatalogBreadcrumbTrailFromNavigation(
  fixedTopCategory: CatalogTopScope,
  breadcrumbs: CatalogNavigationLink[],
  catalogBreadcrumbScope: boolean,
): CatalogBreadcrumbSegment[] {
  if (!fixedTopCategory || breadcrumbs.length === 0) return [];

  const trail: CatalogBreadcrumbSegment[] = breadcrumbs.map((crumb) => ({
    label: crumb.label,
    to: buildCatalogPathFromUrlParams(fixedTopCategory, crumb.url_params),
  }));

  if (trail.length > 0) {
    trail[trail.length - 1] = { ...trail[trail.length - 1], to: null };
  }
  if (trail.length === 1 && !catalogBreadcrumbScope) {
    trail[0] = { ...trail[0], to: null };
  }
  return trail;
}

export function buildCatalogBreadcrumbPath(
  top: CatalogTopScope,
  sub?: string,
  type?: string,
  useMappingParams = false,
): string {
  const base =
    top === CATALOG_ALL_TOP ? catalogAllPath() : catalogSportPath(top as CatalogSport);
  const params = buildCatalogSearchParams({
    sub: sub ?? "",
    productType: type ?? "",
    brand: "",
    gender: "",
    color: "",
    size: "",
    priceMin: "",
    priceMax: "",
    sortPrice: "",
    useMappingParams,
  });
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export type BuildCatalogBreadcrumbTrailParams = {
  fixedTopCategory?: CatalogTopScope;
  searchQ: string;
  sectionTitle?: string;
  catalogLabels: CatalogLabelsConfig | null;
  catalogTaxonomy: CatalogTaxonomy | null;
  subCategory: string;
  productType: string;
  category: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  sortPrice: string;
  catalogSubcategories: CatalogSubCategoryItem[];
  useMappingParams: boolean;
};

export function buildCatalogBreadcrumbTrail({
  fixedTopCategory,
  searchQ,
  sectionTitle,
  catalogLabels,
  catalogTaxonomy,
  subCategory,
  productType,
  category,
  brand,
  gender,
  color,
  size,
  priceMin,
  priceMax,
  sortPrice,
  catalogSubcategories,
  useMappingParams,
}: BuildCatalogBreadcrumbTrailParams): CatalogBreadcrumbSegment[] {
  if (!fixedTopCategory) return [];

  if (searchQ.trim()) {
    return [{ label: `Поиск: ${searchQ.trim()}`, to: null }];
  }

  if (fixedTopCategory === CATALOG_ALL_TOP) {
    return [{ label: sectionTitle ?? CATALOG_ALL_LABEL_RU, to: null }];
  }

  const catalogBreadcrumbScope = hasCatalogBreadcrumbScope({
    subCategory,
    productType,
    category,
    brand,
    gender,
    color,
    size,
    priceMin,
    priceMax,
    sortPrice,
  });

  const labelsForUi = catalogLabels ?? CATALOG_LABELS_FALLBACK;
  const sportLabel =
    sportLabelFromTaxonomy(catalogTaxonomy, fixedTopCategory as CatalogSport) ||
    labelSportType(labelsForUi, fixedTopCategory as CatalogSport);
  const taxonomySport = getTaxonomySport(
    catalogTaxonomy,
    sportScopeToSlug(fixedTopCategory),
  );

  const trail: CatalogBreadcrumbSegment[] = [
    {
      label: sportLabel,
      to: buildCatalogBreadcrumbPath(fixedTopCategory, undefined, undefined, useMappingParams),
    },
  ];

  if (subCategory) {
    const subDef = catalogSubcategories.find((item) => item.slug === subCategory);
    const taxonomySection = taxonomySport?.sections?.find((item) => item.slug === subCategory);
    const taxonomySub = taxonomySport?.subcategories.find((item) => item.slug === subCategory);
    trail.push({
      label: subDef?.label ?? taxonomySection?.label ?? taxonomySub?.label ?? "",
      to: buildCatalogBreadcrumbPath(fixedTopCategory, subCategory, undefined, useMappingParams),
    });
  }

  if (productType && subCategory) {
    const subDef = catalogSubcategories.find((item) => item.slug === subCategory);
    const typeDef = subDef?.types.find((item) => item.key === productType);
    const taxonomyChip = taxonomySport?.sections
      ?.find((item) => item.slug === subCategory)
      ?.chips.find((chip) => chip.display_key === productType || chip.slug === productType);
    trail.push({
      label: typeDef?.label_ru ?? taxonomyChip?.label ?? "",
      to: buildCatalogBreadcrumbPath(
        fixedTopCategory,
        subCategory,
        productType,
        useMappingParams,
      ),
    });
  }

  if (trail.length > 0) {
    trail[trail.length - 1].to = null;
  }
  if (trail.length === 1 && !catalogBreadcrumbScope) {
    trail[0].to = null;
  }

  return trail;
}

export type CatalogBreadcrumbNavProps = {
  compact: boolean;
  headerEyebrow: string;
  brand: string;
  subCategory: string;
  trail: CatalogBreadcrumbSegment[];
  onBreadcrumbNavigate: (to: string) => void;
};

export function CatalogBreadcrumbNav({
  compact,
  headerEyebrow,
  brand,
  subCategory,
  trail,
  onBreadcrumbNavigate,
}: CatalogBreadcrumbNavProps) {
  return (
    <div className={compact ? "mb-3" : "mb-8 lg:mb-6"}>
      <nav
        aria-label="Раздел каталога"
        className={`flex flex-wrap items-center font-medium ${compact ? "gap-1.5 text-[12px]" : "gap-2 text-[14px]"}`}
      >
        <Link
          to={catalogAllPath()}
          className="text-sp-text-secondary hover:text-sp-text-primary sp-transition no-underline"
        >
          {headerEyebrow}
        </Link>
        {trail.map((segment, index) => {
          const isLast = index === trail.length - 1;
          return (
            <span key={`${segment.label}-${index}`} className="flex items-center gap-2">
              <span className="text-sp-text-muted" aria-hidden="true">
                /
              </span>
              {isLast ? (
                <span
                  className={`inline-flex items-center font-medium sp-transition ${compact ? "px-3 py-1 text-[12px]" : "px-5 py-2 text-[14px]"}`}
                  style={{
                    background: "var(--sp-blue)",
                    color: "#FFFFFF",
                    borderRadius: "var(--sp-radius-pill)",
                  }}
                >
                  {segment.label}
                </span>
              ) : segment.to ? (
                <Link
                  to={segment.to}
                  onClick={() => onBreadcrumbNavigate(segment.to!)}
                  className="text-sp-text-secondary hover:text-sp-text-primary sp-transition no-underline"
                >
                  {segment.label}
                </Link>
              ) : (
                <span className="text-sp-text-secondary">{segment.label}</span>
              )}
            </span>
          );
        })}
      </nav>
    </div>
  );
}
