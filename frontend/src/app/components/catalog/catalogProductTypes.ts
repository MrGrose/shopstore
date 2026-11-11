import { resolveProductImageUrl } from "../../../lib/storefront/imageResolver";

export const CATALOG_PAGE_SIZE = 20;
export const CATALOG_CARD_GALLERY_LIMIT = 5;

export type CatalogProductCardImage = {
  url: string;
  fallback_url?: string | null;
  position: number;
};

export type CatalogCardGalleryCandidate = {
  key: string;
  url: string;
  fallbackUrl: string | null;
};

export type CatalogProductCardData = {
  id: number;
  title: string;
  display_title?: string;
  brand: string;
  description?: string | null;
  image_url?: string | null;
  image_urls?: Partial<Record<string, string>> | null;
  images?: CatalogProductCardImage[] | null;
  sale_price: number | string;
  regular_price: number | string;
  category_l1?: string | null;
  category_l2?: string | null;
  category_l3?: string | null;
  sport_type?: string | null;
  sport_type_label_ru?: string;
  category_l2_label_ru?: string;
  gender_label_ru?: string;
  shipping_estimate?: string | null;
  available_stock?: number;
  buyable_qty?: number;
  stock_status?: "in_stock" | "low" | "last" | "out_of_stock";
};

export function catalogGalleryCandidateKey(image: CatalogProductCardImage): string {
  return `${image.position}:${image.url.trim()}`;
}

export function catalogCoverCandidateKey(resolvedCoverUrl: string): string {
  return `cover:${resolvedCoverUrl.trim()}`;
}

export function resolveCoverImage(
  product: CatalogProductCardData,
  compact = false,
): string | null {
  const context = compact ? "catalog_card_compact" : "catalog_card_desktop";
  return resolveProductImageUrl(product, context);
}

function supplierFallbackUrl(image: CatalogProductCardImage): string | null {
  const value = image.fallback_url?.trim();
  return value || null;
}

export function resolveCatalogCardGalleryCandidates(
  product: CatalogProductCardData,
  compact = false,
): CatalogCardGalleryCandidate[] {
  const context = compact ? "catalog_card_compact" : "catalog_card_desktop";
  const fromGallery = [...(product.images ?? [])]
    .sort((left, right) => left.position - right.position)
    .slice(0, CATALOG_CARD_GALLERY_LIMIT)
    .map((image) => {
      const url = resolveProductImageUrl(image.url, context);
      if (!url) return null;
      return {
        key: catalogGalleryCandidateKey(image),
        url,
        fallbackUrl: supplierFallbackUrl(image),
      };
    })
    .filter((candidate): candidate is CatalogCardGalleryCandidate => candidate !== null);
  if (fromGallery.length > 0) return fromGallery;
  const cover = resolveCoverImage(product, compact);
  return cover
    ? [{ key: catalogCoverCandidateKey(cover), url: cover, fallbackUrl: null }]
    : [];
}

export function formatProductCount(total: number): string {
  const n = Math.max(0, Math.round(total));
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return `${n.toLocaleString("ru-RU")} товаров`;
  if (mod10 === 1) return `${n.toLocaleString("ru-RU")} товар`;
  if (mod10 >= 2 && mod10 <= 4) return `${n.toLocaleString("ru-RU")} товара`;
  return `${n.toLocaleString("ru-RU")} товаров`;
}
