import {
  moneyRub,
  rubAmount,
  type ApiCart,
  type CheckoutPreview,
} from "../../../lib/storefront/checkoutUi";

type Props = {
  preview: CheckoutPreview | null;
  previewLoading: boolean;
  cart: ApiCart | null;
  promoAppliedMessage: string | null;
  promoIsApplied?: boolean;
  compact?: boolean;
};

export function CheckoutTotalsSummary({
  preview,
  previewLoading,
  cart,
  promoAppliedMessage,
  promoIsApplied = false,
  compact = false,
}: Props) {
  const hasPreview = Boolean(preview);
  const discount = hasPreview && promoIsApplied ? rubAmount(preview?.discount_items_amount) : 0;
  const hasDiscount = discount > 0;

  const itemsSubtotal = hasPreview
    ? promoIsApplied
      ? preview!.discounted_items_subtotal_amount
      : preview!.items_subtotal_amount
    : cart?.total_amount;
  const itemsBeforeDiscount = hasPreview && promoIsApplied ? preview!.items_subtotal_amount : null;

  const deliveryFee = hasPreview ? preview!.delivery_fee_amount : (cart?.delivery_fee_amount ?? 0);
  const total = hasPreview ? preview!.total_amount : (cart?.total_with_delivery_amount ?? cart?.total_amount);

  const dash = previewLoading ? "…" : "—";

  return (
    <div className={`grid text-sp-text-primary ${compact ? "gap-1.5 text-[12px]" : "gap-2"}`}>
      <div className="flex flex-wrap justify-between gap-4">
        <span className="text-sp-text-secondary">Товары</span>
        <span className="text-right">
          {hasPreview ? (
            hasDiscount ? (
              <>
                <span className="checkout-summary-old">{moneyRub(itemsBeforeDiscount!)}</span>
                <span className="checkout-summary-new">{moneyRub(itemsSubtotal!)}</span>
              </>
            ) : (
              moneyRub(itemsSubtotal!)
            )
          ) : cart ? (
            moneyRub(itemsSubtotal!)
          ) : (
            dash
          )}
        </span>
      </div>
      <div className="flex justify-between">
        <span className="text-sp-text-secondary">Доставка</span>
        <span>{hasPreview || cart ? moneyRub(deliveryFee) : dash}</span>
      </div>
      <div className={`flex justify-between border-t border-sp-border ${compact ? "pt-1.5" : "pt-2"}`}>
        <span className="font-semibold">Итого к оплате</span>
        <span className={`font-semibold ${compact ? "text-[15px]" : "text-[18px]"}`}>
          {hasPreview || cart ? moneyRub(total!) : dash}
        </span>
      </div>
      {promoAppliedMessage ? (
        <div className={`checkout-promo-applied ${compact ? "!text-[11px]" : ""}`} role="status">
          {promoAppliedMessage}
        </div>
      ) : null}
      {hasPreview && preview?.customs_duty_notice ? (
        <div className={`leading-snug text-sp-text-secondary ${compact ? "pt-1 text-[11px]" : "pt-2 text-[13px]"}`}>
          {preview.customs_duty_notice}
        </div>
      ) : null}
    </div>
  );
}
