import { CatalogFiltersPanel } from "../CatalogFiltersPanel";
import type { CatalogFiltersPanelProps } from "../CatalogFiltersPanel";
import type { CatalogTopScope } from "../../../lib/storefront/catalogNavigation";
import type { CatalogSortPrice } from "../../../lib/storefront/catalogFilterParams";

export type CatalogFacetFiltersProps = {
  layout: CatalogFiltersPanelProps["layout"];
  compact: boolean;
  fixedTopCategory?: CatalogTopScope;
  filterToTopCategory: CatalogTopScope | null;
  activeFilter: string;
  onActiveFilterChange: (filter: string) => void;
  subCategory: string;
  productType: string;
  sortPrice: CatalogSortPrice;
  productCountLabel: string | null;
} & Pick<
  CatalogFiltersPanelProps,
  | "catalogLabels"
  | "categories"
  | "brands"
  | "facets"
  | "facetsLoading"
  | "facetsOptionsLoading"
  | "priceBoundsLoading"
  | "category"
  | "brand"
  | "gender"
  | "color"
  | "size"
  | "priceMin"
  | "priceMax"
  | "onCategoryChange"
  | "onBrandChange"
  | "onGenderChange"
  | "onColorChange"
  | "onSizeChange"
  | "onPriceMinChange"
  | "onPriceMaxChange"
  | "onPriceRangeChange"
  | "onSortPriceChange"
  | "onResetFilters"
>;

export function CatalogFacetFilters({
  layout,
  compact,
  fixedTopCategory,
  filterToTopCategory,
  activeFilter,
  onActiveFilterChange,
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
  onCategoryChange,
  onBrandChange,
  onGenderChange,
  onColorChange,
  onSizeChange,
  onPriceMinChange,
  onPriceMaxChange,
  onPriceRangeChange,
  onSortPriceChange,
  onResetFilters,
}: CatalogFacetFiltersProps) {
  return (
    <CatalogFiltersPanel
      layout={layout}
      compactSheet={compact && layout === "sheet"}
      fixedTopCategory={fixedTopCategory}
      showSportTabs={false}
      showCategoryFilter={false}
      activeFilter={activeFilter}
      onActiveFilterChange={onActiveFilterChange}
      catalogLabels={catalogLabels}
      categories={categories}
      brands={brands}
      facets={facets}
      facetsLoading={facetsLoading}
      facetsOptionsLoading={facetsOptionsLoading}
      priceBoundsMin={facets?.price_min}
      priceBoundsMax={facets?.price_max}
      priceBoundsLoading={priceBoundsLoading}
      category={category}
      brand={brand}
      gender={gender}
      color={color}
      size={size}
      priceMin={priceMin}
      priceMax={priceMax}
      onCategoryChange={onCategoryChange}
      onBrandChange={onBrandChange}
      onGenderChange={onGenderChange}
      onColorChange={onColorChange}
      onSizeChange={onSizeChange}
      onPriceMinChange={onPriceMinChange}
      onPriceMaxChange={onPriceMaxChange}
      onPriceRangeChange={onPriceRangeChange}
      priceResetToken={`${filterToTopCategory ?? ""}|${subCategory}|${productType}|${brand}|${gender}|${color}|${size}`}
      sortPrice={filterToTopCategory ? sortPrice : ""}
      onSortPriceChange={filterToTopCategory ? onSortPriceChange : undefined}
      onResetFilters={filterToTopCategory ? onResetFilters : undefined}
      productCountLabel={filterToTopCategory ? productCountLabel : null}
    />
  );
}
