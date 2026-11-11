import { Navigate, useParams } from "react-router";
import { ProductGrid } from "../components/ProductGrid";
import {
  CATALOG_ALL_LABEL_RU,
  CATALOG_ALL_TOP,
  catalogAllPath,
  isCatalogRouteSlug,
  resolveCatalogTopFromSlug,
} from "../../lib/storefront/catalogNavigation";
import { useStorefrontCompactPagePad } from "../../lib/storefront/useStorefrontSurface";

export function SportCatalogPage() {
  const { sport } = useParams<{ sport: string }>();
  const pagePad = useStorefrontCompactPagePad();

  if (sport === "all") {
    return <Navigate to={catalogAllPath()} replace />;
  }

  if (!isCatalogRouteSlug(sport)) {
    return <Navigate to={catalogAllPath()} replace />;
  }

  const topCategory = resolveCatalogTopFromSlug(sport);

  return (
    <div className={`${pagePad} shrink-0`}>
      <ProductGrid
        fixedTopCategory={topCategory}
        filterLayout="sidebar"
        sectionTitle={topCategory === CATALOG_ALL_TOP ? CATALOG_ALL_LABEL_RU : undefined}
      />
    </div>
  );
}
