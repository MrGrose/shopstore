export type CatalogFilterSectionKey =
  | "sort"
  | "category"
  | "brand"
  | "gender"
  | "color"
  | "size";

export type CatalogFilterSectionsState = Record<CatalogFilterSectionKey, boolean>;

export const DEFAULT_FILTER_SECTIONS: CatalogFilterSectionsState = {
  sort: false,
  category: false,
  brand: false,
  gender: false,
  color: false,
  size: false,
};

const sectionsStorageKey = (pathname: string) => `catalog-filter-sections:${pathname}`;

export function loadFilterSectionsState(pathname: string): CatalogFilterSectionsState {
  try {
    const raw = sessionStorage.getItem(sectionsStorageKey(pathname));
    if (!raw) return { ...DEFAULT_FILTER_SECTIONS };
    const parsed = JSON.parse(raw) as Partial<CatalogFilterSectionsState>;
    return { ...DEFAULT_FILTER_SECTIONS, ...parsed };
  } catch {
    return { ...DEFAULT_FILTER_SECTIONS };
  }
}

export function saveFilterSectionsState(
  pathname: string,
  patch: Partial<CatalogFilterSectionsState>,
): void {
  const next = { ...loadFilterSectionsState(pathname), ...patch };
  sessionStorage.setItem(sectionsStorageKey(pathname), JSON.stringify(next));
}

export function clearFilterSectionsState(pathname: string): void {
  sessionStorage.removeItem(sectionsStorageKey(pathname));
}
