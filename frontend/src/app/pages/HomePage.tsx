import { useEffect } from "react";

import { Hero } from "../components/Hero";
import { useCatalogReferencePrefetch } from "../../lib/storefront/prefetchCatalogReference";

export function HomePage() {
  const prefetchCatalogReference = useCatalogReferencePrefetch();

  useEffect(() => {
    prefetchCatalogReference();
  }, [prefetchCatalogReference]);

  return (
    <div className="h-full min-h-0 overflow-hidden">
      <Hero />
    </div>
  );
}
