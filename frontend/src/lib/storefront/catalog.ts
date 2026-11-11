/**
 * Каталог — эндпоинты как в ProductGrid / storefront-catalog-grid.js
 */

import { storefrontApiFetch } from "./api";
import type { CatalogSportSlug } from "./catalogNavigation";

export type CatalogListParams = {
  page?: number;
  page_size?: number;
  top_category?: string;
  section?: string;
  node?: string;
  sub?: string;
  category_type?: string;
  category?: string;
  categories?: string;
  category_l3?: string;
  brand?: string;
  gender?: string;
  color?: string;
  size?: string;
  price_min?: number | string;
  price_max?: number | string;
  q?: string;
  include?: string;
  sort_price?: string;
};

export type CatalogProductListResponse = {
  items: unknown[];
  total?: number | null;
  has_more?: boolean;
  total_pages?: number | null;
  page?: number;
  page_size?: number;
};

export type CatalogFacetOption = {
  value: string;
  label_ru: string;
  count: number;
};

export type CatalogFacets = {
  brands: CatalogFacetOption[];
  genders: CatalogFacetOption[];
  colors: CatalogFacetOption[];
  sizes: CatalogFacetOption[];
  price_min: number | string | null;
  price_max: number | string | null;
};

// Берёт category keys из navigation.url_params или passthrough scope для backend compat.
export function resolveCatalogCategoryApiParams(
  sub: string,
  productType: string,
  urlParams?: Record<string, string> | null,
): Pick<CatalogListParams, "sub" | "category_type" | "section" | "node"> {
  if (urlParams && Object.keys(urlParams).length > 0) {
    return {
      section: urlParams.section,
      node: urlParams.node,
      sub: urlParams.sub,
      category_type: urlParams.category_type,
    };
  }
  const subTrim = sub.trim();
  const typeTrim = productType.trim();
  return {
    sub: subTrim || undefined,
    section: subTrim || undefined,
    category_type: typeTrim || undefined,
    node: typeTrim || undefined,
  };
}

function appendCatalogParams(qs: URLSearchParams, params: CatalogListParams) {
  if (params.page != null) qs.set("page", String(params.page));
  if (params.page_size != null) qs.set("page_size", String(params.page_size));
  if (params.top_category) qs.set("top_category", params.top_category);
  if (params.section) qs.set("section", params.section);
  if (params.node) qs.set("node", params.node);
  if (params.sub) qs.set("sub", params.sub);
  if (params.category_type) qs.set("category_type", params.category_type);
  if (params.category) qs.set("category", params.category);
  if (params.categories) qs.set("categories", params.categories);
  if (params.category_l3) qs.set("category_l3", params.category_l3);
  if (params.brand) qs.set("brand", params.brand);
  if (params.gender) qs.set("gender", params.gender);
  if (params.color) qs.set("color", params.color);
  if (params.size) qs.set("size", params.size);
  if (params.price_min != null && params.price_min !== "") {
    qs.set("price_min", String(params.price_min));
  }
  if (params.price_max != null && params.price_max !== "") {
    qs.set("price_max", String(params.price_max));
  }
  if (params.q?.trim()) qs.set("q", params.q.trim());
  if (params.include?.trim()) qs.set("include", params.include.trim());
  if (params.sort_price?.trim()) qs.set("sort_price", params.sort_price.trim());
}

export function buildProductsQuery(params: CatalogListParams): string {
  const qs = new URLSearchParams();
  appendCatalogParams(qs, params);
  return qs.toString();
}

export async function fetchProducts(params: CatalogListParams): Promise<CatalogProductListResponse> {
  const q = buildProductsQuery(params);
  return storefrontApiFetch<CatalogProductListResponse>(`/products?${q}`);
}

export async function fetchCatalogProductCount(
  params: Omit<CatalogListParams, "page" | "page_size" | "sort_price" | "include">,
): Promise<number> {
  const qs = new URLSearchParams();
  appendCatalogParams(qs, params);
  const data = await storefrontApiFetch<{ total: number }>(`/products/count?${qs}`);
  return Number(data.total) || 0;
}


export async function fetchCatalogProductMeta(
  params: Omit<CatalogListParams, "page" | "page_size" | "sort_price">,
): Promise<{ total: number; facets: CatalogFacets }> {
  const qs = new URLSearchParams();
  appendCatalogParams(qs, params);
  if (!params.include?.trim()) {
    qs.set("include", "all");
  }
  const data = await storefrontApiFetch<{ total: number; facets: CatalogFacets }>(
    `/products/meta?${qs}`,
  );
  return { total: Number(data.total) || 0, facets: data.facets };
}

export async function fetchCatalogFacetsByQueryKey(
  queryKey: string,
  include: string,
): Promise<CatalogFacets> {
  const qs = queryKey ? `${queryKey}&include=${include}` : `include=${include}`;
  return storefrontApiFetch<CatalogFacets>(`/products/facets?${qs}`);
}

export type CatalogLabelItem = { key: string; label_ru: string };

export type CatalogSubCategoryType = {
  key: string;
  label_ru: string;
  count: number;
};

export type CatalogSubCategoryItem = {
  slug: string;
  label: string;
  type_level?: "l2" | "l3" | "chip";
  types: CatalogSubCategoryType[];
};

export async function fetchCatalogSubcategories(
  topCategory: string,
  sub?: string,
  section?: string,
): Promise<CatalogSubCategoryItem[]> {
  const qs = new URLSearchParams({ top_category: topCategory, locale: "ru" });
  if (section?.trim()) qs.set("section", section.trim());
  else if (sub?.trim()) qs.set("sub", sub.trim());
  return storefrontApiFetch(`/products/subcategories?${qs}`);
}

export type CatalogNavigationLink = {
  label: string;
  url_params: Record<string, string>;
};

export type CatalogNavigationActiveNode = {
  sub: string;
  category_type: string;
  section_label?: string | null;
  type_label?: string | null;
};

export type CatalogNavigation = {
  top_category: string;
  use_mapping_params: boolean;
  sub: string;
  category_type: string;
  url_params: Record<string, string>;
  active_node?: CatalogNavigationActiveNode | null;
  breadcrumbs: CatalogNavigationLink[];
  subcategories: CatalogSubCategoryItem[];
};

export type CatalogNavigationParams = {
  top_category: string;
  sub?: string;
  section?: string;
  node?: string;
  category_type?: string;
};

export async function fetchCatalogNavigation(
  params: CatalogNavigationParams,
): Promise<CatalogNavigation> {
  const qs = new URLSearchParams({ top_category: params.top_category });
  if (params.section?.trim()) qs.set("section", params.section.trim());
  if (params.node?.trim()) qs.set("node", params.node.trim());
  if (params.sub?.trim()) qs.set("sub", params.sub.trim());
  if (params.category_type?.trim()) qs.set("category_type", params.category_type.trim());
  return storefrontApiFetch<CatalogNavigation>(`/catalog/navigation?${qs}`);
}

export type CatalogTaxonomyChip = {
  display_key: string;
  slug: string;
  label: string;
};

export type CatalogTaxonomySection = {
  slug: string;
  label: string;
  chips: CatalogTaxonomyChip[];
};

export type CatalogTaxonomySub = {
  slug: string;
  label: string;
  category_l2: string[];
};

export type CatalogTaxonomySport = {
  sport: string;
  slug: CatalogSportSlug;
  label: string;
  sections?: CatalogTaxonomySection[];
  subcategories: CatalogTaxonomySub[];
};

export type CatalogTaxonomy = {
  sports: CatalogTaxonomySport[];
  sub_slug_aliases: Record<string, Record<string, string>>;
};

export async function fetchCatalogTaxonomy(): Promise<CatalogTaxonomy> {
  return storefrontApiFetch<CatalogTaxonomy>("/catalog/taxonomy");
}

export async function fetchCategories(topCategory: string): Promise<CatalogLabelItem[]> {
  const qs = new URLSearchParams({ top_category: topCategory });
  return storefrontApiFetch(`/products/categories?${qs}`);
}

export async function fetchBrands(topCategory: string, category: string) {
  const qs = new URLSearchParams({ top_category: topCategory, category });
  return storefrontApiFetch(`/products/brands?${qs}`);
}

export async function fetchProduct(productId: number) {
  return storefrontApiFetch(`/product/${productId}`);
}
