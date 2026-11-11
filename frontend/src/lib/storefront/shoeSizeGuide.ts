import { storefrontApiFetch, storefrontApiFetchText } from "./api";

export function openShoeSizeGuide(brand: string, title?: string) {
  const normalizedBrand = brand.trim();
  if (!normalizedBrand) return;
  window.dispatchEvent(
    new CustomEvent("store:shoe-size-guide:open", {
      detail: {
        brand: normalizedBrand,
        title: title ?? `Таблица размеров — ${normalizedBrand}`,
      },
    }),
  );
}

export async function fetchShoeSizeGuideHtml(brand: string): Promise<string> {
  const normalizedBrand = brand.trim();
  if (!normalizedBrand) throw new Error("Бренд не указан");
  return storefrontApiFetchText(
    `/storefront/shoe-size-guide/${encodeURIComponent(normalizedBrand)}`,
  );
}

export async function shoeSizeGuideAvailable(brand: string): Promise<boolean> {
  const normalizedBrand = brand.trim();
  if (!normalizedBrand) return false;
  const data = await storefrontApiFetch<{ available?: boolean }>(
    `/storefront/shoe-size-guide-available?brand=${encodeURIComponent(normalizedBrand)}`,
  );
  return Boolean(data?.available);
}
