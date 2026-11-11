import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams, type NavigateFunction } from "react-router";

import {
  fetchCatalogSubcategories,
  type CatalogSubCategoryItem,
  type CatalogTaxonomy,
} from "../lib/storefront/catalog";
import {
  parseProductTypeFromSearchParams,
  parseSubCategoryFromSearchParams,
  pruneCatalogSubcategories,
  sportScopeToSlug,
  subcategoriesFromTaxonomy,
  taxonomyUsesMappingSections,
  type SubCategorySlug,
} from "../lib/storefront/catalogCategoryFilter";
import type { CatalogFilterQueryOpts } from "../lib/storefront/catalogFilterQuery";
import {
  buildCatalogFacetResetPatch,
  buildCatalogReturnPath,
  buildCatalogSearchParams,
  buildPdpVariantSearchParams,
  buildVariantConstraintPreset,
  type CatalogSortPrice,
} from "../lib/storefront/catalogFilterParams";
import {
  CATALOG_ALL_TOP,
  catalogAllPath,
  catalogSportPath,
  type CatalogSport,
  type CatalogTopScope,
} from "../lib/storefront/catalogNavigation";
import {
  catalogLocationKey,
  getCatalogScrollRoot,
  readCatalogScrollTop,
  saveCatalogScrollSnapshot,
} from "../lib/storefront/catalogScrollRestore";
import {
  normalizeCatalogLabelItems,
  type CatalogLabelsConfig,
} from "../lib/storefront/catalogLabels";
import { mapApiErrorToUserMessage } from "../lib/errorMessages";
import { mergeSubcategoryTypes } from "../lib/storefront/catalogSubcategoryMerge";
import { useCatalogCategories } from "./useCatalogCategories";
import { useCatalogCount } from "./useCatalogCount";
import { useCatalogFacetsBundle } from "./useCatalogFacetsBundle";
import { useCatalogFilters } from "./useCatalogFilters";
import { useCatalogMeta } from "./useCatalogMeta";
import { useCatalogNavigation } from "./useCatalogNavigation";
import {
  catalogSubcategoriesQueryKey,
  CATALOG_SUBCATEGORIES_STALE_MS,
  useCatalogSubcategories,
} from "./useCatalogSubcategories";
import { useCatalogWindowFocusInvalidation } from "./useCatalogWindowFocusInvalidation";
import { useCatalogScrollRestore } from "./useCatalogScrollRestore";
import { useProducts } from "./useProducts";
import type { CatalogProductCardData } from "../app/components/catalog/catalogProductTypes";
import { CATALOG_PAGE_SIZE } from "../app/components/catalog/catalogProductTypes";

export type UseCatalogGridDataArgs = {
  fixedTopCategory?: CatalogTopScope;
  activeFilter: string;
  setActiveFilter: Dispatch<SetStateAction<string>>;
  catalogLabels: CatalogLabelsConfig | null;
  catalogTaxonomy: CatalogTaxonomy | null;
  facetsNeeded: boolean;
  pageSize?: number;
  navigate: NavigateFunction;
  pathname: string;
};

function resolveSubcategoryRow(
  items: CatalogSubCategoryItem[],
  subSlug: SubCategorySlug,
): CatalogSubCategoryItem | null {
  const row = items.find((item) => item.slug === subSlug) ?? items[0];
  if (!row) return null;
  return pruneCatalogSubcategories([row])[0] ?? row;
}

export function useCatalogGridData({
  fixedTopCategory,
  activeFilter,
  setActiveFilter,
  catalogLabels,
  catalogTaxonomy,
  facetsNeeded,
  pageSize = CATALOG_PAGE_SIZE,
  navigate,
  pathname,
}: UseCatalogGridDataArgs) {
  const queryClient = useQueryClient();
  const prevTopCategoryRef = useRef<CatalogTopScope | null | undefined>(undefined);
  const facetFiltersKeyRef = useRef("");
  const [catalogSubcategories, setCatalogSubcategories] = useState<CatalogSubCategoryItem[]>([]);
  const [catalogMetaReady, setCatalogMetaReady] = useState(false);

  const filterToTopCategory = useMemo(() => {
    if (fixedTopCategory) return fixedTopCategory;
    if (activeFilter === CATALOG_ALL_TOP) return CATALOG_ALL_TOP;
    if (activeFilter === "Padel" || activeFilter === "Tennis" || activeFilter === "Running") {
      return activeFilter;
    }
    return null;
  }, [activeFilter, fixedTopCategory]);

  const [searchParams] = useSearchParams();
  const sportSlug = sportScopeToSlug(filterToTopCategory);

  const catalogNavEnabled =
    Boolean(filterToTopCategory) && filterToTopCategory !== CATALOG_ALL_TOP;

  const mappingFromTaxonomy = taxonomyUsesMappingSections(catalogTaxonomy, sportSlug);

  const { navigation: catalogNavigation } = useCatalogNavigation(
    {
      topCategory: filterToTopCategory,
      sub: parseSubCategoryFromSearchParams(searchParams, sportSlug, catalogTaxonomy),
      productType: parseProductTypeFromSearchParams(searchParams),
    },
    catalogNavEnabled,
  );

  const useMappingParams = catalogNavigation?.use_mapping_params ?? mappingFromTaxonomy;

  const catalogFilters = useCatalogFilters({
    sportSlug,
    useMappingParams,
    filterToTopCategory,
    catalogTaxonomy,
  });

  const {
    searchQ,
    subCategory,
    productType,
    brand,
    gender,
    color,
    size,
    priceMin,
    priceMax,
    debouncedPriceMin,
    debouncedPriceMax,
    sortPrice,
    category,
    patchSearchParams,
    markPendingUrlSearch,
    clearSearchQuery,
    submitCatalogSearch,
    resetFiltersState,
    resetUrlKeepSearchQuery,
  } = catalogFilters;

  const activeSubcategoryQueryEnabled =
    Boolean(filterToTopCategory) &&
    filterToTopCategory !== CATALOG_ALL_TOP &&
    Boolean(subCategory) &&
    catalogMetaReady;

  const { subcategories: activeSubcategoryPayload } = useCatalogSubcategories(
    filterToTopCategory ?? "",
    useMappingParams ? undefined : subCategory || undefined,
    useMappingParams ? subCategory || undefined : undefined,
    activeSubcategoryQueryEnabled,
  );

  const categoryUrlParams = useMemo((): Record<string, string> | null => {
    const raw = catalogNavigation?.url_params;
    if (!raw || Object.keys(raw).length === 0) return null;
    return raw;
  }, [
    catalogNavigation?.url_params?.section,
    catalogNavigation?.url_params?.node,
    catalogNavigation?.url_params?.sub,
    catalogNavigation?.url_params?.category_type,
  ]);

  const catalogReturnPathOpts = useMemo(
    () => ({
      sub: subCategory,
      productType,
      brand,
      gender,
      color,
      size,
      priceMin,
      priceMax,
      sortPrice,
      searchQ,
      useMappingParams,
    }),
    [
      subCategory,
      productType,
      brand,
      gender,
      color,
      size,
      priceMin,
      priceMax,
      sortPrice,
      searchQ,
      useMappingParams,
    ],
  );

  const catalogFilterOpts = useMemo(
    (): CatalogFilterQueryOpts => ({
      topCategory: filterToTopCategory,
      sub: subCategory,
      type: productType,
      useMappingParams,
      categoryUrlParams,
      brand,
      gender,
      color,
      size,
      priceMin: debouncedPriceMin,
      priceMax: debouncedPriceMax,
      sortPrice,
      searchQ,
    }),
    [
      filterToTopCategory,
      subCategory,
      productType,
      useMappingParams,
      categoryUrlParams,
      brand,
      gender,
      color,
      size,
      sortPrice,
      debouncedPriceMin,
      debouncedPriceMax,
      searchQ,
    ],
  );

  const catalogFacetOptionsSlice = useMemo(
    () => ({
      topCategory: filterToTopCategory,
      sub: subCategory,
      type: productType,
      useMappingParams,
      categoryUrlParams,
      brand,
      gender,
      color,
      size,
      priceMin: debouncedPriceMin,
      priceMax: debouncedPriceMax,
      searchQ,
    }),
    [
      filterToTopCategory,
      subCategory,
      productType,
      useMappingParams,
      categoryUrlParams,
      brand,
      gender,
      color,
      size,
      debouncedPriceMin,
      debouncedPriceMax,
      searchQ,
    ],
  );

  const productsQuery = useProducts(catalogFilterOpts, pageSize, Boolean(filterToTopCategory));
  const {
    items,
    hasMore,
    isLoading: productsLoading,
    isFetching: productsFetching,
    isFetchingNextPage,
    isFetched: productsFetched,
    isPlaceholderData: productsPlaceholderData,
    error: productsError,
    fetchNextPage,
  } = productsQuery;

  useCatalogScrollRestore({
    items,
    hasMore,
    loading: productsLoading,
    loadingMore: isFetchingNextPage,
    productsFetched,
    fetchNextPage,
  });

  // Tiers: products + nav + labels + taxonomy + cart = initial.
  // Facets: meta is initial when the sidebar/sheet needs them (facetsNeeded).
  // Dedicated /products/facets ×4 only for active facet/price filters (deep-link or user).
  // Mobile sheet closed: count only (facetsNeeded=false).
  const facetsQueryEnabled = Boolean(filterToTopCategory) && facetsNeeded;
  const facetsEnabled = facetsQueryEnabled;

  const {
    total: metaTotal,
    facets: metaFacets,
    isLoading: metaFacetsLoading,
  } = useCatalogMeta(catalogFilterOpts, facetsEnabled);

  const { total: catalogCountTotal } = useCatalogCount(
    catalogFilterOpts,
    Boolean(filterToTopCategory) && !facetsQueryEnabled,
  );

  const { facets, brands, facetsLoading, facetsOptionsLoading, priceBoundsLoading } =
    useCatalogFacetsBundle(
      catalogFacetOptionsSlice,
      facetsEnabled,
      metaFacets,
      metaFacetsLoading,
    );

  const { categories: rawCategories } = useCatalogCategories(
    filterToTopCategory,
    catalogMetaReady && Boolean(filterToTopCategory),
  );

  useCatalogWindowFocusInvalidation(catalogMetaReady);

  useEffect(() => {
    if (productsFetched && !productsFetching) {
      setCatalogMetaReady(true);
    }
  }, [productsFetched, productsFetching, catalogFilterOpts]);

  useEffect(() => {
    setCatalogMetaReady(false);
  }, [filterToTopCategory, subCategory, productType, brand, gender, color, size, searchQ]);

  useEffect(() => {
    const nextKey = `${brand}|${gender}|${color}|${size}`;
    if (!facetFiltersKeyRef.current) {
      facetFiltersKeyRef.current = nextKey;
      return;
    }
    if (facetFiltersKeyRef.current === nextKey) return;
    facetFiltersKeyRef.current = nextKey;
    void queryClient.invalidateQueries({ queryKey: ["catalog", "facets"] });
    void queryClient.invalidateQueries({ queryKey: ["catalog", "meta"] });
  }, [brand, gender, color, size, queryClient]);

  useEffect(() => {
    if (!filterToTopCategory || filterToTopCategory === CATALOG_ALL_TOP) {
      setCatalogSubcategories([]);
      return;
    }
    setCatalogSubcategories(subcategoriesFromTaxonomy(catalogTaxonomy, sportSlug));
  }, [filterToTopCategory, catalogTaxonomy, sportSlug]);

  useEffect(() => {
    if (!subCategory || !activeSubcategoryPayload?.length) return;
    const pruned = resolveSubcategoryRow(activeSubcategoryPayload, subCategory);
    if (!pruned) return;
    setCatalogSubcategories((prev) => mergeSubcategoryTypes(prev, pruned));
  }, [activeSubcategoryPayload, subCategory]);

  useEffect(() => {
    if (!subCategory || !productType) return;
    const sub = catalogSubcategories.find((item) => item.slug === subCategory);
    if (!sub?.types.length) return;
    const apiLoaded = sub.types.some((type) => type.count > 0);
    if (!apiLoaded) return;
    const valid = sub.types.some((type) => type.key === productType && type.count > 0);
    if (valid) return;
    patchSearchParams({ productType: "" });
  }, [catalogSubcategories, subCategory, productType, patchSearchParams]);

  useEffect(() => {
    if (prevTopCategoryRef.current === undefined) {
      prevTopCategoryRef.current = filterToTopCategory;
      return;
    }
    if (prevTopCategoryRef.current === filterToTopCategory) return;
    prevTopCategoryRef.current = filterToTopCategory;

    resetFiltersState();
    resetUrlKeepSearchQuery();
  }, [filterToTopCategory, resetFiltersState, resetUrlKeepSearchQuery]);

  useEffect(() => {
    if (fixedTopCategory === CATALOG_ALL_TOP) setActiveFilter("All");
    else if (fixedTopCategory) setActiveFilter(fixedTopCategory);
  }, [fixedTopCategory, setActiveFilter]);

  const loadSubcategoryTypes = useCallback(
    (subSlug: SubCategorySlug) => {
      if (!filterToTopCategory || filterToTopCategory === CATALOG_ALL_TOP || !subSlug) return;

      const queryKey = catalogSubcategoriesQueryKey(
        filterToTopCategory,
        useMappingParams ? undefined : subSlug,
        useMappingParams ? subSlug : undefined,
      );

      const cached = queryClient.getQueryData<CatalogSubCategoryItem[]>(queryKey);
      if (cached?.length) {
        const pruned = resolveSubcategoryRow(cached, subSlug);
        if (!pruned) return;
        setCatalogSubcategories((prev) => mergeSubcategoryTypes(prev, pruned));
        return;
      }

      void queryClient
        .fetchQuery({
          queryKey,
          queryFn: () =>
            fetchCatalogSubcategories(
              filterToTopCategory,
              useMappingParams ? undefined : subSlug,
              useMappingParams ? subSlug : undefined,
            ),
          staleTime: CATALOG_SUBCATEGORIES_STALE_MS,
        })
        .then((items) => {
          const pruned = resolveSubcategoryRow(items, subSlug);
          if (!pruned) return;
          setCatalogSubcategories((prev) => mergeSubcategoryTypes(prev, pruned));
        })
        .catch(() => {
          // taxonomy structure already on screen
        });
    },
    [filterToTopCategory, useMappingParams, queryClient],
  );

  const handleCategorySelect = useCallback(
    (nextSub: SubCategorySlug | "", nextType: string) => {
      patchSearchParams({
        sub: nextSub,
        productType: nextType,
        brand: "",
        priceMin: "",
        priceMax: "",
      });
      void queryClient.resetQueries({ queryKey: ["catalog", "products"] });
    },
    [patchSearchParams, queryClient],
  );

  const handleSportChange = useCallback(
    (sport: CatalogSport | typeof CATALOG_ALL_TOP) => {
      if (sport === CATALOG_ALL_TOP) {
        navigate(catalogAllPath());
        return;
      }
      navigate(catalogSportPath(sport));
    },
    [navigate],
  );

  const openProduct = useCallback(
    (id: number, previewImageUrl?: string | null) => {
      const returnPath = buildCatalogReturnPath(pathname, catalogReturnPathOpts);
      const params = buildCatalogSearchParams(catalogReturnPathOpts);
      const search = params.toString();
      saveCatalogScrollSnapshot({
        url: catalogLocationKey(pathname, search),
        top: readCatalogScrollTop(getCatalogScrollRoot(document.getElementById("products"))),
        productId: id,
        itemCount: items.length,
      });
      markPendingUrlSearch(search);
      navigate(
        { pathname, search: search ? `?${search}` : "" },
        { replace: true },
      );
      const preset = buildVariantConstraintPreset({
        color: catalogReturnPathOpts.color,
        size: catalogReturnPathOpts.size,
      });
      const pdpQs = buildPdpVariantSearchParams({
        color: catalogReturnPathOpts.color,
        size: catalogReturnPathOpts.size,
      }).toString();
      navigate(`/catalog/product/${id}${pdpQs ? `?${pdpQs}` : ""}`, {
        state: {
          from: returnPath,
          previewImageUrl: previewImageUrl ?? null,
          variantConstraintPreset: preset,
        },
      });
    },
    [catalogReturnPathOpts, items.length, pathname, navigate, markPendingUrlSearch],
  );

  const loading = productsLoading;
  const loadingMore = isFetchingNextPage;
  const productsErrorMessage = productsError
    ? mapApiErrorToUserMessage(productsError, { fallback: "Не удалось загрузить товары" })
    : null;
  const showStaleGrid =
    items.length > 0 &&
    (productsPlaceholderData || (productsFetching && !isFetchingNextPage));
  const totalCount = (facetsEnabled ? metaTotal : catalogCountTotal) ?? null;
  const categories = useMemo(
    () => normalizeCatalogLabelItems(rawCategories ?? [], catalogLabels ?? undefined),
    [rawCategories, catalogLabels],
  );

  const handleSortPriceChange = useCallback(
    (value: CatalogSortPrice) => {
      patchSearchParams({ sortPrice: value });
    },
    [patchSearchParams],
  );

  const resetAllFilters = useCallback(() => {
    patchSearchParams(buildCatalogFacetResetPatch());
  }, [patchSearchParams]);

  return {
    filterToTopCategory,
    useMappingParams,
    catalogNavigation,
    searchQ,
    subCategory,
    productType,
    brand,
    gender,
    color,
    size,
    priceMin,
    priceMax,
    sortPrice,
    category,
    patchSearchParams,
    clearSearchQuery,
    submitCatalogSearch,
    catalogSubcategories,
    catalogFilterOpts,
    items: items as CatalogProductCardData[],
    hasMore,
    loading,
    loadingMore,
    productsFetched,
    productsErrorMessage,
    showStaleGrid,
    totalCount,
    categories,
    brands,
    facets,
    facetsLoading,
    facetsOptionsLoading,
    priceBoundsLoading,
    handleCategorySelect,
    handleSportChange,
    loadSubcategoryTypes,
    handleSortPriceChange,
    resetAllFilters,
    openProduct,
    fetchNextPage,
    pageSize,
  };
}
