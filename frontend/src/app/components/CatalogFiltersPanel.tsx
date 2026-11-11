import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { CatalogFacetOption, CatalogFacets } from "../../lib/storefront/catalog";
import type { CatalogLabelItem, CatalogLabelsConfig } from "../../lib/storefront/catalogLabels";
import { labelSportType } from "../../lib/storefront/catalogLabels";
import {
  CATALOG_ALL_TOP,
  catalogAllPath,
  catalogSportPath,
  type CatalogTopScope,
} from "../../lib/storefront/catalogNavigation";
import { useLocation, useNavigate } from "react-router";
import { ChevronLeft, X } from "lucide-react";
import {
  clearFilterSectionsState,
  saveFilterSectionsState,
  type CatalogFilterSectionKey,
} from "../../lib/storefront/catalogFilterUi";
import { usePersistedFilterSection } from "../../lib/storefront/usePersistedFilterSection";
import { CatalogFilterSectionShell } from "./CatalogFilterSectionShell";
import { CatalogPriceSlider } from "./CatalogPriceSlider";
import { CatalogPriceSort, type SortPrice } from "./CatalogPriceSort";
import {
  parseFacetListValue,
  toggleFacetListValue,
  filterFacetOptions,
} from "../../lib/storefront/catalogFilterParams";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";

export type CatalogFiltersPanelProps = {
  layout: "inline" | "sidebar" | "sheet";
  fixedTopCategory?: CatalogTopScope;
  showSportTabs?: boolean;
  showCategoryFilter?: boolean;
  activeFilter: string;
  onActiveFilterChange: (filter: string) => void;
  catalogLabels: CatalogLabelsConfig | null;
  categories: CatalogLabelItem[];
  brands: string[];
  facets: CatalogFacets | null;
  facetsLoading?: boolean;
  facetsOptionsLoading?: boolean;
  priceBoundsMin?: number | string | null;
  priceBoundsMax?: number | string | null;
  priceBoundsLoading?: boolean;
  category: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  onCategoryChange: (value: string) => void;
  onBrandChange: (value: string) => void;
  onGenderChange: (value: string) => void;
  onColorChange: (value: string) => void;
  onSizeChange: (value: string) => void;
  onPriceMinChange: (value: string) => void;
  onPriceMaxChange: (value: string) => void;
  onPriceRangeChange?: (priceMin: string, priceMax: string) => void;
  priceResetToken?: string;
  sortPrice?: SortPrice;
  onSortPriceChange?: (value: SortPrice) => void;
  onResetFilters?: () => void;
  productCountLabel?: string | null;
  compactSheet?: boolean;
};

const sportFilters = ["All", "Padel", "Tennis", "Running"] as const;

type SectionKey = Exclude<CatalogFilterSectionKey, "sort">;

function filterTabLabel(filter: string, labels: CatalogLabelsConfig) {
  if (filter === "All") return labels.filter_all;
  return labelSportType(labels, filter);
}

function facetOptions(
  fromFacets: CatalogFacetOption[] | undefined,
  fallback: CatalogFacetOption[],
): CatalogFacetOption[] {
  if (fromFacets && fromFacets.length > 0) return fromFacets;
  return fallback;
}

function emptyOption(panel: boolean): CatalogFacetOption[] {
  return panel ? [{ value: "", label_ru: "Пока нет вариантов", count: 0 }] : [];
}

function facetOptionsWithSelected(
  options: CatalogFacetOption[],
  selected: string[],
): CatalogFacetOption[] {
  const byValue = new Map(options.filter((o) => o.value).map((o) => [o.value, o]));
  for (const value of selected) {
    if (value && !byValue.has(value)) {
      byValue.set(value, { value, label_ru: value, count: 0 });
    }
  }
  return [...byValue.values()];
}

function toggleSingle(current: string, value: string, onChange: (value: string) => void) {
  onChange(current === value ? "" : value);
}

function FilterSection({
  title,
  section,
  resetToken,
  expandNonce = 0,
  children,
}: {
  title: string;
  section: SectionKey;
  resetToken: string;
  expandNonce?: number;
  children: ReactNode;
}) {
  const { open, toggle, setOpen } = usePersistedFilterSection(section, resetToken);

  useEffect(() => {
    if (expandNonce > 0) setOpen(true);
  }, [expandNonce, setOpen]);

  return (
    <CatalogFilterSectionShell title={title} open={open} onToggle={toggle}>
      {children}
    </CatalogFilterSectionShell>
  );
}

const FACET_CHECKBOX_VISIBLE = 10;

function SelectedFacetChips({
  items,
  selected,
  disabled,
  onToggle,
}: {
  items: CatalogFacetOption[];
  selected: string[];
  disabled?: boolean;
  onToggle: (value: string) => void;
}) {
  if (!selected.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {selected.map((value) => {
        const label = items.find((item) => item.value === value)?.label_ru ?? value;
        return (
          <button
            key={value}
            type="button"
            disabled={disabled}
            onClick={() => onToggle(value)}
            className="inline-flex items-center gap-1 rounded-full border border-sp-border bg-sp-bg px-2.5 py-1 text-[12px] font-medium text-sp-text-primary sp-transition hover:border-sp-blue disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={`Убрать ${label}`}
          >
            <span>{label}</span>
            <X size={12} aria-hidden />
          </button>
        );
      })}
    </div>
  );
}

function CheckboxList({
  options,
  selected,
  onToggle,
  disabled,
  showCounts,
  searchable = false,
  collapsible = false,
  searchPlaceholder = "Найти…",
  resetToken = "",
  emptySearchLabel = "Ничего не найдено",
  loading = false,
  variant = "default",
}: {
  options: CatalogFacetOption[];
  selected: string[];
  onToggle: (value: string) => void;
  disabled?: boolean;
  showCounts?: boolean;
  searchable?: boolean;
  collapsible?: boolean;
  searchPlaceholder?: string;
  resetToken?: string;
  emptySearchLabel?: string;
  loading?: boolean;
  variant?: "default" | "popover";
}) {
  const items = options.filter((o) => o.value);
  const [facetQuery, setFacetQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setFacetQuery("");
    setExpanded(false);
  }, [resetToken]);

  useEffect(() => {
    setExpanded(false);
  }, [facetQuery]);

  const filteredItems = searchable ? filterFacetOptions(items, facetQuery) : items;

  if (!items.length) {
    return (
      <p className="text-[14px] text-sp-text-muted m-0">
        {loading ? "Загрузка…" : "Пока нет вариантов"}
      </p>
    );
  }

  const listItems = searchable ? filteredItems : items;
  const visibleItems =
    collapsible && !expanded && listItems.length > FACET_CHECKBOX_VISIBLE
      ? listItems.slice(0, FACET_CHECKBOX_VISIBLE)
      : listItems;
  const hiddenCount = listItems.length - FACET_CHECKBOX_VISIBLE;
  const showEmptySearch = searchable && facetQuery.trim() && filteredItems.length === 0;

  const selectedChips = searchable ? (
    <SelectedFacetChips
      items={items}
      selected={selected}
      disabled={disabled}
      onToggle={onToggle}
    />
  ) : null;

  const checkboxList = (
    <div className="space-y-2">
      {visibleItems.map((item) => (
        <label
          key={item.value}
          className={`flex items-center gap-2 group ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
        >
          <input
            type="checkbox"
            checked={selected.includes(item.value)}
            disabled={disabled}
            onChange={() => onToggle(item.value)}
            className="w-4 h-4 sp-transition cursor-pointer"
            style={{ accentColor: "var(--sp-blue)" }}
          />
          <span className="text-[14px] text-sp-text-primary group-hover:opacity-70 sp-transition">
            {showCounts && item.count > 0 ? `${item.label_ru} (${item.count})` : item.label_ru}
          </span>
        </label>
      ))}
      {showEmptySearch ? (
        <p className="m-0 text-[13px] text-sp-text-muted">{emptySearchLabel}</p>
      ) : null}
      {collapsible && !expanded && hiddenCount > 0 ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => setExpanded(true)}
          className="text-[13px] font-medium text-sp-blue hover:underline disabled:opacity-60"
        >
          Показать ещё ({hiddenCount})
        </button>
      ) : null}
    </div>
  );

  if (!searchable) {
    return checkboxList;
  }

  const searchInput = (
    <input
      type="search"
      value={facetQuery}
      onChange={(e) => setFacetQuery(e.target.value)}
      placeholder={searchPlaceholder}
      disabled={disabled}
      className="w-full rounded-xl border border-sp-border bg-white px-3 py-2 text-[14px] text-sp-text-primary outline-none sp-transition focus:border-sp-blue disabled:opacity-60"
      aria-label={searchPlaceholder}
    />
  );

  if (variant === "popover") {
    return (
      <div className="flex max-h-60 flex-col">
        <div className="sticky top-0 z-10 shrink-0 space-y-2 bg-white pb-2">
          {searchInput}
          {selectedChips}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain">{checkboxList}</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {searchInput}
      {selectedChips}
      {checkboxList}
    </div>
  );
}

export function CatalogFiltersPanel({
  layout,
  fixedTopCategory,
  showSportTabs = !fixedTopCategory,
  showCategoryFilter = true,
  activeFilter,
  onActiveFilterChange,
  catalogLabels,
  categories,
  brands,
  facets,
  facetsLoading = false,
  facetsOptionsLoading = false,
  priceBoundsMin,
  priceBoundsMax,
  priceBoundsLoading = false,
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
  priceResetToken = "",
  sortPrice = "",
  onSortPriceChange,
  onResetFilters,
  productCountLabel = null,
  compactSheet = false,
}: CatalogFiltersPanelProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const isPanel = layout === "sidebar" || layout === "sheet";

  const expandNonceRef = useRef<Partial<Record<SectionKey, number>>>({});
  const [, bumpExpandNonce] = useState(0);

  const expandSection = useCallback(
    (section: SectionKey) => {
      saveFilterSectionsState(location.pathname, { [section]: true });
      expandNonceRef.current[section] = (expandNonceRef.current[section] ?? 0) + 1;
      bumpExpandNonce((n) => n + 1);
    },
    [location.pathname],
  );

  const labels =
    catalogLabels ??
    ({
      sport_types: {},
      category_l2: {},
      genders: {},
      filter_all: "Все",
      product_fallback: "Товар",
    } satisfies CatalogLabelsConfig);

  const showSliceFilters = Boolean(
    fixedTopCategory === CATALOG_ALL_TOP || fixedTopCategory || activeFilter !== "All",
  );

  const genderFallback: CatalogFacetOption[] = Object.entries(labels.genders).map(
    ([value, label_ru]) => ({ value, label_ru, count: 0 }),
  );

  const categoryOptions: CatalogFacetOption[] = categories.map((c) => ({
    value: c.key,
    label_ru: c.label_ru,
    count: 0,
  }));

  const brandSelected = parseFacetListValue(brand, "brand");
  const genderSelected = parseFacetListValue(gender, "gender");
  const colorSelected = parseFacetListValue(color, "color");
  const sizeSelected = parseFacetListValue(size, "size");

  const brandOptions = facetOptionsWithSelected(
    facetOptions(
      facets?.brands,
      brands.map((b) => ({ value: b, label_ru: b, count: 0 })),
    ),
    brandSelected,
  );
  const genderOptions = facetOptionsWithSelected(
    facetOptions(facets?.genders, genderFallback),
    genderSelected,
  );
  const colorOptions = facetOptionsWithSelected(
    facets?.colors?.length ? facets.colors : emptyOption(isPanel),
    colorSelected,
  );
  const sizeOptions = facetOptionsWithSelected(
    facets?.sizes?.length ? facets.sizes : emptyOption(isPanel),
    sizeSelected,
  );

  const showBrand = isPanel || (facets?.brands?.length ?? 0) > 0 || brands.length > 0;
  const showGender = isPanel || (facets?.genders?.length ?? 0) > 0;
  const showColor = isPanel || (facets?.colors?.length ?? 0) > 0;
  const showSize = isPanel || (facets?.sizes?.length ?? 0) > 0;
  const showPrice =
    isPanel || (facets?.price_min != null && facets?.price_max != null);

  const brandDisabled =
    facetsLoading ||
    facetsOptionsLoading ||
    (brandOptions.length === 1 && brandOptions[0]?.value === "") ||
    (!isPanel && !category && fixedTopCategory !== CATALOG_ALL_TOP);

  const facetDisabled = (options: CatalogFacetOption[]) =>
    facetsLoading ||
    facetsOptionsLoading ||
    (options.length === 1 && options[0]?.value === "");

  const handleCategoryChange = (value: string) => {
    onCategoryChange(value);
    if (value) expandSection("category");
  };
  const handleBrandChange = (value: string) => {
    onBrandChange(value);
    if (value) expandSection("brand");
  };
  const handleGenderChange = (value: string) => {
    onGenderChange(value);
    if (value) expandSection("gender");
  };
  const handleColorChange = (value: string) => {
    onColorChange(value);
    if (value) expandSection("color");
  };
  const handleSizeChange = (value: string) => {
    onSizeChange(value);
    if (value) expandSection("size");
  };

  const hasActiveFilters = Boolean(
    category ||
      brand ||
      gender ||
      color ||
      size ||
      priceMin.trim() ||
      priceMax.trim() ||
      sortPrice,
  );

  const handleResetFilters = () => {
    onResetFilters?.();
    clearFilterSectionsState(location.pathname);
    expandNonceRef.current = {};
    bumpExpandNonce((n) => n + 1);
  };

  const panelFilters = showSliceFilters ? (
    <>
      {showPrice ? (
        <CatalogPriceSlider
          boundsMin={priceBoundsMin}
          boundsMax={priceBoundsMax}
          boundsLoading={priceBoundsLoading}
          priceMin={priceMin}
          priceMax={priceMax}
          onPriceMinChange={onPriceMinChange}
          onPriceMaxChange={onPriceMaxChange}
          resetToken={priceResetToken}
          onPriceRangeChange={onPriceRangeChange}
        />
      ) : null}

      {onSortPriceChange ? (
        <CatalogPriceSort
          sortPrice={sortPrice}
          onSortPriceChange={onSortPriceChange}
          resetToken={priceResetToken}
        />
      ) : null}

      {showCategoryFilter ? (
        <FilterSection
          title="Категория"
          section="category"
          resetToken={priceResetToken}
          expandNonce={expandNonceRef.current.category ?? 0}
        >
          <CheckboxList
            options={categoryOptions}
            selected={category ? [category] : []}
            onToggle={(value) => toggleSingle(category, value, handleCategoryChange)}
            disabled={facetsLoading}
          />
        </FilterSection>
      ) : null}

      {showBrand ? (
        <FilterSection
          title="Бренд"
          section="brand"
          resetToken={priceResetToken}
          expandNonce={expandNonceRef.current.brand ?? 0}
        >
          <CheckboxList
            options={brandOptions}
            selected={brandSelected}
            onToggle={(value) => handleBrandChange(toggleFacetListValue(brand, value, "brand"))}
            disabled={brandDisabled}
            showCounts
            searchable
            collapsible
            searchPlaceholder="Найти бренд…"
            resetToken={priceResetToken}
            emptySearchLabel="Бренд не найден"
          />
        </FilterSection>
      ) : null}

      {showGender ? (
        <FilterSection
          title="Пол"
          section="gender"
          resetToken={priceResetToken}
          expandNonce={expandNonceRef.current.gender ?? 0}
        >
          <CheckboxList
            options={genderOptions}
            selected={genderSelected}
            onToggle={(value) => handleGenderChange(toggleFacetListValue(gender, value, "gender"))}
            disabled={facetDisabled(genderOptions)}
            loading={facetsOptionsLoading}
            showCounts
            searchable
            searchPlaceholder="Найти…"
            resetToken={priceResetToken}
            emptySearchLabel="Ничего не найдено"
          />
        </FilterSection>
      ) : null}

      {showColor ? (
        <FilterSection
          title="Цвет"
          section="color"
          resetToken={priceResetToken}
          expandNonce={expandNonceRef.current.color ?? 0}
        >
          <CheckboxList
            options={colorOptions}
            selected={colorSelected}
            onToggle={(value) => handleColorChange(toggleFacetListValue(color, value, "color"))}
            disabled={facetDisabled(colorOptions)}
            loading={facetsOptionsLoading}
            showCounts
            searchable
            collapsible
            searchPlaceholder="Найти цвет…"
            resetToken={priceResetToken}
            emptySearchLabel="Цвет не найден"
          />
        </FilterSection>
      ) : null}

      {showSize ? (
        <FilterSection
          title="Размер"
          section="size"
          resetToken={priceResetToken}
          expandNonce={expandNonceRef.current.size ?? 0}
        >
          <CheckboxList
            options={sizeOptions}
            selected={sizeSelected}
            onToggle={(value) => handleSizeChange(toggleFacetListValue(size, value, "size"))}
            disabled={facetDisabled(sizeOptions)}
            loading={facetsOptionsLoading}
            showCounts
            searchable
            collapsible
            searchPlaceholder="Найти размер…"
            resetToken={priceResetToken}
            emptySearchLabel="Размер не найден"
          />
        </FilterSection>
      ) : null}
    </>
  ) : null;

  if (isPanel) {
    const sportTabsBlock = showSportTabs ? (
      <div className="mb-5 flex flex-col gap-2 border-b border-sp-border pb-5">
        {sportFilters.map((f) => {
          const active = activeFilter === f;
          return (
            <button
              key={f}
              type="button"
              onClick={() => {
                if (f === "All") {
                  onActiveFilterChange("All");
                  navigate(catalogAllPath());
                  return;
                }
                navigate(catalogSportPath(f));
              }}
              className={`rounded-xl px-4 py-3 text-left text-[14px] font-medium sp-transition ${
                active
                  ? "bg-sp-blue text-white"
                  : "border border-sp-border bg-white text-sp-text-primary hover:border-sp-blue"
              }`}
            >
              {filterTabLabel(f, labels)}
            </button>
          );
        })}
      </div>
    ) : null;

    const homeRow = !showSportTabs ? (
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => navigate("/catalog")}
          className="group flex min-w-0 items-center gap-1 text-sp-blue"
        >
          <ChevronLeft size={16} className="shrink-0" />
          <span className="text-[14px] font-medium group-hover:underline">Главная</span>
        </button>
        {productCountLabel ? (
          <span className="min-w-0 shrink-0 truncate text-right text-[14px] text-sp-text-secondary">
            {productCountLabel}
          </span>
        ) : null}
      </div>
    ) : null;

    const filtersTitleRow = (
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 text-[11px] font-semibold uppercase tracking-[0.1em] text-sp-text-muted">
          Фильтры
          {facetsLoading ? <span className="ml-2">…</span> : null}
        </h3>
        {hasActiveFilters && onResetFilters ? (
          <button
            type="button"
            onClick={handleResetFilters}
            className="shrink-0 text-[13px] font-medium text-sp-blue hover:underline"
          >
            Сбросить
          </button>
        ) : null}
      </div>
    );

    if (layout === "sheet") {
      if (compactSheet) {
        return (
          <div className="flex flex-col">
            {hasActiveFilters && onResetFilters ? (
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  onClick={handleResetFilters}
                  className="shrink-0 text-[12px] font-medium text-sp-blue hover:underline"
                >
                  Сбросить
                </button>
              </div>
            ) : null}
            {panelFilters}
          </div>
        );
      }

      return (
        <div
          data-testid="catalog-filters-sheet"
          className="flex h-full min-h-0 w-full flex-col overflow-hidden"
        >
          <div
            data-testid="catalog-filters-sheet-header"
            className="z-10 shrink-0 border-b border-sp-border bg-sp-surface"
          >
            <div className={`px-4 pt-4 pr-12 ${homeRow ? "pb-2" : "pb-3"}`}>{homeRow}</div>
            <div className="px-4 pb-3">{filtersTitleRow}</div>
          </div>
          <div
            data-testid="catalog-filters-sheet-body"
            className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-4"
          >
            {panelFilters}
          </div>
        </div>
      );
    }

    return (
      <aside
        data-testid="catalog-filter-sidebar"
        className="catalog-filter-sidebar sticky top-24 z-[2] flex w-full max-h-[calc(100vh-7.5rem)] flex-col overflow-hidden overscroll-y-contain"
        style={{
          background: "var(--sp-surface)",
          border: "1px solid var(--sp-border)",
          borderRadius: "var(--sp-radius-card)",
        }}
      >
        <div
          data-testid="catalog-filter-sidebar-header"
          className="z-10 shrink-0 border-b border-sp-border px-6 pt-6 pb-3"
          style={{ background: "var(--sp-surface)" }}
        >
          {homeRow ? <div className="pb-2">{homeRow}</div> : null}
          {filtersTitleRow}
        </div>
        <div
          data-testid="catalog-filter-sidebar-body"
          className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-6 pb-6 pt-4"
        >
          {sportTabsBlock}
          {panelFilters}
        </div>
      </aside>
    );
  }

  return (
    <div className="flex gap-2 flex-wrap items-center">
      {showSportTabs
        ? sportFilters.map((f) => {
            const active = activeFilter === f;
            return (
              <button
                key={f}
                type="button"
                onClick={() => {
                  if (f === "All") {
                    onActiveFilterChange("All");
                    navigate(catalogAllPath());
                    return;
                  }
                  navigate(catalogSportPath(f));
                }}
                className={`text-[14px] font-medium px-5 py-2 rounded-full sp-transition ${
                  active
                    ? "bg-sp-blue text-white"
                    : "bg-white text-sp-text-secondary border border-sp-border hover:border-sp-blue"
                }`}
              >
                {filterTabLabel(f, labels)}
              </button>
            );
          })
        : null}
      {showSliceFilters ? (
        <div className="flex gap-2 flex-wrap items-center w-full mt-2">
          {showCategoryFilter ? (
            <select
              value={category}
              onChange={(e) => onCategoryChange(e.target.value)}
              className="text-[14px] px-4 py-2 border border-sp-border rounded-xl bg-white text-sp-text-primary"
              aria-label="Категория"
            >
              <option value="">Категория</option>
              {categories.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label_ru}
                </option>
              ))}
            </select>
          ) : null}
          {showBrand ? (
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  disabled={brandDisabled}
                  className="text-[14px] px-4 py-2 border border-sp-border rounded-xl bg-white text-sp-text-primary disabled:opacity-60 text-left min-w-[120px]"
                  aria-label="Бренд"
                >
                  {brandSelected.length
                    ? `Бренд (${brandSelected.length})`
                    : "Бренд"}
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-64 max-h-72 overflow-hidden p-3 bg-white border-sp-border">
                <CheckboxList
                  options={brandOptions}
                  selected={brandSelected}
                  onToggle={(value) => handleBrandChange(toggleFacetListValue(brand, value, "brand"))}
                  disabled={brandDisabled}
                  showCounts
                  searchable
                  collapsible
                  variant="popover"
                  searchPlaceholder="Найти бренд…"
                  resetToken={priceResetToken}
                  emptySearchLabel="Бренд не найден"
                />
              </PopoverContent>
            </Popover>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
