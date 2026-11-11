import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type CSSProperties } from "react";
import {
  resolveVariantBuyableQty,
  stockStatusExtraClass,
} from "../../../lib/storefront/variantStock";
import { useLocation, useNavigate } from "react-router";
import { ArrowLeft, Check, ShoppingBag, Trash2, Truck, X } from "lucide-react";
import { moneyRub } from "../../../lib/storefront/checkoutUi";
import { catalogAllPath } from "../../../lib/storefront/catalogNavigation";
import {
  getCatalogScrollRoot,
  shouldPopProductBack,
  writeCatalogScrollTop,
} from "../../../lib/storefront/catalogScrollRestore";
import {
  MINIAPP_BOTTOM_NAV_OFFSET,
  PDP_COMPACT_SCROLL_PAD,
  PDP_MINIAPP_SCROLL_PAD,
} from "../../../lib/storefront/miniApp";
import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";
import { resolveProductImageUrl } from "../../../lib/storefront/imageResolver";
import { PRODUCT_PLACEHOLDER } from "../../../lib/storefront/productPlaceholder";
import { ImageWithFallback } from "../figma/ImageWithFallback";
import { Skeleton } from "../ui/skeleton";
import { adjustGalleryActiveIndex } from "../../../lib/storefront/galleryActiveIndex";
import { sportBadgePillClass, resolveSportCategory } from "../../../lib/storefront/sportBadge";
import { useStorefrontCompact, useStorefrontBottomNav, useStorefrontCompactPagePad, pdpHeroFrameClassName, pdpHeroGridClassName, pdpHeroPageClassName } from "../../../lib/storefront/useStorefrontSurface";
import {
  buyerStockBadgeParts,
  DEFAULT_STOCK_DISPLAY,
  fetchStockDisplayConfig,
  variantQtyForChipHover,
  type StockDisplayConfig,
} from "../../../lib/storefront/stockDisplay";
import { openShoeSizeGuide } from "../../../lib/storefront/shoeSizeGuide";
import { resolveVariantSelectionFromConstraints } from "../../../lib/storefront/catalogVariantPreset";
import type { VariantConstraintPreset } from "../../../lib/storefront/variantConstraintTypes";
import {
  findMatchingVariant,
  firstInStockSelection,
  fmtOpt,
  getVariantOptionKeys,
  getVisibleVariantOptionKeys,
  isValueAvailable,
  isVariantInStock,
  selectionFromVariant,
  type OptionKey,
} from "../../../lib/storefront/variantSelection";


export type ProductDetailData = {
  id: number;
  title: string;
  display_title?: string;
  brand: string;
  description?: string | null;
  image_url?: string | null;
  image_urls?: Partial<Record<string, string>> | null;
  sale_price: number | string;
  sport_type?: string | null;
  sport_type_label_ru?: string;
  category_l2?: string | null;
  category_l2_label_ru?: string;
  category_l3_label_ru?: string;
  shipping_estimate?: string | null;
  images?: Array<{ id: number; url: string; alt?: string | null; position: number; fallback_url?: string | null }>;
  features?: Array<{
    id: number;
    name: string;
    name_ru?: string;
    value?: string | null;
    value_ru?: string;
    icon_url?: string | null;
    position: number;
  }>;
  variants?: Array<{
    id: number;
    option1?: string | null;
    option2?: string | null;
    option3?: string | null;
    option1_ru?: string;
    option2_ru?: string;
    option3_ru?: string;
    inventory_quantity: number;
    available_quantity?: number | null;
    available: boolean;
    buyable_qty?: number;
    stock_status?: "in_stock" | "low" | "last" | "out_of_stock";
  }>;
  buyable_qty?: number;
  stock_status?: "in_stock" | "low" | "last" | "out_of_stock";
  available_stock?: number;
  variant_option_labels?: Partial<Record<OptionKey, string>>;
  variant_option_values?: Partial<Record<OptionKey, string[]>>;
  variant_option_values_ru?: Partial<Record<OptionKey, Record<string, string>>>;
  variant_options_hidden?: string[];
  variant_display_titles?: Record<string, string>;
  show_shoe_size_guide?: boolean;
};

const galleryNavBtnStyle: CSSProperties = {
  position: "absolute",
  top: "50%",
  transform: "translateY(-50%)",
  width: 44,
  height: 44,
  borderRadius: 999,
  border: "1px solid var(--sp-border)",
  background: "var(--sp-surface)",
  color: "var(--sp-text-primary)",
  cursor: "pointer",
  fontSize: "1.25rem",
  lineHeight: 1,
  zIndex: 2,
  boxShadow: "var(--sp-shadow-soft)",
};

export { getVariantOptionKeys, getVisibleVariantOptionKeys } from "../../../lib/storefront/variantSelection";

export type { OptionKey } from "../../../lib/storefront/variantSelection";

export function getVariantValues(
  variants: NonNullable<ProductDetailData["variants"]>,
  key: OptionKey,
  orderedValues?: string[] | null,
) {
  const fromVariants = (): string[] => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const v of variants) {
      const val = fmtOpt(v[key]);
      if (!val || seen.has(val)) continue;
      seen.add(val);
      out.push(val);
    }
    return out;
  };
  const base = fromVariants();
  if (!orderedValues?.length) return base;
  const allowed = new Set(base);
  const ordered = orderedValues.filter((value) => allowed.has(value));
  if (!ordered.length) return base;
  const seen = new Set(ordered);
  for (const value of base) {
    if (!seen.has(value)) ordered.push(value);
  }
  return ordered;
}

type ProductGallerySlide = {
  key: string;
  url: string;
  alt: string;
  fallbackUrl: string | null;
};

function productGallerySlideKey(image: {
  id: number;
  url: string;
  position: number;
}): string {
  return `${image.position}:${image.url.trim()}`;
}

function buildProductGallery(product: ProductDetailData): ProductGallerySlide[] {
  const imgs = Array.isArray(product.images)
    ? [...product.images].sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    : [];
  const fallback = product.image_url ?? null;
  if (imgs.length) {
    return imgs.map((i) => ({
      key: productGallerySlideKey(i),
      url: i.url,
      alt: i.alt ?? product.title,
      fallbackUrl: i.fallback_url ?? null,
    }));
  }
  if (fallback) {
    return [
      {
        key: `cover:${fallback.trim()}`,
        url: fallback,
        alt: product.title,
        fallbackUrl: null,
      },
    ];
  }
  return [];
}

type Props = {
  product: ProductDetailData;
  cartQty: number;
  cartBusy: boolean;
  cartActionError?: string | null;
  cartLineVariantId?: number | null;
  onAddToCart: (variantId?: number | null) => Promise<void>;
  onChangeQty: (nextQty: number, variantId?: number | null) => Promise<void>;
  onSelectedVariantChange?: (variantId: number | null) => void;
  syncVariantId?: number | null;
  variantConstraintPreset?: VariantConstraintPreset;
};

export function ProductDetail({
  product,
  cartQty,
  cartBusy,
  cartActionError = null,
  cartLineVariantId = null,
  onAddToCart,
  onChangeQty,
  onSelectedVariantChange,
  syncVariantId = null,
  variantConstraintPreset = [],
}: Props) {
  const navigate = useNavigate();

  // Shared Mini App / mobile `main`: catalog unmount no longer zeros scroll on PDP entry.
  useLayoutEffect(() => {
    const root = getCatalogScrollRoot(document.querySelector("main"));
    if (root === window) return;
    writeCatalogScrollTop(root, 0);
  }, []);
  const location = useLocation();
  const compact = useStorefrontCompact();
  const bottomNav = useStorefrontBottomNav();
  const pagePad = useStorefrontCompactPagePad();
  const [stockDisplay, setStockDisplay] = useState<StockDisplayConfig>(DEFAULT_STOCK_DISPLAY);
  const [variantSelection, setVariantSelection] = useState<Partial<Record<OptionKey, string>>>({});
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const [loadedThumbKeys, setLoadedThumbKeys] = useState<Set<string>>(() => new Set());
  const [loadedHeroKey, setLoadedHeroKey] = useState<string | null>(null);
  const [exhaustedGalleryKeys, setExhaustedGalleryKeys] = useState<Set<string>>(() => new Set());
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [imageLightboxOpen, setImageLightboxOpen] = useState(false);
  const [variantHoverQty, setVariantHoverQty] = useState<number | null>(null);
  useEffect(() => {
    void fetchStockDisplayConfig().then(setStockDisplay);
  }, []);

  useEffect(() => {
    const vars = Array.isArray(product.variants) ? product.variants : [];
    if (variantConstraintPreset.length > 0) {
      const resolved = resolveVariantSelectionFromConstraints(product, variantConstraintPreset);
      setVariantSelection(resolved ?? firstInStockSelection(vars));
    } else {
      setVariantSelection(firstInStockSelection(vars));
    }
    setSelectedImageIndex(0);
    setLoadedThumbKeys(new Set());
    setLoadedHeroKey(null);
    setExhaustedGalleryKeys(new Set());
    setDescriptionExpanded(false);
    setVariantHoverQty(null);
  }, [product.id, product.variants, variantConstraintPreset]);

  useEffect(() => {
    if (syncVariantId == null) return;
    const vars = Array.isArray(product.variants) ? product.variants : [];
    const match = vars.find((v) => Number(v.id) === Number(syncVariantId));
    if (!match) return;
    setVariantSelection(selectionFromVariant(match));
  }, [syncVariantId, product.variants]);

  useEffect(() => {
    setVariantHoverQty(null);
  }, [variantSelection]);

  const galleryCandidates = useMemo(() => buildProductGallery(product), [product]);
  const productImagePlaceholder = PRODUCT_PLACEHOLDER;
  const availableGallery = useMemo(
    () => galleryCandidates.filter((slide) => !exhaustedGalleryKeys.has(slide.key)),
    [galleryCandidates, exhaustedGalleryKeys],
  );
  const showGalleryEmptyState = availableGallery.length === 0;

  const markGallerySlideExhausted = useCallback(
    (slideKey: string) => {
      setExhaustedGalleryKeys((prev) => {
        if (prev.has(slideKey)) return prev;
        const availableBefore = galleryCandidates.filter((slide) => !prev.has(slide.key));
        const removedIndex = availableBefore.findIndex((slide) => slide.key === slideKey);
        if (removedIndex < 0) return prev;
        const nextExhausted = new Set(prev);
        nextExhausted.add(slideKey);
        setSelectedImageIndex((current) =>
          adjustGalleryActiveIndex(current, removedIndex, availableBefore.length - 1),
        );
        return nextExhausted;
      });
    },
    [galleryCandidates],
  );

  const displayCategoryLabelRu =
    product.category_l3_label_ru?.trim() || product.category_l2_label_ru?.trim() || "";
  const galleryIndex = Math.max(
    0,
    Math.min(selectedImageIndex, Math.max(0, availableGallery.length - 1)),
  );
  const galleryActive = availableGallery[galleryIndex] ?? null;
  const heroImageUrl =
    !showGalleryEmptyState && galleryActive
      ? resolveProductImageUrl(
          { image_url: galleryActive.url, image_urls: product.image_urls },
          "pdp_hero",
        ) ?? galleryActive.url
      : null;
  const heroFallbackUrl = galleryActive?.fallbackUrl
    ? resolveProductImageUrl(galleryActive.fallbackUrl, "pdp_hero")
    : null;

  const heroVisible = galleryActive != null && loadedHeroKey === galleryActive.key;
  const thumbRowVisible = availableGallery.some((slide) => loadedThumbKeys.has(slide.key));

  const heroSrcIsCurrent = useCallback(
    (img: HTMLImageElement) => {
      const shown = img.currentSrc || img.getAttribute("src") || "";
      return [heroImageUrl, heroFallbackUrl].some((expected) => {
        if (!expected || !shown) return false;
        if (shown === expected) return true;
        try {
          return new URL(shown, window.location.href).href === new URL(expected, window.location.href).href;
        } catch {
          return false;
        }
      });
    },
    [heroImageUrl, heroFallbackUrl],
  );

  const markHeroLoaded = useCallback(
    (slideKey: string) => {
      setLoadedHeroKey((current) => (current === slideKey ? current : slideKey));
    },
    [],
  );

  const syncCachedHeroImage = useCallback(() => {
    if (!heroImageUrl || !galleryActive) return;
    const img = document.querySelector<HTMLImageElement>(
      '[data-pdp-hero="image"][data-pdp-gallery-key]',
    );
    if (!img || img.getAttribute("data-pdp-gallery-key") !== galleryActive.key) return;
    if (!img.complete || img.naturalWidth <= 0 || !heroSrcIsCurrent(img)) return;
    setLoadedHeroKey((current) => (current === galleryActive.key ? current : galleryActive.key));
  }, [heroImageUrl, galleryActive, heroSrcIsCurrent]);

  useLayoutEffect(() => {
    syncCachedHeroImage();
  }, [syncCachedHeroImage]);

  useEffect(() => {
    syncCachedHeroImage();
  }, [syncCachedHeroImage]);

  const markThumbLoaded = useCallback((slideKey: string) => {
    setLoadedThumbKeys((prev) => {
      if (prev.has(slideKey)) return prev;
      const next = new Set(prev);
      next.add(slideKey);
      return next;
    });
  }, []);

  // Cached thumbs can be complete before onLoad is attached. One check after commit, not a poll.
  const syncCachedThumbImages = useCallback(() => {
    const nodes = document.querySelectorAll<HTMLImageElement>("[data-pdp-thumb-image]");
    setLoadedThumbKeys((prev) => {
      let changed = false;
      const next = new Set(prev);
      nodes.forEach((img) => {
        const key = img.getAttribute("data-pdp-gallery-key");
        if (!key || next.has(key) || !img.complete || img.naturalWidth <= 0) return;
        next.add(key);
        changed = true;
      });
      return changed ? next : prev;
    });
  }, []);

  useLayoutEffect(() => {
    syncCachedThumbImages();
  }, [syncCachedThumbImages, availableGallery]);

  useEffect(() => {
    syncCachedThumbImages();
  }, [syncCachedThumbImages, availableGallery]);

  useEffect(() => {
    if (!imageLightboxOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setImageLightboxOpen(false);
        return;
      }
      if (availableGallery.length <= 1) return;
      if (e.key === "ArrowLeft") {
        setSelectedImageIndex((v) => (v - 1 + availableGallery.length) % availableGallery.length);
      }
      if (e.key === "ArrowRight") {
        setSelectedImageIndex((v) => (v + 1) % availableGallery.length);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [imageLightboxOpen, availableGallery.length]);

  const selectedVariant = useMemo(() => {
    const vars = product.variants;
    if (!Array.isArray(vars) || !vars.length) return null;
    return findMatchingVariant(vars, variantSelection);
  }, [product.variants, variantSelection]);

  const selectedVariantId = selectedVariant?.id ?? null;

  const displayCartQty =
    cartQty > 0 &&
    (!Array.isArray(product.variants) ||
      !product.variants.length ||
      (cartLineVariantId != null &&
        selectedVariantId != null &&
        Number(cartLineVariantId) === Number(selectedVariantId)))
      ? cartQty
      : 0;

  const selectedVariantStockQty = useMemo(() => {
    if (!selectedVariant || !isVariantInStock(selectedVariant)) return 0;
    return resolveVariantBuyableQty(selectedVariant);
  }, [selectedVariant]);

  const stockQty = compact || variantHoverQty === null ? selectedVariantStockQty : variantHoverQty;
  const stockParts = useMemo(() => {
    const parts = buyerStockBadgeParts(stockQty, stockDisplay);
    const status = selectedVariant?.stock_status ?? product.stock_status;
    if (status === undefined) return parts;
    return {
      text: parts.text,
      extraClass: stockStatusExtraClass(status),
    };
  }, [stockQty, stockDisplay, selectedVariant?.stock_status, product.stock_status]);
  const variantOptionKeys = useMemo(
    () => getVariantOptionKeys(product.variants),
    [product.variants],
  );
  const visibleVariantOptionKeys = useMemo(
    () => getVisibleVariantOptionKeys(product),
    [product],
  );
  const shippingLabel =
    String(product.shipping_estimate || "").trim() || stockDisplay.shippingEstimateFallback;
  const displayTitle = useMemo(() => {
    if (selectedVariantId != null) {
      const fromApi = product.variant_display_titles?.[String(selectedVariantId)];
      if (fromApi) return fromApi;
    }
    return product.display_title || product.title;
  }, [product.display_title, product.title, product.variant_display_titles, selectedVariantId]);

  const optionValueLabel = useCallback(
    (key: OptionKey, raw: string) =>
      product.variant_option_values_ru?.[key]?.[raw] ?? raw,
    [product.variant_option_values_ru],
  );

  const optionGroupLabel = useCallback(
    (key: OptionKey) => product.variant_option_labels?.[key] ?? key,
    [product.variant_option_labels],
  );

  const selectVariantOption = useCallback((key: OptionKey, val: string) => {
    setVariantHoverQty(null);
    setVariantSelection((s) => ({ ...s, [key]: val }));
  }, []);

  const scrollVariantChipAboveSticky = useCallback((chip: HTMLElement) => {
    if (!compact) return;
    const scrollRoot = chip.closest("main");
    const stickyBar = document.querySelector<HTMLElement>(".product-pdp-sticky-bar");
    if (!scrollRoot || !stickyBar) return;
    const overlap =
      chip.getBoundingClientRect().bottom - stickyBar.getBoundingClientRect().top + 4;
    if (overlap > 0) scrollRoot.scrollTop += overlap;
  }, [compact]);

  const previewVariantStock = useCallback(
    (key: OptionKey, val: string) => {
      if (compact || !product.variants?.length) return;
      const qty = variantQtyForChipHover(
        product.variants,
        variantOptionKeys,
        variantSelection,
        key,
        val,
      );
      setVariantHoverQty(qty);
    },
    [compact, product.variants, variantOptionKeys, variantSelection],
  );

  const goBack = useCallback(() => {
    const from = (location.state as { from?: string } | null)?.from;
    if (shouldPopProductBack(from) || window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate(catalogAllPath());
  }, [location.state, navigate]);

  const changeSelectedQty = useCallback(
    async (nextQty: number) => {
      await onChangeQty(nextQty, selectedVariantId);
    },
    [onChangeQty, selectedVariantId],
  );

  useEffect(() => {
    onSelectedVariantChange?.(selectedVariantId);
  }, [onSelectedVariantChange, selectedVariantId]);

  return (
    <div
      className={
        compact
          ? "bg-sp-bg text-sp-text-primary"
          : "bg-sp-bg text-sp-text-primary pb-16"
      }
      style={
        compact
          ? { paddingBottom: bottomNav ? PDP_MINIAPP_SCROLL_PAD : PDP_COMPACT_SCROLL_PAD }
          : undefined
      }
    >
      {imageLightboxOpen && galleryActive ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Увеличенное фото"
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 md:p-6"
          style={{ backgroundColor: "rgba(0,0,0,0.92)" }}
          onClick={() => setImageLightboxOpen(false)}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute top-4 right-4 z-[62] flex h-11 w-11 items-center justify-center rounded-full border border-white/80 bg-white text-sp-text-primary shadow-md hover:bg-white/90 sp-transition"
            onClick={(e) => {
              e.stopPropagation();
              setImageLightboxOpen(false);
            }}
          >
            <X size={22} />
          </button>

          {availableGallery.length > 1 ? (
            <>
              <button
                type="button"
                aria-label="Предыдущее фото"
                className="absolute left-3 md:left-6 top-1/2 z-[62] -translate-y-1/2 flex h-11 w-11 items-center justify-center rounded-full border border-white/80 bg-white text-sp-text-primary text-xl shadow-md hover:bg-white/90 sp-transition"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedImageIndex((v) => (v - 1 + availableGallery.length) % availableGallery.length);
                }}
              >
                ‹
              </button>
              <button
                type="button"
                aria-label="Следующее фото"
                className="absolute right-3 md:right-6 top-1/2 z-[62] -translate-y-1/2 flex h-11 w-11 items-center justify-center rounded-full border border-white/80 bg-white text-sp-text-primary text-xl shadow-md hover:bg-white/90 sp-transition"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedImageIndex((v) => (v + 1) % availableGallery.length);
                }}
              >
                ›
              </button>
              <div className="absolute bottom-5 left-1/2 z-[62] -translate-x-1/2 rounded-full bg-white px-3 py-1 text-[13px] font-medium text-sp-text-primary shadow-md">
                {galleryIndex + 1} / {availableGallery.length}
              </div>
            </>
          ) : null}

          <ImageWithFallback
            src={resolveProductImageUrl(
              { image_url: galleryActive.url, image_urls: product.image_urls },
              "pdp_hero",
            ) ?? galleryActive.url}
            fallbackSrc={
              galleryActive.fallbackUrl
                ? resolveProductImageUrl(galleryActive.fallbackUrl, "pdp_hero")
                : null
            }
            alt={galleryActive.alt}
            data-pdp-gallery-key={galleryActive.key}
            onExhausted={() => markGallerySlideExhausted(galleryActive.key)}
            className={
              compact
                ? "max-w-[96vw] max-h-[88vh] object-contain select-none"
                : "h-auto w-[min(92vw,900px)] max-h-[92dvh] max-w-[min(92vw,900px)] object-contain select-none"
            }
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}

      <div className={pdpHeroPageClassName(compact, pagePad)}>
        <button
          type="button"
          onClick={goBack}
          className={
            compact
              ? "mb-2 inline-flex items-center gap-1.5 border-0 bg-transparent p-0 text-[12px] font-medium text-sp-blue sp-transition hover:opacity-80"
              : "mb-4 inline-flex cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-sp-blue sp-transition hover:text-[#1a7fe0]"
          }
        >
          <ArrowLeft className={compact ? "size-3.5" : "h-4 w-4"} />
          <span className={compact ? "" : "text-[15px] font-medium"}>Назад</span>
        </button>

        <div
          className={
            pdpHeroGridClassName(compact)
          }
        >
          <div className={`product-pdp-col ${compact ? "space-y-2" : "space-y-4 lg:sticky lg:top-24 lg:self-start"}`}>
            <div
              data-pdp-hero="frame"
              className={pdpHeroFrameClassName(compact)}
            >
              {!showGalleryEmptyState && heroImageUrl ? (
                <>
                  {heroVisible ? null : (
                    <Skeleton className="absolute inset-0 z-[1] size-full" />
                  )}
                  <ImageWithFallback
                    data-pdp-hero="image"
                    src={heroImageUrl}
                    fallbackSrc={heroFallbackUrl}
                    alt={galleryActive?.alt ?? product.title}
                    loading="eager"
                    fetchPriority="high"
                    decoding="async"
                    className={`absolute inset-0 h-full w-full cursor-zoom-in object-cover object-center${heroVisible ? "" : " opacity-0"}`}
                    data-pdp-gallery-key={galleryActive.key}
                    onExhausted={() => markGallerySlideExhausted(galleryActive.key)}
                    onLoad={(event) => {
                      const img = event.currentTarget;
                      if (!(img instanceof HTMLImageElement)) return;
                      if (img.getAttribute("data-pdp-gallery-key") !== galleryActive.key) return;
                      if (!heroSrcIsCurrent(img)) return;
                      markHeroLoaded(galleryActive.key);
                    }}
                    onClick={() => setImageLightboxOpen(true)}
                  />
                  {availableGallery.length > 1 ? (
                    <>
                      <button
                        type="button"
                        aria-label="Предыдущее фото"
                        onClick={() =>
                          setSelectedImageIndex((v) => (v - 1 + availableGallery.length) % availableGallery.length)
                        }
                        style={{
                          ...galleryNavBtnStyle,
                          left: 12,
                          width: compact ? 34 : 40,
                          height: compact ? 34 : 40,
                          fontSize: compact ? "1.1rem" : "1.25rem",
                        }}
                      >
                        ‹
                      </button>
                      <button
                        type="button"
                        aria-label="Следующее фото"
                        onClick={() => setSelectedImageIndex((v) => (v + 1) % availableGallery.length)}
                        style={{
                          ...galleryNavBtnStyle,
                          right: 12,
                          width: compact ? 34 : 40,
                          height: compact ? 34 : 40,
                          fontSize: compact ? "1.1rem" : "1.25rem",
                        }}
                      >
                        ›
                      </button>
                    </>
                  ) : null}
                </>
              ) : (
                <img
                  src={productImagePlaceholder}
                  alt={product.title}
                  data-pdp-hero="image"
                  data-pdp-placeholder="true"
                  className="absolute inset-0 h-full w-full object-cover object-center"
                />
              )}
            </div>

            {availableGallery.length > 1 ? (
              <div
                data-pdp-thumb-row="true"
                aria-hidden={!thumbRowVisible}
                className={`${thumbRowVisible ? "visible" : "invisible"} ${
                  compact
                    ? "flex gap-2 overflow-x-auto px-0.5 pb-0.5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                    : "flex flex-wrap gap-3"
                }`}
              >
                {availableGallery.map((g, i) => {
                  const thumbVisible = loadedThumbKeys.has(g.key);
                  return (
                    <button
                      key={g.key}
                      data-pdp-thumb="true"
                      type="button"
                      onClick={() => setSelectedImageIndex(i)}
                      className={`relative cursor-pointer overflow-hidden sp-transition hover:opacity-70 aspect-square ${compact ? "size-14 shrink-0" : "h-[72px] w-[72px] shrink-0"}`}
                      style={{
                        borderRadius: compact ? "10px" : "12px",
                        border:
                          i === galleryIndex
                            ? "2px solid var(--sp-blue)"
                            : "1px solid var(--sp-border)",
                      }}
                    >
                      {thumbVisible ? null : (
                        <Skeleton className="absolute inset-0 size-full rounded-[inherit]" />
                      )}
                      <ImageWithFallback
                        src={resolveProductImageUrl(g.url, "pdp_gallery_thumb") ?? g.url}
                        fallbackSrc={
                          g.fallbackUrl
                            ? resolveProductImageUrl(g.fallbackUrl, "pdp_gallery_thumb")
                            : null
                        }
                        alt={g.alt}
                        data-pdp-gallery-key={g.key}
                        data-pdp-thumb-image="true"
                        loading={i === galleryIndex ? "eager" : "lazy"}
                        decoding="async"
                        className={`h-full w-full object-cover object-center${thumbVisible ? "" : " opacity-0"}`}
                        onExhausted={() => markGallerySlideExhausted(g.key)}
                        onLoad={() => markThumbLoaded(g.key)}
                      />
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          <div className="product-pdp-col flex flex-col">
            <div className={`inline-flex flex-wrap items-center gap-1.5 ${compact ? "mb-2" : "mb-3"}`}>
              <span
                className={sportBadgePillClass(resolveSportCategory(product), compact)}
              >
                {product.sport_type_label_ru || "Товар"}
              </span>
              {displayCategoryLabelRu ? (
                <>
                  <span className={`text-sp-text-muted ${compact ? "text-[11px]" : "text-[13px]"}`}>·</span>
                  <span className={`text-sp-text-secondary ${compact ? "text-[11px]" : "text-[13px]"}`}>
                    {displayCategoryLabelRu}
                  </span>
                </>
              ) : null}
            </div>

            {product.brand ? (
              <div
                className={`font-semibold uppercase tracking-[0.1em] text-sp-text-muted ${compact ? "mb-1 text-[10px]" : "mb-2 text-[11px]"}`}
              >
                {product.brand}
              </div>
            ) : null}

            <h1
              className={`product-pdp-title font-semibold ${compact ? "mb-2 text-[20px] leading-snug" : "mb-4 text-[28px] leading-tight md:text-[36px]"}`}
            >
              {displayTitle}
            </h1>

            <div
              className={`font-semibold text-sp-text-primary ${compact ? "mb-3 text-[22px]" : "mb-5 text-[28px]"}`}
            >
              {moneyRub(product.sale_price)}
            </div>

            {product.description ? (
              <div className={compact ? "mb-4" : "mb-6"}>
                <p
                  className={`m-0 text-sp-text-secondary leading-relaxed ${compact ? "text-[14px] leading-snug" : "text-[16px]"} ${
                    descriptionExpanded ? "" : compact ? "line-clamp-3" : "line-clamp-4"
                  }`}
                >
                  {product.description}
                </p>
                {product.description.length > (compact ? 120 : 180) ? (
                  <button
                    type="button"
                    onClick={() => setDescriptionExpanded((v) => !v)}
                    className={`mt-2 cursor-pointer border-0 bg-transparent p-0 text-sp-blue hover:underline ${compact ? "text-[13px]" : "text-[14px]"}`}
                  >
                    {descriptionExpanded ? "Свернуть" : "Читать полностью"}
                  </button>
                ) : null}
              </div>
            ) : null}

            {Array.isArray(product.variants) && product.variants.length ? (
              <div className={compact ? "mb-3" : "mb-4"} onMouseLeave={compact ? undefined : () => setVariantHoverQty(null)}>
                {visibleVariantOptionKeys.map((key, i) => {
                  const values = getVariantValues(
                    product.variants!,
                    key,
                    product.variant_option_values?.[key],
                  ).filter((val) =>
                    isValueAvailable(product.variants!, variantSelection, key, val),
                  );
                  if (!values.length) return null;
                  return (
                    <div key={key} className={i === 0 ? (compact ? "mb-2" : "mb-3") : compact ? "mb-2" : "mb-2"}>
                      <div
                        className={`flex flex-wrap items-baseline gap-x-2 gap-y-1 ${compact ? "mb-1.5" : "mb-2"}`}
                      >
                        <label
                          className={`font-semibold text-sp-text-primary ${compact ? "text-[12px]" : "text-[13px]"}`}
                        >
                          {optionGroupLabel(key)}
                        </label>
                        {key === "option2" && product.show_shoe_size_guide && product.brand ? (
                          <button
                            type="button"
                            onClick={() => openShoeSizeGuide(product.brand)}
                            className={`cursor-pointer border-0 bg-transparent p-0 font-normal text-sp-blue hover:underline ${compact ? "text-[11px]" : "text-[13px]"}`}
                          >
                            Таблица размеров {product.brand}
                          </button>
                        ) : null}
                      </div>
                      <div className={`flex flex-wrap ${compact ? "gap-1.5" : "gap-2"}`}>
                        {values.map((val) => {
                          const active = variantSelection[key] === val;
                          const ok = isValueAvailable(product.variants!, variantSelection, key, val);
                          return (
                            <button
                              key={val}
                              type="button"
                              disabled={!ok}
                              onMouseEnter={compact ? undefined : () => previewVariantStock(key, val)}
                              onClick={(e) => {
                                scrollVariantChipAboveSticky(e.currentTarget);
                                selectVariantOption(key, val);
                              }}
                              className={
                                compact
                                  ? `${miniAppPillClass(active && ok)} ${!ok ? "cursor-not-allowed opacity-60" : ""}`
                                  : `${active && ok ? miniAppPillClass(true) : miniAppPillClass(false)} px-5 py-2 text-[14px] ${
                                      !ok ? "cursor-not-allowed opacity-60" : ""
                                    }`
                              }
                            >
                              {optionValueLabel(key, val)}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}


                {compact ? (
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <div className="variant-buyer-stock variant-buyer-stock--compact !mt-0 min-h-0">
                      {stockParts.extraClass === "out-of-stock" ? (
                        <span className="stock-status-out">{stockParts.text}</span>
                      ) : (
                        <span className={`stock-badge ${stockParts.extraClass}`.trim()}>
                          {stockParts.text}
                        </span>
                      )}
                    </div>
                    <div className="product-shipping-inline !mt-0 gap-1 text-[11px] text-sp-text-secondary">
                      <Truck size={13} strokeWidth={1.75} aria-hidden />
                      <span>{shippingLabel}</span>
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1">
                    <div className="variant-buyer-stock !mt-0 min-h-0">
                      {stockParts.extraClass === "out-of-stock" ? (
                        <span className="stock-status-out">{stockParts.text}</span>
                      ) : (
                        <span className={`stock-badge ${stockParts.extraClass}`.trim()}>
                          {stockParts.text}
                        </span>
                      )}
                    </div>
                    <div className="product-shipping-inline !mt-0">
                      <Truck size={16} strokeWidth={1.75} aria-hidden />
                      <span>{shippingLabel}</span>
                    </div>
                  </div>
                )}
              </div>
            ) : null}

            {!Array.isArray(product.variants) || !product.variants.length ? (
              <div className={`product-shipping-inline ${compact ? "!mt-0 text-[11px]" : ""}`}>
                <Truck size={compact ? 13 : 16} strokeWidth={1.75} aria-hidden />
                <span>{shippingLabel}</span>
              </div>
            ) : null}

            {!compact ? (
            <div
              className="hidden lg:block mt-4 py-4"
              style={{
                borderTop: "1px solid var(--sp-border)",
                borderBottom: "1px solid var(--sp-border)",
              }}
            >
              <div className="flex h-[37px] items-center justify-start">
                {displayCartQty > 0 ? (
                  <>
                    <div
                      className={`${miniAppPillClass(true)} inline-flex h-[37px] w-[134px] shrink-0 items-center justify-between gap-1 px-3 py-2 text-[14px]`}
                    >
                      <button
                        type="button"
                        onClick={() => void changeSelectedQty(Math.max(0, displayCartQty - 1))}
                        disabled={cartBusy}
                        className="flex h-5 w-5 shrink-0 items-center justify-center disabled:opacity-60 hover:opacity-80 sp-transition"
                      >
                        −
                      </button>
                      <span className="min-w-0 flex-1 truncate text-center font-medium">
                        {displayCartQty} шт
                      </span>
                      <button
                        type="button"
                        onClick={() => void changeSelectedQty(displayCartQty + 1)}
                        disabled={cartBusy}
                        className="flex h-5 w-5 shrink-0 items-center justify-center disabled:opacity-60 hover:opacity-80 sp-transition"
                      >
                        +
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => void changeSelectedQty(0)}
                      disabled={cartBusy}
                      aria-label="Удалить из корзины"
                      className="ml-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-sp-border bg-sp-surface text-sp-text-muted sp-transition hover:border-red-200 hover:text-red-500 disabled:opacity-60"
                    >
                      <Trash2 size={15} strokeWidth={1.75} aria-hidden />
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => void onAddToCart(selectedVariantId)}
                    disabled={cartBusy || stockParts.extraClass === "out-of-stock"}
                    className={`${miniAppPillClass(true)} inline-flex h-[37px] w-[134px] shrink-0 items-center justify-center gap-2 px-5 py-2 text-[14px] disabled:opacity-60 hover:opacity-90`}
                  >
                    <ShoppingBag size={16} />
                    В корзину
                  </button>
                )}
              </div>
              {cartActionError ? (
                <p className="m-0 mt-2 text-[13px] text-red-500" role="alert">
                  {cartActionError}
                </p>
              ) : null}
            </div>
            ) : null}

            {Array.isArray(product.features) && product.features.length ? (
              <div
                className={`${compact ? "mt-3 border-t border-sp-border py-2" : "mb-2 mt-4 border-t border-sp-border py-3 lg:mt-0 lg:border-t-0"}`}
              >
                <div className={`product-pdp-features ${compact ? "gap-1" : ""}`}>
                  {[...product.features]
                    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                    .map((f) => (
                      <div key={f.id} className="flex min-w-0 items-start gap-2">
                        <div
                          className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full"
                          style={{ background: "rgba(41, 151, 255, 0.1)" }}
                        >
                          <Check size={11} className="text-sp-blue" />
                        </div>
                        <div
                          className={`min-w-0 leading-snug text-sp-text-primary ${compact ? "text-[13px]" : "text-[14px]"}`}
                        >
                          {f.name_ru || f.name}
                          {f.value ? (
                            <span className="text-sp-text-secondary">
                              {" "}
                              — {f.value_ru ?? f.value}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className={
          compact
            ? "product-pdp-sticky-bar fixed inset-x-0 bottom-0 z-[55] border-t border-sp-border bg-sp-surface/95 p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom,0px))] backdrop-blur-md"
            : "product-pdp-sticky-bar glass-navbar fixed inset-x-0 bottom-0 z-[55] border-t border-sp-border p-4 lg:hidden"
        }
        style={compact && bottomNav ? { bottom: MINIAPP_BOTTOM_NAV_OFFSET } : undefined}
      >
        <div className={`flex items-center gap-3 ${compact ? "" : "mx-auto max-w-[1200px] justify-between"}`}>
          <div className="min-w-0 flex-1">
            {compact ? (
              <div className="truncate text-[13px] font-medium text-sp-text-primary">{displayTitle}</div>
            ) : product.brand ? (
              <div className="text-[13px] text-sp-text-secondary">{product.brand}</div>
            ) : null}
            <div className={compact ? "text-[16px] font-semibold" : "text-[17px] font-semibold"}>
              {moneyRub(product.sale_price)}
            </div>
          </div>
          {displayCartQty > 0 ? (
            compact ? (
              <div className="inline-flex shrink-0 items-center justify-center gap-2 rounded-full border border-sp-border px-2 py-1">
                <button
                  type="button"
                  onClick={() => void changeSelectedQty(Math.max(0, displayCartQty - 1))}
                  disabled={cartBusy}
                  className="h-7 w-7 text-[14px] text-sp-text-primary sp-transition hover:text-sp-blue disabled:opacity-60"
                >
                  −
                </button>
                <span className="min-w-[3rem] text-center text-[12px] font-medium text-sp-text-primary">
                  {displayCartQty} шт
                </span>
                <button
                  type="button"
                  onClick={() => void changeSelectedQty(displayCartQty + 1)}
                  disabled={cartBusy || stockParts.extraClass === "out-of-stock"}
                  className="h-7 w-7 text-[14px] text-sp-text-primary sp-transition hover:text-sp-blue disabled:opacity-60"
                >
                  +
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => void changeSelectedQty(displayCartQty + 1)}
                disabled={cartBusy}
                className="shrink-0 rounded-full bg-sp-blue px-8 py-3 text-[15px] font-semibold text-white disabled:opacity-60"
              >
                В корзине: {displayCartQty}
              </button>
            )
          ) : (
            <button
              type="button"
              onClick={() => void onAddToCart(selectedVariantId)}
              disabled={cartBusy || stockParts.extraClass === "out-of-stock"}
              className={`shrink-0 disabled:opacity-60 ${compact ? miniAppPillClass(true) : "rounded-full bg-sp-blue px-8 py-3 text-[15px] font-semibold text-white"}`}
            >
              В корзину
            </button>
          )}
        </div>
        {cartActionError ? (
          <p
            className={`m-0 mt-2 text-red-500 ${compact ? "text-[12px]" : "text-[13px]"}`}
            role="alert"
          >
            {cartActionError}
          </p>
        ) : null}
      </div>
    </div>
  );
}
