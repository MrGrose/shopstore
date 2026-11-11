import { ProductGrid } from "../components/ProductGrid";
import { CATALOG_ALL_TOP } from "../../lib/storefront/catalogNavigation";
import { useStorefrontCompactPagePad } from "../../lib/storefront/useStorefrontSurface";

export function CatalogPage() {
  const pagePad = useStorefrontCompactPagePad();

  return (
    <div className={`${pagePad} shrink-0`}>
      <ProductGrid
        fixedTopCategory={CATALOG_ALL_TOP}
        filterLayout="sidebar"
        sectionTitle="Все товары"
      />
    </div>
  );
}
