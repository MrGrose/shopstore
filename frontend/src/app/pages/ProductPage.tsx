import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { ProductDetail, type ProductDetailData } from "../components/product/ProductDetail";
import {
  addCartItem,
  changeCartQty,
  getCatalogCartItem,
  pdpCartQtyForVariant,
  resolvePdpCartLineAfterAdd,
} from "../../lib/storefront/cart";
import { catalogAllPath } from "../../lib/storefront/catalogNavigation";
import type { ApiCart } from "../../lib/storefront/checkoutUi";
import { PDP_COMPACT_SCROLL_PAD } from "../../lib/storefront/miniApp";
import { userFacingApiErrorMessage } from "../../lib/apiErrorMapper";
import { mapApiErrorToUserMessage } from "../../lib/errorMessages";
import { useStorefrontCompact, useStorefrontCompactPagePad } from "../../lib/storefront/useStorefrontSurface";
import { invalidateCartQuery, syncCartQueryCache, useCart } from "../../hooks/useCart";
import { useProduct } from "../../hooks/useProduct";
import { readPdpTransitionPreviewUrl } from "../../lib/storefront/imageResolver";
import { PdpHeroStage } from "../components/PageRouteFallback";
import {
  buildVariantConstraintPresetFromSearchParams,
  pickVariantConstraintPreset,
  type ProductPageLocationState,
} from "../../lib/storefront/catalogFilterParams";

export function ProductPage() {
  const { productId } = useParams<{ productId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const compact = useStorefrontCompact();
  const pagePad = useStorefrontCompactPagePad();
  const previewImageUrl = readPdpTransitionPreviewUrl(
    (location.state as ProductPageLocationState | null)?.previewImageUrl,
  );
  const [cartBusy, setCartBusy] = useState(false);
  const [cartActionError, setCartActionError] = useState<string | null>(null);
  const [selectedVariantId, setSelectedVariantId] = useState<number | null>(null);
  const [syncVariantId, setSyncVariantId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const { cart } = useCart();
  const [searchParams] = useSearchParams();
  const variantConstraintPreset = useMemo(() => {
    const state = location.state as ProductPageLocationState | null;
    const urlPreset = buildVariantConstraintPresetFromSearchParams(searchParams);
    return pickVariantConstraintPreset(state?.variantConstraintPreset, urlPreset);
  }, [location.state, searchParams]);

  const pid = Number(productId);
  const pidValid = Number.isFinite(pid) && pid > 0;
  const {
    product: loadedProduct,
    isLoading,
    error: productError,
  } = useProduct(pid, pidValid);
  const product = (loadedProduct ?? null) as ProductDetailData | null;
  const invalidIdError = !pidValid ? "Неверный идентификатор товара" : null;
  const error = invalidIdError
    ?? (productError
      ? mapApiErrorToUserMessage(productError, { fallback: "Не удалось загрузить товар" })
      : null);
  const loading = pidValid && isLoading;

  const cartQty = useMemo(() => {
    if (!product) return 0;
    return pdpCartQtyForVariant(cart?.items, product.id, selectedVariantId);
  }, [product, cart, selectedVariantId]);

  const cartLineVariantId =
    cartQty > 0 && selectedVariantId != null ? Number(selectedVariantId) : null;

  const handleSelectedVariantChange = useCallback((variantId: number | null) => {
    setSelectedVariantId(variantId);
  }, []);

  useEffect(() => {
    if (syncVariantId != null && selectedVariantId === syncVariantId) {
      setSyncVariantId(null);
    }
  }, [syncVariantId, selectedVariantId]);

  useEffect(() => {
    if (!product || !cart) return;
    const line = getCatalogCartItem(cart.items, product.id);
    if (!line) return;
    const qty = Number(line.quantity ?? 0);
    const vid =
      line.variant_id === null || line.variant_id === undefined
        ? null
        : Number(line.variant_id);
    if (qty > 0 && vid != null) {
      setSelectedVariantId(vid);
      setSyncVariantId(vid);
    }
  }, [product?.id, cart]);

  function applyPdpCartState(cart: ApiCart, variantId?: number | null) {
    if (!product) return;
    const exactQty = pdpCartQtyForVariant(cart.items, product.id, variantId);
    if (exactQty > 0) {
      setSelectedVariantId(variantId ?? null);
      setSyncVariantId(null);
      return;
    }
    const resolved = resolvePdpCartLineAfterAdd(cart.items, product.id, variantId);
    if (resolved.qty > 0 && resolved.variantId != null) {
      setSyncVariantId(resolved.variantId);
      setSelectedVariantId(resolved.variantId);
      return;
    }
    setSelectedVariantId(variantId ?? null);
    setSyncVariantId(null);
  }

  async function addToCart(variantId?: number | null) {
    if (!product) return;
    setCartBusy(true);
    setCartActionError(null);
    try {
      const cart = await addCartItem(product.id, variantId ?? null);
      syncCartQueryCache(queryClient, cart);
      applyPdpCartState(cart as ApiCart, variantId);
    } catch (e) {
      setCartActionError(
        userFacingApiErrorMessage(e, "Не удалось добавить в корзину"),
      );
      await invalidateCartQuery(queryClient);
    } finally {
      setCartBusy(false);
    }
  }

  async function changeQty(nextQty: number, variantId?: number | null) {
    if (!product) return;
    setCartBusy(true);
    setCartActionError(null);
    try {
      const cart = await changeCartQty(product.id, nextQty, variantId ?? null);
      if (cart?.items) {
        syncCartQueryCache(queryClient, cart);
        applyPdpCartState(cart as ApiCart, variantId);
      } else {
        await invalidateCartQuery(queryClient);
      }
    } catch (e) {
      setCartActionError(
        userFacingApiErrorMessage(e, "Не удалось изменить количество"),
      );
      await invalidateCartQuery(queryClient);
    } finally {
      setCartBusy(false);
    }
  }

  if (loading) {
    return (
      <div
        aria-busy="true"
        aria-label="Загрузка товара"
        style={compact ? { paddingBottom: PDP_COMPACT_SCROLL_PAD } : undefined}
      >
        <PdpHeroStage compact={compact} pagePad={pagePad}>
          {previewImageUrl ? (
            <img
              data-pdp-hero="preview"
              src={previewImageUrl}
              alt=""
              className="absolute inset-0 h-full w-full object-cover object-center"
              loading="eager"
              fetchPriority="high"
              decoding="async"
            />
          ) : (
            <div className="h-full w-full animate-pulse bg-sp-border/40" />
          )}
        </PdpHeroStage>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className={`min-h-screen bg-sp-bg ${compact ? `px-3 ${pagePad}` : "px-6 pt-32"}`}>
        <p className="text-red-500">{error || "Товар не найден"}</p>
        <button
          type="button"
          onClick={() => navigate(catalogAllPath())}
          className="mt-4 text-sp-blue bg-transparent border-0 cursor-pointer"
        >
          В каталог
        </button>
      </div>
    );
  }

  return (
    <ProductDetail
      product={product}
      cartQty={cartQty}
      cartBusy={cartBusy}
      cartActionError={cartActionError}
      cartLineVariantId={cartLineVariantId}
      onAddToCart={addToCart}
      onChangeQty={changeQty}
      onSelectedVariantChange={handleSelectedVariantChange}
      syncVariantId={syncVariantId}
      variantConstraintPreset={variantConstraintPreset}
    />
  );
}
