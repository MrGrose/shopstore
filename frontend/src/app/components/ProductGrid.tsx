import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router";

import {
  CATALOG_ALL_LABEL_RU,
  CATALOG_ALL_TOP,
  catalogSportPath,
  type CatalogSport,
  type CatalogTopScope,
} from "../../lib/storefront/catalogNavigation";
import {
  sportLabelFromTaxonomy,
  sportScopeToSlug,
} from "../../lib/storefront/catalogCategoryFilter";
import {
  readCatalogFiltersFromSearchParams,
} from "../../lib/storefront/catalogFilterParams";
import { CatalogCategoryNav } from "./catalog/CatalogCategoryNav";
import {
  labelSportType,
} from "../../lib/storefront/catalogLabels";
import { useCatalogLabels } from "../../hooks/useCatalogLabels";
import { useCatalogTaxonomy } from "../../hooks/useCatalogTaxonomy";
import { useCart } from "../../hooks/useCart";
import { useStorefrontCompact, useStorefrontBottomNav } from "../../lib/storefront/useStorefrontSurface";
import { useCatalogGridData } from "../../hooks/useCatalogGridData";
import { useDesktopSidebar } from "../../hooks/useDesktopSidebar";
import {
  buildCatalogBreadcrumbTrail,
  buildCatalogBreadcrumbTrailFromNavigation,
  hasCatalogBreadcrumbScope,
  CatalogBreadcrumbNav,
} from "./catalog/CatalogBreadcrumbNav";
import { CatalogFacetFilters } from "./catalog/CatalogFacetFilters";
import { CatalogFiltersSheet } from "./catalog/CatalogFiltersSheet";
import { CatalogGridLayout } from "./catalog/CatalogGridLayout";
import { CatalogProductList } from "./catalog/CatalogProductList";
import { CatalogSectionHeader } from "./catalog/CatalogSectionHeader";
import {
  CatalogMiniAppSearchBar,
  CatalogSearchBanner,
} from "./catalog/CatalogSearchControls";
import { StorefrontToast } from "./catalog/StorefrontToast";
import { formatProductCount } from "./catalog/catalogProductTypes";
import { useCatalogCartActions } from "../../hooks/useCatalogCartActions";

export type ProductGridProps = {
  fixedTopCategory?: CatalogTopScope;
  showSportTabs?: boolean;
  filterLayout?: "inline" | "sidebar";
  sectionEyebrow?: string;
  sectionTitle?: string;
};

export function ProductGrid({
  fixedTopCategory,
  showSportTabs = fixedTopCategory == null,
  filterLayout = fixedTopCategory ? "sidebar" : "inline",
  sectionEyebrow,
  sectionTitle,
}: ProductGridProps = {}) {
  const { labels: catalogLabelsData } = useCatalogLabels();
  const { taxonomy: catalogTaxonomyData } = useCatalogTaxonomy();
  const catalogLabels = catalogLabelsData ?? null;
  const catalogTaxonomy = catalogTaxonomyData ?? null;
  const navigate = useNavigate();
  const location = useLocation();
  const compact = useStorefrontCompact();
  const bottomNav = useStorefrontBottomNav();
  const isDesktopSidebar = useDesktopSidebar();
  const [activeFilter, setActiveFilter] = useState<string>(fixedTopCategory ?? "All");
  const [toast, setToast] = useState<string | null>(null);
  const { cartRefreshing, addToCart, changeCatalogCartQty } = useCatalogCartActions(setToast);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const { cart } = useCart();
  const cartItems = cart?.items ?? [];

  const grid = useCatalogGridData({
    fixedTopCategory,
    activeFilter,
    setActiveFilter,
    catalogLabels,
    catalogTaxonomy,
    facetsNeeded: isDesktopSidebar || filtersOpen,
    navigate,
    pathname: location.pathname,
  });

  const {
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
    items,
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
  } = grid;

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ filter?: string }>;
      const next = String(ce?.detail?.filter || "");
      if (next === "Padel" || next === "Tennis" || next === "Running") {
        navigate(catalogSportPath(next));
        return;
      }
      if (!fixedTopCategory && next) {
        setActiveFilter(next);
        document.getElementById("products")?.scrollIntoView({ behavior: "smooth" });
      }
    };
    window.addEventListener("store:catalog:filter", handler);
    return () => window.removeEventListener("store:catalog:filter", handler);
  }, [navigate, fixedTopCategory]);

  const clearSearchQueryAndResetPage = useCallback(() => {
    clearSearchQuery();
  }, [clearSearchQuery]);

  const submitCatalogSearchAndResetPage = useCallback(
    (raw: string) => {
      submitCatalogSearch(raw);
    },
    [submitCatalogSearch],
  );

  const handleActiveFilterChange = useCallback((filter: string) => {
    setActiveFilter(filter);
  }, []);

  const headerEyebrow =
    sectionEyebrow ?? (fixedTopCategory ? "Каталог" : "Избранные товары");
  const headerTitle = searchQ.trim()
    ? `Поиск: ${searchQ.trim()}`
    : sectionTitle ??
      (fixedTopCategory === CATALOG_ALL_TOP
        ? CATALOG_ALL_LABEL_RU
        : fixedTopCategory
          ? sportLabelFromTaxonomy(catalogTaxonomy, fixedTopCategory as CatalogSport) ||
            (catalogLabels ? labelSportType(catalogLabels, fixedTopCategory) : "")
          : "Лучшие предложения");

  const catalogBreadcrumbScope = useMemo(
    () =>
      hasCatalogBreadcrumbScope({
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
      }),
    [
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
    ],
  );

  const catalogBreadcrumbTrail = useMemo(() => {
    if (searchQ.trim()) {
      return [{ label: `Поиск: ${searchQ.trim()}`, to: null }];
    }
    if (catalogNavigation?.breadcrumbs?.length && fixedTopCategory) {
      return buildCatalogBreadcrumbTrailFromNavigation(
        fixedTopCategory,
        catalogNavigation.breadcrumbs,
        catalogBreadcrumbScope,
      );
    }
    return buildCatalogBreadcrumbTrail({
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
    });
  }, [
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
    catalogNavigation?.breadcrumbs,
    catalogBreadcrumbScope,
  ]);

  const handleBreadcrumbNavigate = useCallback(
    (to: string) => {
      const url = new URL(to, window.location.origin);
      const parsed = readCatalogFiltersFromSearchParams(
        url.searchParams,
        sportScopeToSlug(fixedTopCategory),
        catalogTaxonomy,
      );
      patchSearchParams({
        sub: parsed.sub,
        productType: parsed.productType,
        brand: "",
        category: "",
        gender: "",
        color: "",
        size: "",
        priceMin: "",
        priceMax: "",
        sortPrice: "",
      });
    },
    [fixedTopCategory, catalogTaxonomy, patchSearchParams],
  );

  const productCountLabel =
    loading && items.length === 0
      ? "Загрузка…"
      : totalCount != null
        ? formatProductCount(totalCount)
        : loading
          ? "…"
          : null;

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (category) count += 1;
    if (brand) count += 1;
    if (gender) count += 1;
    if (color) count += 1;
    if (size) count += 1;
    if (priceMin.trim() || priceMax.trim()) count += 1;
    if (sortPrice) count += 1;
    return count;
  }, [brand, category, color, gender, priceMax, priceMin, size, sortPrice]);

  const categoryNav =
    filterToTopCategory ? (
      <CatalogCategoryNav
        topCategory={filterToTopCategory}
        subCategories={catalogSubcategories}
        subCategory={subCategory}
        productType={productType}
        onCategorySelect={handleCategorySelect}
        onSportChange={handleSportChange}
        onSubcategoryHover={loadSubcategoryTypes}
        catalogLabels={catalogLabels}
        catalogTaxonomy={catalogTaxonomy}
        variant={compact ? "miniapp" : "default"}
      />
    ) : null;

  const facetFiltersProps = {
    compact,
    fixedTopCategory,
    filterToTopCategory,
    activeFilter,
    onActiveFilterChange: handleActiveFilterChange,
    subCategory,
    productType,
    sortPrice,
    productCountLabel,
    catalogLabels,
    categories,
    brands,
    facets,
    facetsLoading,
    facetsOptionsLoading,
    priceBoundsLoading,
    category,
    brand,
    gender,
    color,
    size,
    priceMin,
    priceMax,
    onCategoryChange: (value: string) => patchSearchParams({ category: value }),
    onBrandChange: (value: string) => patchSearchParams({ brand: value }),
    onGenderChange: (value: string) => patchSearchParams({ gender: value }),
    onColorChange: (value: string) => patchSearchParams({ color: value }),
    onSizeChange: (value: string) => patchSearchParams({ size: value }),
    onPriceMinChange: (value: string) => patchSearchParams({ priceMin: value }),
    onPriceMaxChange: (value: string) => patchSearchParams({ priceMax: value }),
    onPriceRangeChange: (priceMin: string, priceMax: string) =>
      patchSearchParams({ priceMin, priceMax }),
    onSortPriceChange: handleSortPriceChange,
    onResetFilters: resetAllFilters,
  } as const;

  const filtersSheet = (
    <CatalogFiltersSheet
      open={filtersOpen}
      onOpenChange={setFiltersOpen}
      compact={compact}
      activeFilterCount={activeFilterCount}
    >
      <CatalogFacetFilters layout="sheet" {...facetFiltersProps} />
    </CatalogFiltersSheet>
  );

  const productList = (
    <CatalogProductList
      items={items}
      pageSize={pageSize}
      compact={compact}
      loading={loading}
      loadingMore={loadingMore}
      hasMore={hasMore}
      showStaleGrid={showStaleGrid}
      productsErrorMessage={productsErrorMessage}
      productsFetched={productsFetched}
      searchQ={searchQ}
      cartItems={cartItems}
      cartRefreshing={cartRefreshing}
      onOpen={openProduct}
      onAddToCart={addToCart}
      onChangeCartQty={changeCatalogCartQty}
      onLoadMore={fetchNextPage}
    />
  );

  return (
    <section
      id="products"
      className={compact ? "shrink-0 pb-3 pt-3" : "shrink-0 pb-4 pt-10"}
    >
      <div className={compact ? "mx-auto px-3" : "max-w-[1400px] mx-auto px-6 lg:px-8"}>
        {fixedTopCategory ? (
          <CatalogBreadcrumbNav
            compact={compact}
            headerEyebrow={headerEyebrow}
            brand={brand}
            subCategory={subCategory}
            trail={catalogBreadcrumbTrail}
            onBreadcrumbNavigate={handleBreadcrumbNavigate}
          />
        ) : (
          <CatalogSectionHeader eyebrow={headerEyebrow} title={headerTitle} />
        )}

        <CatalogGridLayout
          compact={compact}
          filterLayout={filterLayout}
          filterToTopCategory={filterToTopCategory}
          productCountLabel={productCountLabel}
          miniAppSearchBar={
            compact ? (
              <CatalogMiniAppSearchBar
                searchQ={searchQ}
                onSubmitSearch={submitCatalogSearchAndResetPage}
                onClearSearch={clearSearchQueryAndResetPage}
              />
            ) : null
          }
          searchBanner={
            <CatalogSearchBanner
              compact={compact}
              searchQ={searchQ}
              onClearSearch={clearSearchQueryAndResetPage}
            />
          }
          categoryNav={categoryNav}
          filtersSheet={filtersSheet}
          sidebarFilters={<CatalogFacetFilters layout="sidebar" {...facetFiltersProps} />}
          inlineFilters={<CatalogFacetFilters layout={filterLayout} {...facetFiltersProps} />}
          productList={productList}
        />
      </div>

      {toast ? <StorefrontToast message={toast} compact={compact} bottomNav={bottomNav} /> : null}
    </section>
  );
}
