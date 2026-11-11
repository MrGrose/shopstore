import { useMemo } from "react";

import type { CatalogFacets } from "../lib/storefront/catalog";
import {
  catalogFacetOptionsQueryKey,
  type CatalogFacetKey,
} from "../lib/storefront/catalogFilterParams";
import type { CatalogFilterQueryOpts } from "../lib/storefront/catalogFilterQuery";
import { useCatalogFacets } from "./useCatalogFacets";

const FACET_OPTION_INCLUDES: Record<CatalogFacetKey, string> = {
  brand: "brands",
  gender: "genders",
  color: "colors",
  size: "sizes",
};

type FacetOptionsSlice = Pick<
  CatalogFilterQueryOpts,
  | "topCategory"
  | "sub"
  | "type"
  | "useMappingParams"
  | "categoryUrlParams"
  | "brand"
  | "gender"
  | "color"
  | "size"
  | "priceMin"
  | "priceMax"
  | "searchQ"
>;

function hasActiveFacetFilters(opts: FacetOptionsSlice): boolean {
  return Boolean(opts.brand || opts.gender || opts.color || opts.size);
}

function hasActivePriceFilter(opts: Pick<FacetOptionsSlice, "priceMin" | "priceMax">): boolean {
  return Boolean(opts.priceMin.trim() || opts.priceMax.trim());
}

function mergeFacetOptions<T extends keyof CatalogFacets>(
  key: T,
  dedicated: CatalogFacets[T] | undefined,
  meta: CatalogFacets[T] | undefined,
): CatalogFacets[T] {
  const dedicatedList = Array.isArray(dedicated) ? dedicated : [];
  if (dedicatedList.length > 0) return dedicated as CatalogFacets[T];
  return (meta ?? (Array.isArray(dedicated) ? [] : null)) as CatalogFacets[T];
}

export function useCatalogFacetsBundle(
  catalogFacetOptionsSlice: FacetOptionsSlice,
  facetsEnabled: boolean,
  metaFacets?: CatalogFacets,
  metaFacetsLoading = false,
): {
  facets: CatalogFacets | null;
  brands: string[];
  facetsLoading: boolean;
  facetsOptionsLoading: boolean;
  priceBoundsLoading: boolean;
} {
  const needsDedicatedFacets =
    hasActiveFacetFilters(catalogFacetOptionsSlice) ||
    hasActivePriceFilter(catalogFacetOptionsSlice);
  // A: cold, no filters → meta only (dedicated off even while metaFacets is undefined).
  // B/C: URL or user filters → dedicated on immediately; do not wait for meta.
  const skipAllFacetQueries = facetsEnabled && !needsDedicatedFacets;
  const optionFacetsEnabled = facetsEnabled && needsDedicatedFacets;

  const facetOptionsKeys = useMemo(
    () => ({
      brand: catalogFacetOptionsQueryKey(catalogFacetOptionsSlice, "brand"),
      gender: catalogFacetOptionsQueryKey(catalogFacetOptionsSlice, "gender"),
      color: catalogFacetOptionsQueryKey(catalogFacetOptionsSlice, "color"),
      size: catalogFacetOptionsQueryKey(catalogFacetOptionsSlice, "size"),
    }),
    [catalogFacetOptionsSlice],
  );

  const brandFacetsQuery = useCatalogFacets(
    facetOptionsKeys.brand,
    FACET_OPTION_INCLUDES.brand,
    optionFacetsEnabled,
  );
  const genderFacetsQuery = useCatalogFacets(
    facetOptionsKeys.gender,
    FACET_OPTION_INCLUDES.gender,
    optionFacetsEnabled,
  );
  const colorFacetsQuery = useCatalogFacets(
    facetOptionsKeys.color,
    FACET_OPTION_INCLUDES.color,
    optionFacetsEnabled,
  );
  const sizeFacetsQuery = useCatalogFacets(
    facetOptionsKeys.size,
    FACET_OPTION_INCLUDES.size,
    optionFacetsEnabled,
  );

  const facets = useMemo((): CatalogFacets | null => {
    if (!facetsEnabled) return null;

    const brand = brandFacetsQuery.facets;
    const gender = genderFacetsQuery.facets;
    const color = colorFacetsQuery.facets;
    const size = sizeFacetsQuery.facets;

    if (
      skipAllFacetQueries &&
      metaFacets &&
      !brand?.brands?.length &&
      !gender?.genders?.length &&
      !color?.colors?.length &&
      !size?.sizes?.length
    ) {
      return metaFacets;
    }

    if (!brand && !gender && !color && !size && !metaFacets) return null;

    return {
      brands: mergeFacetOptions("brands", brand?.brands, metaFacets?.brands),
      genders: mergeFacetOptions("genders", gender?.genders, metaFacets?.genders),
      colors: mergeFacetOptions("colors", color?.colors, metaFacets?.colors),
      sizes: mergeFacetOptions("sizes", size?.sizes, metaFacets?.sizes),
      price_min: metaFacets?.price_min ?? null,
      price_max: metaFacets?.price_max ?? null,
    };
  }, [
    facetsEnabled,
    skipAllFacetQueries,
    metaFacets,
    brandFacetsQuery.facets,
    genderFacetsQuery.facets,
    colorFacetsQuery.facets,
    sizeFacetsQuery.facets,
  ]);

  const brands = useMemo(
    () => (facets?.brands?.length ? facets.brands.map((item) => item.value) : []),
    [facets?.brands],
  );

  const facetsLoading = facetsEnabled && metaFacetsLoading;
  const facetsOptionsLoading =
    optionFacetsEnabled &&
    (brandFacetsQuery.isLoading ||
      genderFacetsQuery.isLoading ||
      colorFacetsQuery.isLoading ||
      sizeFacetsQuery.isLoading);
  const priceBoundsLoading = facetsLoading;

  return {
    facets,
    brands,
    facetsLoading,
    facetsOptionsLoading,
    priceBoundsLoading,
  };
}
