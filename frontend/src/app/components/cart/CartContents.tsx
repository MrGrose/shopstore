import { Link, useLocation } from "react-router";
import { X } from "lucide-react";
import {
  resolveCatalogCardPreviewUrl,
  resolveLineItemThumbUrl,
} from "../../../lib/storefront/imageResolver";
import { moneyRub, cartItemTitle, variantOptionParts, cartItemUnavailable, type ApiCart } from "../../../lib/storefront/checkoutUi";
import { productPath } from "../../../lib/storefront/catalogNavigation";
import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";

type Props = {
  cart: ApiCart | null;
  loading: boolean;
  error: string | null;
  actionError?: string | null;
  isMutating?: boolean;
  compact?: boolean;
  onChangeQty: (productId: number, nextQty: number, variantId?: number | null) => void;
  onCheckout: () => void | Promise<void>;
  checkoutDisabled?: boolean;
  showContinueShopping?: boolean;
  onContinueShopping?: () => void;
  onProductLinkClick?: () => void;
};

function variantLabel(it: ApiCart["items"][number]) {
  const parts = variantOptionParts(it);
  return parts.length ? parts.join(" · ") : null;
}

export function CartContents({
  cart,
  loading,
  error,
  actionError = null,
  isMutating = false,
  compact = false,
  onChangeQty,
  onCheckout,
  checkoutDisabled = false,
  showContinueShopping = false,
  onContinueShopping,
  onProductLinkClick,
}: Props) {
  const location = useLocation();
  const returnPath = `${location.pathname}${location.search}`;
  const items = cart?.items ?? [];
  const hasItems = items.length > 0;
  const hasUnavailableItems = items.some(cartItemUnavailable);

  return (
    <>
      <div className={compact ? "flex-1 overflow-y-auto px-3 py-3" : "flex-1 overflow-y-auto px-6 py-6"}>
        {loading ? (
          <p className={`m-0 text-sp-text-secondary ${compact ? "text-[12px]" : ""}`}>Загрузка…</p>
        ) : error ? (
          <p className={`m-0 text-red-500 ${compact ? "text-[12px]" : ""}`}>{error}</p>
        ) : !hasItems ? (
          <p className={`m-0 text-sp-text-secondary ${compact ? "text-[12px]" : ""}`}>Корзина пуста.</p>
        ) : (
          <div className={compact ? "space-y-3" : "space-y-4"}>
            {items.map((it) => {
              const unavailable = cartItemUnavailable(it);
              const maxQty = it.available_stock ?? it.quantity;

              return (
                <div
                  key={`${it.product_id}:${it.variant_id ?? ""}`}
                  className={`overflow-hidden border ${compact ? "rounded-xl" : "rounded-2xl"} ${
                    unavailable
                      ? "border-sp-border bg-[#eceff3]"
                      : "border-transparent bg-transparent"
                  }`}
                >
                  {unavailable ? (
                    <div
                      className={`font-medium text-sp-text-muted ${compact ? "px-3 py-1.5 text-[11px]" : "px-4 py-2 text-[13px]"}`}
                      style={{ background: "rgba(0, 0, 0, 0.06)" }}
                    >
                      Товар закончился
                    </div>
                  ) : null}
                  <div
                    className={`flex ${compact ? "gap-3 p-3" : "gap-4 p-4"} ${unavailable ? "opacity-70" : ""}`}
                  >
                    <div
                      className={`shrink-0 overflow-hidden bg-sp-bg ${compact ? "h-16 w-16" : "h-20 w-20"} ${unavailable ? "grayscale" : ""}`}
                      style={{ borderRadius: compact ? "10px" : "12px" }}
                    >
                      {it.product_image_url ? (
                        <img
                          src={resolveLineItemThumbUrl(it.product_image_url) ?? ""}
                          alt={cartItemTitle(it)}
                          className="h-full w-full object-cover"
                        />
                      ) : null}
                    </div>
                    <div className="min-w-0 flex-1">
                      <Link
                        to={productPath(it.product_id)}
                        state={{
                          from: returnPath,
                          previewImageUrl: resolveCatalogCardPreviewUrl(it.product_image_url),
                        }}
                        onClick={onProductLinkClick}
                        className={`m-0 mb-1 block truncate font-medium no-underline sp-transition hover:text-sp-blue ${
                          unavailable ? "text-sp-text-muted" : "text-sp-text-primary"
                        } ${compact ? "text-[13px]" : "text-[14px]"}`}
                      >
                        {cartItemTitle(it)}
                      </Link>
                      {it.product_brand ? (
                        <p className={`m-0 mb-1 text-sp-text-muted ${compact ? "text-[10px]" : "text-[12px]"}`}>
                          {it.product_brand}
                        </p>
                      ) : null}
                      {variantLabel(it) ? (
                        <p className={`m-0 mb-1.5 text-sp-text-secondary ${compact ? "text-[11px]" : "text-[12px]"}`}>
                          {variantLabel(it)}
                        </p>
                      ) : null}
                      <p
                        className={`m-0 mb-1.5 font-semibold ${unavailable ? "text-sp-text-muted" : "text-sp-text-primary"} ${compact ? "text-[13px]" : "text-[14px]"}`}
                      >
                        {moneyRub(Number(it.price_snapshot) * it.quantity)}
                      </p>
                      <div
                        className={`inline-flex items-center rounded-full border border-sp-border ${compact ? "gap-1 px-1.5 py-0.5" : "gap-2 px-2 py-1"}`}
                      >
                        <button
                          type="button"
                          disabled={isMutating}
                          onClick={() => void onChangeQty(it.product_id, Math.max(0, it.quantity - 1), it.variant_id)}
                          className={`text-sp-text-primary sp-transition hover:text-sp-blue disabled:cursor-not-allowed disabled:opacity-40 ${compact ? "h-6 w-6 text-[13px]" : "h-6 w-6"}`}
                        >
                          −
                        </button>
                        <span
                          className={`min-w-[1.5rem] text-center text-sp-text-secondary ${compact ? "text-[12px]" : "text-[13px]"}`}
                        >
                          {it.quantity}
                        </span>
                        <button
                          type="button"
                          disabled={isMutating || unavailable || it.quantity >= maxQty}
                          onClick={() => void onChangeQty(it.product_id, it.quantity + 1, it.variant_id)}
                          className={`text-sp-text-primary sp-transition hover:text-sp-blue disabled:cursor-not-allowed disabled:opacity-40 ${compact ? "h-6 w-6 text-[13px]" : "h-6 w-6"}`}
                        >
                          +
                        </button>
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={isMutating}
                      onClick={() => void onChangeQty(it.product_id, 0, it.variant_id)}
                      className="shrink-0 self-start p-1 text-sp-text-muted sp-transition hover:opacity-70 disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label="Удалить"
                    >
                      <X size={compact ? 16 : 18} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className={compact ? "border-t border-sp-border px-3 py-3" : "border-t border-sp-border px-6 py-6"}>
        {actionError ? (
          <p
            className={`m-0 text-red-500 ${compact ? "mb-3 text-[12px]" : "mb-4 text-[14px]"}`}
            role="alert"
          >
            {actionError}
          </p>
        ) : null}

        {hasUnavailableItems ? (
          <p
            className={`m-0 text-red-500 ${compact ? "mb-3 text-[12px]" : "mb-4 text-[14px]"}`}
            role="status"
          >
            Оформление недоступно — в корзине есть позиции не в наличии.
          </p>
        ) : null}


        {hasItems ? (
          <div
            className={`border-b border-sp-border ${compact ? "mb-3 space-y-2 pb-3" : "mb-6 space-y-3 pb-6"}`}
          >
            <div className={`flex justify-between ${compact ? "text-[12px]" : "text-[15px]"}`}>
              <span className="text-sp-text-secondary">Товары</span>
              <span className="text-sp-text-primary">
                {cart?.total_amount != null ? moneyRub(cart.total_amount) : "—"}
              </span>
            </div>
            <div className={`flex justify-between ${compact ? "text-[12px]" : "text-[15px]"}`}>
              <span className="text-sp-text-secondary">Доставка</span>
              <span className="text-sp-cyan">
                {cart?.delivery_fee_amount != null && Number(cart.delivery_fee_amount) > 0
                  ? moneyRub(cart.delivery_fee_amount)
                  : "Бесплатно"}
              </span>
            </div>
            <div
              className={`flex justify-between border-t border-sp-border font-semibold ${compact ? "pt-2 text-[15px]" : "pt-3 text-[18px]"}`}
            >
              <span className="text-sp-text-primary">Итого</span>
              <span className="text-sp-text-primary">
                {cart?.total_with_delivery_amount != null
                  ? moneyRub(cart.total_with_delivery_amount)
                  : cart?.total_amount != null
                    ? moneyRub(cart.total_amount)
                    : "—"}
              </span>
            </div>
          </div>
        ) : null}

        <button
          type="button"
          disabled={!hasItems || checkoutDisabled || hasUnavailableItems}
          onClick={() => void onCheckout()}
          className={
            compact
              ? `${miniAppPillClass(true)} w-full disabled:opacity-50`
              : "w-full py-4 text-[16px] font-medium text-white sp-transition hover:opacity-90 disabled:opacity-50"
          }
          style={
            compact
              ? undefined
              : {
                  background: "var(--sp-blue)",
                  borderRadius: "var(--sp-radius-pill)",
                }
          }
        >
          Оформить заказ
        </button>

        {showContinueShopping && onContinueShopping ? (
          <button
            type="button"
            onClick={onContinueShopping}
            className={
              compact
                ? `${miniAppPillClass(false)} mt-2 w-full`
                : "mt-4 block w-full cursor-pointer border-0 bg-transparent text-center text-[14px] text-sp-blue hover:underline"
            }
          >
            Продолжить покупки
          </button>
        ) : null}
      </div>
    </>
  );
}
