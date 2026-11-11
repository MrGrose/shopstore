import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { CartContents } from "../components/cart/CartContents";
import { catalogAllPath } from "../../lib/storefront/catalogNavigation";
import { changeCartQty } from "../../lib/storefront/cart";
import { checkoutCardStyle, cartHasUnavailableItems, type ApiCart } from "../../lib/storefront/checkoutUi";
import { useRefreshOnPageActive } from "../../lib/storefront/useRefreshOnPageActive";
import { useAuth } from "../auth/AuthContext";
import { isTelegramMiniAppRoute } from "../../lib/storefront/miniApp";
import { userFacingApiErrorMessage } from "../../lib/apiErrorMapper";
import { mapApiErrorToUserMessage } from "../../lib/errorMessages";
import { useStorefrontCompact, useStorefrontCompactPagePad } from "../../lib/storefront/useStorefrontSurface";
import { cartQueryKey, invalidateCartQuery, syncCartQueryCache, useCart } from "../../hooks/useCart";

export function CartPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const compact = useStorefrontCompact();
  const pagePad = useStorefrontCompactPagePad("pb-8");
  const queryClient = useQueryClient();
  const { cart: cartData, isLoading, isFetching, error: cartQueryError } = useCart();
  const cart = (cartData as ApiCart | undefined) ?? null;
  const loading = isLoading || isFetching;
  const error = cartQueryError
    ? mapApiErrorToUserMessage(cartQueryError, {
        fallback: "Не удалось загрузить корзину",
      })
    : null;
  const [cartActionError, setCartActionError] = useState<string | null>(null);
  const [cartMutating, setCartMutating] = useState(false);

  const refreshCart = useCallback(async (): Promise<ApiCart | null> => {
    await invalidateCartQuery(queryClient);
    const next = queryClient.getQueryData<ApiCart>(cartQueryKey);
    return next ?? null;
  }, [queryClient]);

  useRefreshOnPageActive(refreshCart);

  async function changeQty(productId: number, nextQty: number, variantId?: number | null) {
    if (cartMutating) return;
    const pid = Number(productId);
    if (!Number.isFinite(pid) || pid <= 0) return;
    setCartMutating(true);
    setCartActionError(null);
    try {
      const updated = await changeCartQty(pid, nextQty, variantId ?? null);
      if (updated) {
        syncCartQueryCache(queryClient, updated);
      } else {
        await refreshCart();
      }
    } catch (e) {
      setCartActionError(
        userFacingApiErrorMessage(e, "Не удалось изменить количество"),
      );
      await refreshCart();
    } finally {
      setCartMutating(false);
    }
  }

  async function beginCheckout() {
    const next = await refreshCart();
    if (cartHasUnavailableItems(next)) return;

    if (!isAuthenticated && !isTelegramMiniAppRoute()) {
      navigate(`/login?next=${encodeURIComponent("/checkout")}`);
      return;
    }
    navigate("/checkout");
  }

  return (
    <div className="min-h-screen bg-sp-bg text-sp-text-primary">
      <div className={compact ? `px-3 ${pagePad}` : "px-6 pb-16 pt-24"}>
        <div className="mx-auto max-w-[720px]">
          <Link
            to={catalogAllPath()}
            className={
              compact
                ? "mb-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-sp-blue no-underline sp-transition hover:opacity-80"
                : "mb-6 inline-flex items-center gap-2 text-sp-blue no-underline sp-transition hover:text-[#1a7fe0]"
            }
          >
            <ArrowLeft size={compact ? 14 : 18} />
            <span className={compact ? "" : "text-[15px] font-medium"}>Назад в каталог</span>
          </Link>

          <h1
            className={`m-0 font-semibold tracking-tight ${compact ? "mb-4 text-[20px]" : "mb-8 text-[32px] md:text-[40px]"}`}
          >
            Корзина
          </h1>

          <div
            className={`flex flex-col ${compact ? "min-h-0" : "min-h-[420px]"}`}
            style={checkoutCardStyle}
          >
            <CartContents
              cart={cart}
              loading={loading}
              error={error}
              actionError={cartActionError}
              isMutating={cartMutating}
              compact={compact}
              onChangeQty={changeQty}
              onCheckout={beginCheckout}
              showContinueShopping
              onContinueShopping={() => navigate(catalogAllPath())}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
