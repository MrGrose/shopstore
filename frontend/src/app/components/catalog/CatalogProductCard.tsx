import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type TouchEvent } from "react";
import { motion } from "motion/react";

import type { CartLine } from "../../../lib/storefront/cart";
import { moneyRub } from "../../../lib/storefront/checkoutUi";
import { prefetchProductPageChunk } from "../../../lib/storefront/prefetchProductPage";
import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";
import { PRODUCT_PLACEHOLDER } from "../../../lib/storefront/productPlaceholder";
import { sportBadgeCardClass, resolveSportCategory } from "../../../lib/storefront/sportBadge";
import { ImageWithFallback } from "../figma/ImageWithFallback";
import { adjustGalleryActiveIndex } from "../../../lib/storefront/galleryActiveIndex";
import {
  type CatalogProductCardData,
  resolveCatalogCardGalleryCandidates,
} from "./catalogProductTypes";

const SWIPE_THRESHOLD_PX = 40;

export type CatalogProductCardProps = {
  product: CatalogProductCardData;
  animationIndex: number;
  cartLine: CartLine | null;
  cartBusy: boolean;
  onOpen: (id: number, previewImageUrl?: string | null) => void;
  onAddToCart: (product: CatalogProductCardData) => Promise<void>;
  onChangeCartQty: (
    product: CatalogProductCardData,
    nextQty: number,
    variantId?: number | null,
  ) => void;
  compact?: boolean;
  imagePriority?: boolean;
  /** POP remount after PDP: skip opacity enter animation. */
  skipEnterAnimation?: boolean;
};

export function CatalogProductCard({
  product,
  animationIndex,
  cartLine,
  cartBusy,
  onOpen,
  onAddToCart,
  onChangeCartQty,
  compact = false,
  imagePriority = false,
  skipEnterAnimation = false,
}: CatalogProductCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [adding, setAdding] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [exhaustedSlideKeys, setExhaustedSlideKeys] = useState<Set<string>>(() => new Set());
  const suppressOpenRef = useRef(false);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);

  const galleryCandidates = useMemo(
    () => resolveCatalogCardGalleryCandidates(product, compact),
    [product, compact],
  );
  const placeholderSrc = PRODUCT_PLACEHOLDER;
  const availableSlides = useMemo(
    () => galleryCandidates.filter((slide) => !exhaustedSlideKeys.has(slide.key)),
    [galleryCandidates, exhaustedSlideKeys],
  );
  const slideCount = availableSlides.length;
  const safeActiveIndex =
    slideCount === 0 ? 0 : Math.min(activeIndex, Math.max(0, slideCount - 1));
  const activeUrl = availableSlides[safeActiveIndex]?.url ?? null;
  const showPlaceholder = slideCount === 0;
  const showGalleryControls = slideCount >= 2;

  const buyableQty = product.buyable_qty ?? product.available_stock;
  const inStock =
    product.stock_status !== undefined
      ? product.stock_status !== "out_of_stock"
      : buyableQty === undefined || buyableQty > 0;
  const cartQty = cartLine ? Number(cartLine.quantity ?? 0) : 0;
  const inCart = cartQty > 0;
  const showCartControl = compact || inCart || isHovered;

  useEffect(() => {
    setActiveIndex(0);
    setExhaustedSlideKeys(new Set());
  }, [product.id]);

  const markSlideExhausted = useCallback(
    (slideKey: string) => {
      setExhaustedSlideKeys((prev) => {
        if (prev.has(slideKey)) return prev;
        const availableBefore = galleryCandidates.filter((slide) => !prev.has(slide.key));
        const removedIndex = availableBefore.findIndex((slide) => slide.key === slideKey);
        if (removedIndex < 0) return prev;
        const nextExhausted = new Set(prev);
        nextExhausted.add(slideKey);
        const nextSlideCount = availableBefore.length - 1;
        setActiveIndex((current) =>
          adjustGalleryActiveIndex(current, removedIndex, nextSlideCount),
        );
        return nextExhausted;
      });
    },
    [galleryCandidates],
  );

  const openProduct = () => {
    if (suppressOpenRef.current) {
      suppressOpenRef.current = false;
      return;
    }
    onOpen(product.id, showPlaceholder ? null : activeUrl);
  };

  const handleCart = async (e: MouseEvent) => {
    e.stopPropagation();
    if (adding || !inStock) return;
    setAdding(true);
    try {
      await onAddToCart(product);
    } finally {
      setAdding(false);
    }
  };

  const handleGalleryClick = (event: MouseEvent) => {
    event.stopPropagation();
  };

  const goToSlide = (nextIndex: number) => {
    if (slideCount === 0) return;
    setActiveIndex(Math.max(0, Math.min(slideCount - 1, nextIndex)));
  };

  const handleTouchStart = (event: TouchEvent) => {
    if (slideCount < 2) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    touchStartRef.current = { x: touch.clientX, y: touch.clientY };
  };

  const handleTouchEnd = (event: TouchEvent) => {
    if (slideCount < 2 || !touchStartRef.current) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - touchStartRef.current.x;
    const dy = touch.clientY - touchStartRef.current.y;
    touchStartRef.current = null;
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) < Math.abs(dy)) return;
    event.preventDefault();
    event.stopPropagation();
    suppressOpenRef.current = true;
    const delta = dx < 0 ? 1 : -1;
    setActiveIndex((value) => (value + delta + slideCount) % slideCount);
  };

  return (
    <motion.div
      initial={skipEnterAnimation ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -3 }}
      transition={{
        duration: compact ? 0.18 : 0.24,
        delay: compact ? 0 : Math.min(animationIndex * 0.012, 0.1),
      }}
      className="group flex flex-col sp-transition cursor-pointer overflow-hidden"
      data-catalog-product-id={product.id}
      data-catalog-enter={skipEnterAnimation ? "skip" : "play"}
      style={{
        background: "var(--sp-surface)",
        borderRadius: "var(--sp-radius-card)",
        border: "1px solid var(--sp-border)",
        boxShadow: isHovered ? "var(--sp-shadow-hover)" : "none",
      }}
      role="button"
      tabIndex={0}
      onClick={openProduct}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") openProduct();
      }}
      onMouseEnter={() => {
        setIsHovered(true);
        prefetchProductPageChunk();
      }}
      onFocus={prefetchProductPageChunk}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          background: "var(--sp-bg)",
          aspectRatio: "1 / 1",
          borderRadius: compact ? undefined : "var(--sp-radius-card) var(--sp-radius-card) 0 0",
        }}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {showPlaceholder ? (
          <img
            src={placeholderSrc}
            alt={product.title}
            data-catalog-card-placeholder="true"
            className="absolute inset-0 h-full w-full object-cover object-center"
          />
        ) : (
          availableSlides.map((slide, index) => (
            <ImageWithFallback
              key={slide.key}
              src={slide.url}
              fallbackSrc={slide.fallbackUrl}
              alt={product.title}
              data-catalog-card-slide={index}
              data-catalog-slide-key={slide.key}
              data-catalog-card-active={index === safeActiveIndex ? "true" : "false"}
              loading={index === 0 ? "eager" : "lazy"}
              decoding="async"
              fetchPriority={index === 0 && imagePriority ? "high" : "auto"}
              className="absolute inset-0 h-full w-full object-cover object-center sp-transition"
              style={{
                opacity: index === safeActiveIndex ? 1 : 0,
                transform: isHovered ? "scale(1.05)" : "scale(1)",
                pointerEvents: "none",
              }}
              onExhausted={() => markSlideExhausted(slide.key)}
            />
          ))
        )}

        {showGalleryControls && !compact
          ? availableSlides.map((_, index) => (
              <div
                key={`zone-${index}`}
                data-catalog-card-hover-zone={index}
                className="absolute inset-y-0 z-10"
                style={{
                  left: `${(index / slideCount) * 100}%`,
                  width: `${100 / slideCount}%`,
                }}
                onMouseEnter={() => goToSlide(index)}
              />
            ))
          : null}

        {showGalleryControls ? (
          <div
            className="absolute bottom-2 left-0 right-0 z-20 flex justify-center gap-1"
            onClick={handleGalleryClick}
          >
            {availableSlides.map((_, index) => (
              <button
                key={`dot-${index}`}
                type="button"
                data-catalog-card-dot={index}
                aria-label={`Фото ${index + 1}`}
                className="h-1.5 w-1.5 rounded-full"
                style={{
                  background:
                    index === safeActiveIndex ? "var(--sp-text-primary)" : "var(--sp-border)",
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  suppressOpenRef.current = true;
                  goToSlide(index);
                }}
              />
            ))}
          </div>
        ) : null}

        <div className={sportBadgeCardClass(resolveSportCategory(product), compact)}>
          {product.sport_type_label_ru || "Товар"}
        </div>

        {!inStock ? (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ background: "rgba(255, 255, 255, 0.9)" }}
          >
            <span className="text-[14px] font-medium" style={{ color: "var(--sp-text-secondary)" }}>
              Нет в наличии
            </span>
          </div>
        ) : null}
      </div>

      <div
        className={
          compact
            ? "flex min-h-0 flex-1 flex-col gap-1 p-3"
            : "flex min-h-0 flex-1 flex-col gap-1.5 p-5"
        }
      >
        <div
          className="truncate text-[12px] uppercase tracking-[0.05em]"
          style={{ color: "var(--sp-text-muted)" }}
        >
          {product.brand || ""}
        </div>
        <h3
          className={
            compact
              ? "min-h-[2.5rem] text-[14px] font-medium leading-snug line-clamp-2"
              : "min-h-[2.75rem] text-[16px] font-medium leading-snug line-clamp-2"
          }
          style={{ color: "var(--sp-text-primary)" }}
        >
          {product.display_title || product.title}
        </h3>
        <div className="mt-auto flex flex-col gap-2">
          <div
            className={compact ? "text-[15px] font-semibold" : "text-[18px] font-semibold"}
            style={{ color: "var(--sp-text-primary)" }}
          >
            {moneyRub(product.sale_price)}
          </div>
          {inStock ? (
            <div
              className="sp-transition"
              style={{
                opacity: showCartControl ? 1 : 0,
                transform: showCartControl ? "translateY(0)" : "translateY(10px)",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {inCart ? (
                <div
                  className={`inline-flex w-full items-center justify-center rounded-full border border-sp-border ${compact ? "h-8 gap-2 px-2" : "h-[41px] gap-3 px-3"}`}
                >
                  <button
                    type="button"
                    onClick={() =>
                      onChangeCartQty(product, Math.max(0, cartQty - 1), cartLine?.variant_id)
                    }
                    disabled={cartBusy || adding}
                    className={`text-sp-text-primary hover:text-sp-blue sp-transition disabled:opacity-60 ${compact ? "h-7 w-7 text-[14px]" : "h-8 w-8"}`}
                  >
                    −
                  </button>
                  <span
                    className={`min-w-[3rem] text-center font-medium text-sp-text-primary ${compact ? "text-[12px]" : "text-[14px]"}`}
                  >
                    {cartQty} шт
                  </span>
                  <button
                    type="button"
                    onClick={() => onChangeCartQty(product, cartQty + 1, cartLine?.variant_id)}
                    disabled={cartBusy || adding}
                    className={`text-sp-text-primary hover:text-sp-blue sp-transition disabled:opacity-60 ${compact ? "h-7 w-7 text-[14px]" : "h-8 w-8"}`}
                  >
                    +
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={(e) => void handleCart(e)}
                  disabled={adding}
                  className={`${miniAppPillClass(true)} w-full disabled:opacity-60 hover:opacity-90${
                    compact ? " h-8 py-0" : " h-[41px] px-4 py-0 text-[14px]"
                  }`}
                >
                  {adding ? "Добавляем…" : "В корзину"}
                </button>
              )}
            </div>
          ) : (
            <div className={compact ? "h-[34px]" : "h-[42px]"} aria-hidden="true" />
          )}
        </div>
      </div>
    </motion.div>
  );
}
