import type { ReactNode } from "react";

import type { CatalogTopScope } from "../../../lib/storefront/catalogNavigation";

export type CatalogGridLayoutProps = {
  compact: boolean;
  filterLayout: "inline" | "sidebar";
  filterToTopCategory: CatalogTopScope | null;
  productCountLabel: string | null;
  miniAppSearchBar: ReactNode;
  searchBanner: ReactNode;
  categoryNav: ReactNode;
  filtersSheet: ReactNode;
  sidebarFilters: ReactNode;
  inlineFilters: ReactNode;
  productList: ReactNode;
};

export function CatalogGridLayout({
  compact,
  filterLayout,
  filterToTopCategory,
  productCountLabel,
  miniAppSearchBar,
  searchBanner,
  categoryNav,
  filtersSheet,
  sidebarFilters,
  inlineFilters,
  productList,
}: CatalogGridLayoutProps) {
  if (compact) {
    return (
      <>
        {miniAppSearchBar}
        {categoryNav}
        {filterToTopCategory ? (
          <div className="mb-3 flex items-center gap-2">
            {filtersSheet}
            {productCountLabel ? (
              <span className="shrink-0 text-[11px] text-sp-text-secondary">{productCountLabel}</span>
            ) : null}
          </div>
        ) : null}
        {searchBanner}
        {productList}
      </>
    );
  }

  if (filterLayout === "sidebar" && filterToTopCategory) {
    return (
      <>
        {searchBanner}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[320px_1fr] lg:items-start">
          <div className="hidden lg:block">{sidebarFilters}</div>
          <div>
            <div className="mb-6 lg:hidden">{filtersSheet}</div>
            {categoryNav}
            {productList}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {searchBanner}
      <div className="mb-10">{inlineFilters}</div>
      {categoryNav}
      {productList}
    </>
  );
}
