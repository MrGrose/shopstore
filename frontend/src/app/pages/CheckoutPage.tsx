import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router";
import { ArrowLeft } from "lucide-react";
import { RequireAuth } from "../auth/RequireAuth";
import { useAuth } from "../auth/AuthContext";
import { CheckoutOrderAcceptedDialog } from "../components/CheckoutOrderAcceptedDialog";
import { PaymentDialog } from "../components/PaymentDialog";
import { CheckoutDeliveryField } from "../components/checkout/CheckoutDeliveryField";
import { NotificationChannelPicker } from "../components/checkout/NotificationChannelPicker";
import { CheckoutTotalsSummary } from "../components/checkout/CheckoutTotalsSummary";
import {
  StorefrontApiError,
  storefrontApiFetch,
} from "../../lib/storefront/api";
import {
  deliveryFieldErrorsMap,
  parseDeliveryFieldErrors,
  parsePromoFieldError,
  type DeliveryFormField,
} from "../../lib/storefront/checkoutErrors";
import {
  checkoutCardStyle,
  cartItemTitle,
  moneyRub,
  variantOptionParts,
  cartHasUnavailableItems,
  type ApiCart,
  type CheckoutPreview,
} from "../../lib/storefront/checkoutUi";
import { openStoreLegal } from "../../lib/storefront/legal";
import {
  normalizeRuMobilePhone,
  validateRuMobilePhone,
} from "../../lib/storefront/phone";
import {
  useStorefrontCompact,
  useStorefrontCompactPagePad,
} from "../../lib/storefront/useStorefrontSurface";
import { fetchDeliveryProfile } from "../../lib/storefront/deliveryProfile";
import {
  miniAppInputClass,
  miniAppPillClass,
} from "../../lib/storefront/miniAppUi";
import { mapApiErrorToUserMessage } from "../../lib/apiErrorMapper";
import {
  resolveCatalogCardPreviewUrl,
  resolveLineItemThumbUrl,
} from "../../lib/storefront/imageResolver";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import { catalogAllPath, productPath } from "../../lib/storefront/catalogNavigation";
import { invalidateCartQuery, useCart } from "../../hooks/useCart";
import {
  ORDER_PAYMENT_GATEWAY_UNAVAILABLE_TEXT,
  ORDER_PAYMENT_PENDING_TEXT,
  resolveCheckoutPostSubmitAction,
} from "../../lib/storefront/orderPaymentUi";

type CheckoutCreatedOrder = {
  id: number;
  payment_allowed?: boolean;
  payment_gateway_enabled?: boolean;
  total_amount: number | string;
  availability_confirmation_status?: string;
  availability_message_ru?: string | null;
};

type PostCheckoutDialog = "pending" | "gateway_unavailable" | null;

function hasTelegramIdentity(
  user:
    | {
        telegram_id?: number | string | null;
        identities?: Array<{ provider?: string | null }>;
      }
    | null
    | undefined,
): boolean {
  if (!user) return false;
  if (user.telegram_id != null && String(user.telegram_id).trim() !== "")
    return true;
  return Boolean(user.identities?.some((item) => item.provider === "telegram"));
}

export function CheckoutContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const checkoutReturnPath = `${location.pathname}${location.search}`;
  const queryClient = useQueryClient();
  const { user, refresh } = useAuth();
  const compact = useStorefrontCompact();
  const pagePad = useStorefrontCompactPagePad("pb-8");
  const {
    cart: cartData,
    isLoading: cartIsLoading,
    isFetching: cartIsFetching,
    error: cartQueryError,
  } = useCart();
  const cart = (cartData as ApiCart | undefined) ?? null;
  const cartLoading = cartIsLoading || cartIsFetching;
  const cartError = cartQueryError
    ? mapApiErrorToUserMessage(cartQueryError, {
        fallback: "Не удалось загрузить корзину",
      })
    : null;
  const [promoInput, setPromoInput] = useState("");
  const [appliedPromoCode, setAppliedPromoCode] = useState<string | null>(null);
  const [promoStatus, setPromoStatus] = useState<string | null>(null);
  const [promoError, setPromoError] = useState<string | null>(null);
  const appliedPromoCodeRef = useRef<string | null>(null);
  appliedPromoCodeRef.current = appliedPromoCode;
  const basePreviewRef = useRef<CheckoutPreview | null>(null);
  const previewCheckoutRef = useRef<(code: string | null) => Promise<void>>(
    async () => {},
  );
  const [preview, setPreview] = useState<CheckoutPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [postCheckoutDialog, setPostCheckoutDialog] =
    useState<PostCheckoutDialog>(null);
  const [createdOrder, setCreatedOrder] = useState<CheckoutCreatedOrder | null>(
    null,
  );
  const [paymentDialogOpen, setPaymentDialogOpen] = useState(false);
  const [agree, setAgree] = useState(false);
  const [delivery, setDelivery] = useState({
    last_name: "",
    first_name: "",
    street: "",
    house: "",
    apartment: "",
    city: "",
    postal_code: "",
    phone: "",
  });
  const [deliveryErrors, setDeliveryErrors] = useState<
    Partial<Record<DeliveryFormField, string>>
  >({});
  const [notificationChannels, setNotificationChannels] = useState<string[]>(
    [],
  );
  const [notificationEmail, setNotificationEmail] = useState("");
  const [notificationEmailVerified, setNotificationEmailVerified] =
    useState(false);

  const telegramLinked = hasTelegramIdentity(user);
  const telegramUsername =
    user?.telegram_username?.trim() ||
    user?.identities
      ?.find((item) => item.provider === "telegram")
      ?.telegram_username?.trim() ||
    "";

  // Бот привязывает TG в другой вкладке/приложении; без refresh страница остаётся «не привязано».
  useEffect(() => {
    if (telegramLinked) return;
    const sync = () => {
      void refresh();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") sync();
    };
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", sync);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh, telegramLinked]);

  const patchDelivery = useCallback(
    (field: DeliveryFormField, value: string) => {
      setDelivery((s) => ({ ...s, [field]: value }));
      setDeliveryErrors((errs) => {
        if (!errs[field]) return errs;
        const next = { ...errs };
        delete next[field];
        return next;
      });
    },
    [],
  );

  const refreshCart = useCallback(async () => {
    await invalidateCartQuery(queryClient);
  }, [queryClient]);

  const previewCheckout = useCallback(async (code: string | null) => {
    setCheckoutError(null);
    setPromoError(null);
    setPromoStatus(null);
    setPreview(null);
    setPreviewLoading(true);
    try {
      const trimmed = (code ?? "").trim();
      const data = await storefrontApiFetch<CheckoutPreview>(
        "/orders/checkout/preview",
        {
          method: "POST",
          body: JSON.stringify({ promo_code: trimmed || null }),
        },
      );
      setPreview(data ?? null);
      if (!trimmed) {
        basePreviewRef.current = data ?? null;
        setAppliedPromoCode(null);
      } else if (data?.promo_code_applied) {
        setAppliedPromoCode(data.promo_code_applied);
        setPromoStatus(`Промокод «${data.promo_code_applied}» применён.`);
      } else {
        setAppliedPromoCode(null);
        setPromoError(
          "Промокод не применён. Проверьте код и нажмите «Применить».",
        );
      }
    } catch (e) {
      if (e instanceof StorefrontApiError) {
        const promoMsg = parsePromoFieldError(e.apiDetail);
        if (promoMsg) {
          setPromoError(promoMsg);
          setCheckoutError("Не удалось применить промокод.");
          return;
        }
      }
      setCheckoutError(
        userFacingApiErrorMessage(e, "Не удалось пересчитать заказ"),
      );
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  previewCheckoutRef.current = previewCheckout;

  const cartSignature = useMemo(() => {
    if (!cart?.items?.length) return "";
    return cart.items
      .map(
        (item) => `${item.product_id}:${item.variant_id ?? 0}:${item.quantity}`,
      )
      .join("|");
  }, [cart]);

  useEffect(() => {
    void fetchDeliveryProfile()
      .then((profile) => {
        if (!profile) return;
        setDelivery({
          last_name: profile.last_name,
          first_name: profile.first_name,
          street: profile.street,
          house: profile.house,
          apartment: profile.apartment ?? "",
          city: profile.city,
          postal_code: profile.postal_code,
          phone: profile.phone,
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (cartLoading) return;
    if (cartHasUnavailableItems(cart)) {
      navigate("/cart", { replace: true });
      return;
    }
    if (!cart?.items?.length) return;
    void previewCheckoutRef.current(appliedPromoCodeRef.current);
  }, [cartLoading, cartSignature, navigate]);

  async function submitCheckout() {
    setCheckoutLoading(true);
    setCheckoutError(null);
    setDeliveryErrors({});
    const phoneError = validateRuMobilePhone(delivery.phone);
    if (phoneError) {
      setDeliveryErrors({ phone: phoneError });
      setCheckoutError("Проверьте выделенные поля доставки.");
      setCheckoutLoading(false);
      return;
    }
    try {
      const payload = {
        promo_code: appliedPromoCode,
        notification_channels: notificationChannels,
        notification_email: notificationChannels.includes("email")
          ? notificationEmail.trim()
          : null,
        delivery: {
          last_name: delivery.last_name,
          first_name: delivery.first_name,
          street: delivery.street,
          house: delivery.house,
          apartment: delivery.apartment.trim() ? delivery.apartment : null,
          city: delivery.city,
          postal_code: delivery.postal_code,
          phone:
            normalizeRuMobilePhone(delivery.phone) ?? delivery.phone.trim(),
        },
      };
      const created = await storefrontApiFetch<CheckoutCreatedOrder>(
        "/orders/checkout",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setPromoInput("");
      setAppliedPromoCode(null);
      setPromoStatus(null);
      setPromoError(null);
      setPreview(null);
      setAgree(false);
      setCreatedOrder(created);
      await refreshCart();
      const nextAction = resolveCheckoutPostSubmitAction(created);
      if (nextAction.action === "open_payment") {
        setPaymentDialogOpen(true);
        return;
      }
      if (nextAction.action === "show_pending") {
        setPostCheckoutDialog("pending");
        return;
      }
      if (nextAction.action === "show_gateway_unavailable") {
        setPostCheckoutDialog("gateway_unavailable");
        return;
      }
      navigate("/account?tab=orders");
    } catch (e) {
      if (e instanceof StorefrontApiError) {
        const hints = parseDeliveryFieldErrors(e.apiDetail);
        if (hints.length) {
          setDeliveryErrors(deliveryFieldErrorsMap(hints));
          setCheckoutError("Проверьте выделенные поля доставки.");
          return;
        }
      }
      setCheckoutError(
        userFacingApiErrorMessage(e, "Не удалось оформить заказ"),
      );
    } finally {
      setCheckoutLoading(false);
    }
  }

  const sectionTitleClass = compact
    ? "m-0 text-[10px] font-semibold uppercase tracking-[0.1em] text-sp-text-muted"
    : "text-[11px] font-semibold tracking-[0.1em] uppercase text-sp-text-muted m-0";
  const checkoutBlocked = !cart?.items?.length;
  const hasEmailChannel = notificationChannels.includes("email");
  const hasTelegramChannel = notificationChannels.includes("telegram");
  const notificationsBlocked =
    notificationChannels.length === 0 ||
    (hasTelegramChannel && !telegramLinked) ||
    (hasEmailChannel && !notificationEmailVerified);

  useEffect(() => {
    const linkedEmail = user?.identities?.find(
      (identity) => identity.provider === "email" && identity.email,
    )?.email;
    if (linkedEmail) {
      setNotificationEmail(linkedEmail);
      setNotificationEmailVerified(true);
    }
  }, [user?.identities]);

  return (
    <div className="min-h-screen bg-sp-bg text-sp-text-primary">
      <div className={compact ? `px-3 ${pagePad}` : "px-6 pb-16 pt-24"}>
        <div className="mx-auto max-w-[1200px]">
          <Link
            to="/cart"
            className={
              compact
                ? "mb-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-sp-blue no-underline sp-transition hover:opacity-80"
                : "mb-6 inline-flex items-center gap-2 text-sp-blue no-underline sp-transition hover:text-[#1a7fe0]"
            }
          >
            <ArrowLeft size={compact ? 14 : 18} />
            <span className={compact ? "" : "text-[15px] font-medium"}>
              Назад
            </span>
          </Link>

          <p
            className={`font-semibold uppercase tracking-[0.1em] text-sp-text-muted ${compact ? "mb-1.5 text-[10px]" : "mb-2 text-[11px]"}`}
          >
            Оформление
          </p>
          <h1
            className={`m-0 font-semibold tracking-tight ${compact ? "mb-4 text-[20px]" : "mb-8 text-[32px] md:text-[40px]"}`}
          >
            Оформление заказа
          </h1>

          {cartError ? (
            <div
              className={`mb-4 text-[#d4183d] ${compact ? "text-[12px]" : "mb-6"}`}
            >
              {cartError}
            </div>
          ) : null}

          {!cartLoading && !cart?.items?.length ? (
            <div
              className={`text-center ${compact ? "p-4" : "p-8"}`}
              style={checkoutCardStyle}
            >
              <p
                className={`m-0 mb-3 text-sp-text-secondary ${compact ? "text-[12px]" : "mb-4"}`}
              >
                Корзина пуста.
              </p>
              <Link
                to={catalogAllPath()}
                className={
                  compact
                    ? `${miniAppPillClass(true)} inline-flex no-underline`
                    : "inline-block px-6 py-3 text-[14px] font-medium no-underline sp-transition hover:opacity-90"
                }
                style={
                  compact
                    ? undefined
                    : {
                        background: "var(--sp-blue)",
                        color: "#FFFFFF",
                        borderRadius: "var(--sp-radius-pill)",
                      }
                }
              >
                Перейти в каталог
              </Link>
            </div>
          ) : (
            <div
              className={`grid w-full grid-cols-1 ${compact ? "gap-4" : "gap-8 lg:grid-cols-[1.5fr_1fr]"}`}
            >
              <div
                className={`min-w-0 w-full ${compact ? "space-y-4 p-4" : "space-y-8 p-8"}`}
                style={checkoutCardStyle}
              >
                <section className={compact ? "space-y-3" : "space-y-4"}>
                  <h2 className={sectionTitleClass}>Адрес доставки</h2>
                  <div className="checkout-form-grid-2">
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Фамилия"
                      value={delivery.last_name}
                      placeholder="Ivanov"
                      error={deliveryErrors.last_name}
                      onChange={(v) => patchDelivery("last_name", v)}
                    />
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Имя"
                      value={delivery.first_name}
                      placeholder="Ivan"
                      error={deliveryErrors.first_name}
                      onChange={(v) => patchDelivery("first_name", v)}
                    />
                  </div>
                  <div className="checkout-form-grid-2">
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Город"
                      value={delivery.city}
                      placeholder="Moscow"
                      error={deliveryErrors.city}
                      onChange={(v) => patchDelivery("city", v)}
                    />
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Индекс"
                      value={delivery.postal_code}
                      placeholder="101000"
                      error={deliveryErrors.postal_code}
                      onChange={(v) => patchDelivery("postal_code", v)}
                    />
                  </div>
                  <CheckoutDeliveryField
                    compact={compact}
                    label="Улица"
                    value={delivery.street}
                    placeholder="Tverskaya st"
                    error={deliveryErrors.street}
                    onChange={(v) => patchDelivery("street", v)}
                  />
                  <div className="checkout-form-grid-2">
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Дом"
                      value={delivery.house}
                      placeholder="10"
                      error={deliveryErrors.house}
                      onChange={(v) => patchDelivery("house", v)}
                    />
                    <CheckoutDeliveryField
                      compact={compact}
                      label="Квартира"
                      value={delivery.apartment}
                      placeholder="42"
                      error={deliveryErrors.apartment}
                      onChange={(v) => patchDelivery("apartment", v)}
                    />
                  </div>
                  <CheckoutDeliveryField
                    compact={compact}
                    label="Телефон"
                    value={delivery.phone}
                    placeholder="+79991234567"
                    error={deliveryErrors.phone}
                    onChange={(v) => patchDelivery("phone", v)}
                    inputMode="tel"
                    autoComplete="tel"
                  />
                </section>

                <section className={compact ? "space-y-2" : "space-y-3"}>
                  <h2 className={sectionTitleClass}>Промокод</h2>
                  <input
                    className={
                      compact
                        ? `${miniAppInputClass()} checkout-field-input w-full`
                        : "checkout-field-input w-full"
                    }
                    value={promoInput}
                    placeholder="Введите промокод"
                    onChange={(e) => {
                      const next = e.target.value;
                      setPromoInput(next);
                      setPromoError(null);
                      setPromoStatus(null);
                      if (
                        appliedPromoCode &&
                        next.trim() !== appliedPromoCode
                      ) {
                        setAppliedPromoCode(null);
                        if (basePreviewRef.current) {
                          setPreview(basePreviewRef.current);
                        }
                      }
                    }}
                    style={
                      compact
                        ? {
                            border: promoError
                              ? "1px solid #ff6b6b"
                              : undefined,
                          }
                        : {
                            padding: "0.75rem",
                            background: "var(--sp-bg)",
                            border: promoError
                              ? "1px solid #ff6b6b"
                              : "1px solid var(--sp-border)",
                            borderRadius: "var(--sp-radius-input)",
                            color: "var(--sp-text-primary)",
                          }
                    }
                  />
                  {promoError ? (
                    <div
                      className={`checkout-promo-error ${compact ? "!text-[11px]" : ""}`}
                      role="alert"
                    >
                      {promoError}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    onClick={() =>
                      void previewCheckout(promoInput.trim() || null)
                    }
                    disabled={previewLoading || !cart?.items?.length}
                    className={
                      compact
                        ? `${miniAppPillClass(false)} disabled:opacity-50`
                        : "rounded-full border border-sp-border px-4 py-2 text-[12px] font-medium text-sp-text-primary sp-transition hover:border-sp-blue disabled:opacity-50"
                    }
                  >
                    {previewLoading ? "Считаем…" : "Применить"}
                  </button>
                </section>

                <div
                  className={`w-full border-t border-sp-border pt-2 ${compact ? "space-y-3" : "space-y-4"}`}
                >
                  <NotificationChannelPicker
                    compact={compact}
                    channels={notificationChannels}
                    onChannelsChange={setNotificationChannels}
                    telegramLinked={telegramLinked}
                    email={notificationEmail}
                    onEmailChange={(value) => {
                      setNotificationEmail(value);
                      setNotificationEmailVerified(false);
                    }}
                    emailVerified={notificationEmailVerified}
                    onEmailVerified={async () => {
                      setNotificationEmailVerified(true);
                      await refresh();
                    }}
                  />
                  <label
                    className={`checkout-agree-label text-sp-text-secondary ${compact ? "text-[12px]" : "text-[14px]"}`}
                  >
                    <input
                      type="checkbox"
                      checked={agree}
                      onChange={(e) => setAgree(e.target.checked)}
                    />
                    <span className="checkout-agree-text">
                      Я ознакомился(ась) и принимаю условия{" "}
                      <a
                        href="/terms"
                        className="checkout-agree-link"
                        onClick={(e) => {
                          e.preventDefault();
                          openStoreLegal("/terms", "Публичная оферта");
                        }}
                      >
                        Публичной оферты
                      </a>
                      .
                    </span>
                  </label>


                  {checkoutError ? (
                    <div
                      className={`whitespace-pre-wrap text-[#d4183d] ${compact ? "text-[12px]" : ""}`}
                    >
                      {checkoutError}
                    </div>
                  ) : null}

                  <button
                    type="button"
                    onClick={() => void submitCheckout()}
                    disabled={
                      checkoutLoading ||
                      !agree ||
                      cartLoading ||
                      checkoutBlocked ||
                      notificationsBlocked
                    }
                    className={
                      compact
                        ? `${miniAppPillClass(true)} w-full disabled:opacity-50`
                        : "w-full py-4 text-[15px] font-semibold sp-transition hover:opacity-90 disabled:opacity-50"
                    }
                    style={
                      compact
                        ? undefined
                        : {
                            background: "var(--sp-blue)",
                            color: "#FFFFFF",
                            borderRadius: "var(--sp-radius-pill)",
                            border: "none",
                            cursor: "pointer",
                          }
                    }
                  >
                    {checkoutLoading
                      ? "Оформляем…"
                      : notificationsBlocked
                        ? "Оформить заказ — недоступно"
                        : "Оформить заказ"}
                  </button>
                </div>
              </div>

              <aside
                className={`h-fit min-w-0 w-full ${compact ? "space-y-3 p-4" : "space-y-6 p-8 lg:sticky lg:top-24"}`}
                style={checkoutCardStyle}
              >
                <h2
                  className={`m-0 font-semibold ${compact ? "text-[15px]" : "text-[18px]"}`}
                >
                  Ваш заказ
                </h2>
                {cartLoading ? (
                  <p
                    className={`m-0 text-sp-text-secondary ${compact ? "text-[12px]" : ""}`}
                  >
                    Загрузка…
                  </p>
                ) : !cart?.items?.length ? (
                  <p
                    className={`m-0 text-sp-text-secondary ${compact ? "text-[12px]" : ""}`}
                  >
                    Корзина пуста.
                  </p>
                ) : (
                  <div className={compact ? "space-y-3" : "space-y-4"}>
                    {cart.items.map((it) => {
                      const variantParts = variantOptionParts(it);
                      return (
                        <div
                          key={`${it.product_id}:${it.variant_id ?? ""}`}
                          className={`checkout-cart-line flex ${compact ? "gap-2" : "gap-3"}`}
                        >
                          {it.product_image_url ? (
                            <div
                              className={`shrink-0 overflow-hidden bg-sp-bg ${compact ? "h-12 w-12" : "h-14 w-14"}`}
                              style={{ borderRadius: compact ? "8px" : "10px" }}
                            >
                              <img
                                src={resolveLineItemThumbUrl(it.product_image_url) ?? ""}
                                alt=""
                                className="h-full w-full object-cover"
                              />
                            </div>
                          ) : null}
                          <div className="checkout-cart-line-info min-w-0 flex-1">
                            <Link
                              to={productPath(it.product_id)}
                              state={{
                                from: checkoutReturnPath,
                                previewImageUrl: resolveCatalogCardPreviewUrl(it.product_image_url),
                              }}
                              className={`checkout-cart-line-title block font-medium no-underline sp-transition hover:text-sp-blue ${
                                compact ? "text-[13px]" : "text-[15px]"
                              }`}
                            >
                              {cartItemTitle(it)}
                            </Link>
                            {it.product_brand ? (
                              <div
                                className={`text-sp-text-muted ${compact ? "text-[10px]" : "text-[13px]"}`}
                              >
                                {it.product_brand}
                              </div>
                            ) : null}
                            {variantParts.length ? (
                              <div
                                className={`text-sp-text-secondary ${compact ? "text-[11px]" : "text-[13px]"}`}
                              >
                                {variantParts.join(" · ")}
                              </div>
                            ) : null}
                          </div>
                          <div
                            className={`shrink-0 text-right ${compact ? "text-[12px]" : "text-[14px]"}`}
                          >
                            {it.quantity} × {moneyRub(it.price_snapshot)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                <CheckoutTotalsSummary
                  compact={compact}
                  preview={preview}
                  previewLoading={previewLoading}
                  cart={cart}
                  promoAppliedMessage={promoStatus}
                  promoIsApplied={Boolean(appliedPromoCode)}
                />
              </aside>
            </div>
          )}
        </div>
      </div>

      {createdOrder && postCheckoutDialog === "pending" ? (
        <CheckoutOrderAcceptedDialog
          open
          title={`Заказ №${createdOrder.id} оформлен`}
          message={ORDER_PAYMENT_PENDING_TEXT}
          disabledActionLabel="Оплатить"
          onClose={() => {
            setPostCheckoutDialog(null);
            navigate("/account?tab=orders");
          }}
        />
      ) : null}

      {createdOrder && postCheckoutDialog === "gateway_unavailable" ? (
        <CheckoutOrderAcceptedDialog
          open
          title={`Заказ №${createdOrder.id} оформлен`}
          message={ORDER_PAYMENT_GATEWAY_UNAVAILABLE_TEXT}
          closeLabel="К истории заказов"
          onClose={() => {
            setPostCheckoutDialog(null);
            navigate("/account?tab=orders");
          }}
        />
      ) : null}

      {createdOrder && paymentDialogOpen ? (
        <PaymentDialog
          open={paymentDialogOpen}
          orderId={createdOrder.id}
          totalAmount={createdOrder.total_amount}
          title={`Оплата заказа №${createdOrder.id}`}
          onClose={() => {
            setPaymentDialogOpen(false);
            navigate("/account?tab=orders");
          }}
        />
      ) : null}
    </div>
  );
}

export function CheckoutPage() {
  return (
    <RequireAuth>
      <CheckoutContent />
    </RequireAuth>
  );
}
