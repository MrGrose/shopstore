import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import type { CatalogTaxonomy } from "../lib/storefront/catalog";
import type { SubCategorySlug } from "../lib/storefront/catalogCategoryFilter";
import type { CatalogSportSlug } from "../lib/storefront/catalogNavigation";
import {
  applyCatalogFiltersToSearchParams,
  applyCatalogSearchQueryToSearchParams,
  canonicalizeCategorySearchParams,
  hasCategoryFilterInUrl,
  readCatalogFiltersFromSearchParams,
  readCatalogSearchQuery,
  type CatalogFilterState,
  type CatalogSortPrice,
} from "../lib/storefront/catalogFilterParams";

const PRICE_DEBOUNCE_MS = 400;

export type UseCatalogFiltersArgs = {
  sportSlug: CatalogSportSlug | null;
  useMappingParams: boolean;
  filterToTopCategory: string | null;
  catalogTaxonomy?: CatalogTaxonomy | null;
};

export function useCatalogFilters({
  sportSlug,
  useMappingParams,
  filterToTopCategory,
  catalogTaxonomy = null,
}: UseCatalogFiltersArgs) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pendingUrlPatchRef = useRef<string | null>(null);
  const prevSubTypeRef = useRef<string | undefined>(undefined);
  const prevPriceScopeRef = useRef<string | undefined>(undefined);

  const initialFilters = readCatalogFiltersFromSearchParams(
    searchParams,
    sportSlug,
    catalogTaxonomy,
  );

  const [subCategory, setSubCategory] = useState<SubCategorySlug | "">(initialFilters.sub);
  const [productType, setProductType] = useState(initialFilters.productType);
  const [brand, setBrand] = useState(initialFilters.brand);
  const [gender, setGender] = useState(initialFilters.gender);
  const [color, setColor] = useState(initialFilters.color);
  const [size, setSize] = useState(initialFilters.size);
  const [priceMin, setPriceMin] = useState(initialFilters.priceMin);
  const [priceMax, setPriceMax] = useState(initialFilters.priceMax);
  const [debouncedPriceMin, setDebouncedPriceMin] = useState(initialFilters.priceMin);
  const [debouncedPriceMax, setDebouncedPriceMax] = useState(initialFilters.priceMax);
  const [sortPrice, setSortPrice] = useState<CatalogSortPrice>(initialFilters.sortPrice);
  const [category, setCategory] = useState(initialFilters.category);

  const searchQ = readCatalogSearchQuery(searchParams);

  const commitSearchParams = useCallback(
    (buildNext: (prev: URLSearchParams) => URLSearchParams) => {
      setSearchParams(
        (prev) => {
          const next = buildNext(prev);
          pendingUrlPatchRef.current = next.toString();
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const markPendingUrlSearch = useCallback((expected: string) => {
    pendingUrlPatchRef.current = expected;
  }, []);

  const patchSearchParams = useCallback(
    (patch: Partial<CatalogFilterState>) => {
      if ("sub" in patch) setSubCategory(patch.sub ?? "");
      if ("productType" in patch) setProductType(patch.productType ?? "");
      if ("brand" in patch) setBrand(patch.brand ?? "");
      if ("gender" in patch) setGender(patch.gender ?? "");
      if ("color" in patch) setColor(patch.color ?? "");
      if ("size" in patch) setSize(patch.size ?? "");
      if ("priceMin" in patch) {
        setPriceMin(patch.priceMin ?? "");
        setDebouncedPriceMin(patch.priceMin ?? "");
      }
      if ("priceMax" in patch) {
        setPriceMax(patch.priceMax ?? "");
        setDebouncedPriceMax(patch.priceMax ?? "");
      }
      if ("sortPrice" in patch) setSortPrice(patch.sortPrice ?? "");
      if ("category" in patch) setCategory(patch.category ?? "");
      commitSearchParams((prev) =>
        applyCatalogFiltersToSearchParams(prev, patch, { useMappingParams }),
      );
    },
    [commitSearchParams, useMappingParams],
  );

  useEffect(() => {
    const pending = pendingUrlPatchRef.current;
    if (pending !== null) {
      if (searchParams.toString() !== pending) {
        return;
      }
      pendingUrlPatchRef.current = null;
    }
    const parsed = readCatalogFiltersFromSearchParams(
      searchParams,
      sportSlug,
      catalogTaxonomy,
    );
    const urlHasCategory = hasCategoryFilterInUrl(searchParams);
    setSubCategory((prev) => {
      if (!parsed.sub && !urlHasCategory && prev) return prev;
      return prev !== parsed.sub ? parsed.sub : prev;
    });
    setProductType((prev) => {
      if (!parsed.productType && !urlHasCategory && prev) return prev;
      return prev !== parsed.productType ? parsed.productType : prev;
    });
    setBrand((prev) => (prev !== parsed.brand ? parsed.brand : prev));
    setGender((prev) => (prev !== parsed.gender ? parsed.gender : prev));
    setColor((prev) => (prev !== parsed.color ? parsed.color : prev));
    setSize((prev) => (prev !== parsed.size ? parsed.size : prev));
    setPriceMin((prev) => (prev !== parsed.priceMin ? parsed.priceMin : prev));
    setPriceMax((prev) => (prev !== parsed.priceMax ? parsed.priceMax : prev));
    setDebouncedPriceMin((prev) => (prev !== parsed.priceMin ? parsed.priceMin : prev));
    setDebouncedPriceMax((prev) => (prev !== parsed.priceMax ? parsed.priceMax : prev));
    setSortPrice((prev) => (prev !== parsed.sortPrice ? parsed.sortPrice : prev));
    setCategory((prev) => (prev !== parsed.category ? parsed.category : prev));
  }, [searchParams, sportSlug, catalogTaxonomy]);

  useEffect(() => {
    if (!useMappingParams) return;
    const hasLegacy =
      searchParams.has("sub") ||
      searchParams.has("category_type") ||
      searchParams.has("type");
    if (!hasLegacy) return;
    commitSearchParams((prev) =>
      canonicalizeCategorySearchParams(prev, subCategory, productType),
    );
  }, [useMappingParams, searchParams, subCategory, productType, commitSearchParams]);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedPriceMin(priceMin), PRICE_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [priceMin]);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedPriceMax(priceMax), PRICE_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [priceMax]);

  useEffect(() => {
    const key = `${subCategory}|${productType}`;
    if (prevSubTypeRef.current === undefined) {
      prevSubTypeRef.current = key;
      return;
    }
    if (prevSubTypeRef.current === key) return;
    prevSubTypeRef.current = key;
    if (!brand.trim()) return;
    setBrand("");
    patchSearchParams({ brand: "" });
  }, [subCategory, productType, brand, patchSearchParams]);

  useEffect(() => {
    const key = `${filterToTopCategory ?? ""}|${subCategory}|${productType}`;
    if (prevPriceScopeRef.current === undefined) {
      prevPriceScopeRef.current = key;
      return;
    }
    if (prevPriceScopeRef.current === key) return;
    prevPriceScopeRef.current = key;
    const hadPrice = priceMin.trim() || priceMax.trim();
    setPriceMin("");
    setPriceMax("");
    setDebouncedPriceMin("");
    setDebouncedPriceMax("");
    if (!hadPrice) return;
    patchSearchParams({ priceMin: "", priceMax: "" });
  }, [
    filterToTopCategory,
    subCategory,
    productType,
    priceMin,
    priceMax,
    patchSearchParams,
  ]);

  const clearSearchQuery = useCallback(() => {
    commitSearchParams((prev) => applyCatalogSearchQueryToSearchParams(prev, ""));
  }, [commitSearchParams]);

  const submitCatalogSearch = useCallback(
    (raw: string) => {
      commitSearchParams((prev) => applyCatalogSearchQueryToSearchParams(prev, raw));
    },
    [commitSearchParams],
  );

  const resetFiltersState = useCallback(() => {
    prevSubTypeRef.current = "|";
    prevPriceScopeRef.current = undefined;
    setSubCategory("");
    setProductType("");
    setBrand("");
    setGender("");
    setColor("");
    setSize("");
    setPriceMin("");
    setPriceMax("");
    setDebouncedPriceMin("");
    setDebouncedPriceMax("");
    setSortPrice("");
    setCategory("");
  }, []);

  const resetUrlKeepSearchQuery = useCallback(() => {
    commitSearchParams((prev) => {
      const params = new URLSearchParams();
      const q = prev.get("q")?.trim();
      if (q) params.set("q", q);
      return params;
    });
  }, [commitSearchParams]);

  return {
    searchParams,
    setSearchParams,
    searchQ,
    subCategory,
    setSubCategory,
    productType,
    setProductType,
    brand,
    setBrand,
    gender,
    setGender,
    color,
    setColor,
    size,
    setSize,
    priceMin,
    setPriceMin,
    priceMax,
    setPriceMax,
    debouncedPriceMin,
    debouncedPriceMax,
    setDebouncedPriceMin,
    setDebouncedPriceMax,
    sortPrice,
    setSortPrice,
    category,
    setCategory,
    patchSearchParams,
    markPendingUrlSearch,
    clearSearchQuery,
    submitCatalogSearch,
    resetFiltersState,
    resetUrlKeepSearchQuery,
  };
}
