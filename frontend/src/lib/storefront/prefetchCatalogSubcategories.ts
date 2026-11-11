import { CATALOG_SPORTS, SPORT_TO_SLUG, type CatalogSport } from "./catalogNavigation";
import { fetchCatalogSubcategories, fetchCatalogTaxonomy } from "./catalog";
import { getTaxonomySport } from "./catalogCategoryFilter";
import { queryClient } from "../../lib/queryClient";
import {
  catalogSubcategoriesQueryKey,
  CATALOG_SUBCATEGORIES_STALE_MS,
} from "../../hooks/useCatalogSubcategories";
import { catalogTaxonomyQueryKey } from "../../hooks/useCatalogTaxonomy";

const STAGGER_MS = 40;

function idleRun(task: () => void): void {
  if (typeof requestIdleCallback !== "undefined") {
    requestIdleCallback(task, { timeout: 4000 });
    return;
  }
  window.setTimeout(task, 300);
}

async function prefetchSportSubcategories(sport: CatalogSport): Promise<void> {
  const taxonomy = await queryClient.fetchQuery({
    queryKey: catalogTaxonomyQueryKey,
    queryFn: fetchCatalogTaxonomy,
  });
  const sportDef = getTaxonomySport(taxonomy, SPORT_TO_SLUG[sport]);
  if (!sportDef) return;

  for (const sub of sportDef.subcategories) {
    const queryKey = catalogSubcategoriesQueryKey(sport, sub.slug);
    const state = queryClient.getQueryState(queryKey);
    if (state?.dataUpdatedAt && Date.now() - state.dataUpdatedAt < CATALOG_SUBCATEGORIES_STALE_MS) {
      continue;
    }
    try {
      await queryClient.prefetchQuery({
        queryKey,
        queryFn: () => fetchCatalogSubcategories(sport, sub.slug),
        staleTime: CATALOG_SUBCATEGORIES_STALE_MS,
      });
    } catch {
      // фоновый prefetch — ошибки не блокируют UI
    }
    await new Promise<void>((resolve) => window.setTimeout(resolve, STAGGER_MS));
  }
}

// В фоне подгружает types для всех подкатегорий Padel/Tennis/Running.
export function scheduleMiniAppCatalogPrefetch(): void {
  idleRun(() => {
    void (async () => {
      for (const sport of CATALOG_SPORTS) {
        await prefetchSportSubcategories(sport);
      }
    })();
  });
}
