import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  Package,
  User as UserIcon,
  Gift,
  Copy,
  Check,
  TrendingUp,
  LifeBuoy,
} from "lucide-react";
import { SupportSection } from "../components/support/SupportSection";
import { AccountLegalSection } from "../components/account/AccountLegalSection";
import { useAuth } from "../auth/AuthContext";
import { RequireAuth } from "../auth/RequireAuth";
import { AccountIdentitiesCard } from "../components/account/AccountIdentitiesCard";
import { OrdersList } from "../components/OrdersList";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import { storefrontApiFetch } from "../../lib/storefront/api";
import { moneyRub } from "../../lib/storefront/checkoutUi";
import { invalidateUserQuery, useUser } from "../../hooks/useUser";
import {
  fetchMyReferrer,
  formatReferralPercent,
  maskReferralOrderLabel,
  type MyReferrer,
  type ReferralCommissionSource,
} from "../../lib/storefront/referrer";
import { useStorefrontCompact, useStorefrontPageShellPad, useStorefrontSurface } from "../../lib/storefront/useStorefrontSurface";
import { accountDisplayLabel, userInitials } from "../../lib/storefront/userDisplay";

type ReferralMe = {
  referral_code: string;
  referral_alias?: string | null;
  referral_link: string;
  commission_percent: number | string;
  commission_percent_source?: ReferralCommissionSource;
  invited_count: number;
  orders_count: number;
  total_earned_rub: number | string;
  recent_earnings: Array<{
    order_id: number;
    order_amount_rub: number | string;
    commission_percent: number | string;
    commission_amount_rub: number | string;
    created_at: string;
  }>;
};

const TAB_VALUES = ["orders", "profile", "support", "referrals"] as const;
type TabValue = (typeof TAB_VALUES)[number];

const TABS: { id: TabValue; label: string; Icon: typeof Package }[] = [
  { id: "orders", label: "Заказы", Icon: Package },
  { id: "profile", label: "Профиль", Icon: UserIcon },
  { id: "referrals", label: "Реферальная", Icon: Gift },
  { id: "support", label: "Поддержка", Icon: LifeBuoy },
];

function formatDateTime(raw?: string | null) {
  if (!raw) return "—";
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw.includes("T") ? `${raw}Z` : raw;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function AccountContent() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { logout } = useAuth();
  const { user } = useUser();
  const compact = useStorefrontCompact();
  const surface = useStorefrontSurface();
  const pageShellPad = useStorefrontPageShellPad();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabRaw = searchParams.get("tab");
  const activeTab: TabValue = TAB_VALUES.includes(tabRaw as TabValue)
    ? (tabRaw as TabValue)
    : compact
      ? "profile"
      : "orders";

  const [referral, setReferral] = useState<ReferralMe | null>(null);
  const [referralLoading, setReferralLoading] = useState(false);
  const [referralError, setReferralError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [myReferrer, setMyReferrer] = useState<MyReferrer | null>(null);
  const [referrerLoading, setReferrerLoading] = useState(false);
  const [referrerError, setReferrerError] = useState<string | null>(null);

  const canBeReferred = user?.can_be_referred === true;
  const hasReferralAccess = user?.has_referral_program === true;
  const visibleTabs = TABS.filter((tab) => tab.id !== "referrals" || hasReferralAccess);

  const setTab = useCallback(
    (value: TabValue, options?: { topic?: string }) => {
      const params: Record<string, string> = { tab: value };
      if (options?.topic) {
        params.topic = options.topic;
      }
      setSearchParams(params, { replace: true });
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (activeTab === "referrals" && !hasReferralAccess) {
      setTab("orders");
    }
  }, [activeTab, hasReferralAccess, setTab]);

  const loadMyReferrer = useCallback(async () => {
    setReferrerLoading(true);
    setReferrerError(null);
    try {
      const data = await fetchMyReferrer();
      setMyReferrer(data);
    } catch (e) {
      setReferrerError(
        userFacingApiErrorMessage(e, "Не удалось загрузить данные реферала"),
      );
    } finally {
      setReferrerLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab !== "profile" || !canBeReferred) return;
    void loadMyReferrer();
  }, [activeTab, canBeReferred, loadMyReferrer, user?.referrer_id]);

  useEffect(() => {
    if (activeTab !== "referrals" || !hasReferralAccess) return;
    let cancelled = false;
    (async () => {
      setReferralLoading(true);
      setReferralError(null);
      try {
        const data = await storefrontApiFetch<ReferralMe>("/referral/me");
        if (!cancelled) setReferral(data);
      } catch (e) {
        if (!cancelled) {
          setReferralError(userFacingApiErrorMessage(e, "Не удалось загрузить рефералы"));
        }
      } finally {
        if (!cancelled) setReferralLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTab, hasReferralAccess]);

  async function copyReferralLink() {
    const link = referral?.referral_link?.trim();
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
    window.setTimeout(() => setCopied(false), 2000);
  }

  const displayName = accountDisplayLabel(user);
  const convRate =
    referral && referral.invited_count > 0
      ? Math.round((referral.orders_count / referral.invited_count) * 100)
      : 0;

  return (
    <div
      className={[
        "w-full min-h-screen px-4 sm:px-6 max-w-[1100px] mx-auto bg-sp-bg overflow-x-hidden [scrollbar-gutter:stable]",
        pageShellPad,
      ].join(" ")}
    >
      <div className="flex items-center gap-4 mb-8">
        <div
          className="w-14 h-14 flex items-center justify-center text-[18px] font-semibold shrink-0"
          style={{
            background: "linear-gradient(135deg, var(--sp-blue), var(--sp-cyan))",
            color: "#fff",
            borderRadius: "50%",
          }}
        >
          {userInitials(user?.name)}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-[22px] font-semibold m-0" style={{ color: "var(--sp-text-primary)" }}>
            {displayName}
          </h1>
        </div>
        {surface !== "miniapp" ? (
          <button
            type="button"
            onClick={() => void logout().then(() => navigate("/catalog", { replace: true }))}
            className="ml-auto shrink-0 px-4 py-2 text-[13px] font-medium sp-transition hover:opacity-80"
            style={{
              border: "1px solid var(--sp-border)",
              borderRadius: "var(--sp-radius-pill)",
              background: "var(--sp-surface)",
              color: "var(--sp-text-secondary)",
              cursor: "pointer",
            }}
          >
            Выйти
          </button>
        ) : null}
      </div>

      <div className="flex flex-col lg:flex-row gap-6 w-full min-w-0">
        <aside className="w-full lg:w-52 shrink-0 min-w-0">
          <nav className="lg:sticky w-full" style={{ top: "80px" }}>
            <div
              className={`grid ${visibleTabs.length === 2 ? "grid-cols-2" : "grid-cols-3"} lg:flex lg:flex-col gap-1 w-full`}
              style={{
                background: "var(--sp-surface)",
                border: "1px solid var(--sp-border)",
                borderRadius: "18px",
                padding: "8px",
              }}
            >
              {visibleTabs.map((tab) => {
                const active = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setTab(tab.id)}
                    className="flex items-center justify-center lg:justify-start gap-2 lg:gap-2.5 px-2 lg:px-4 py-3 sp-transition w-full text-left"
                    style={{
                      background: active ? "var(--sp-bg)" : "transparent",
                      color: active ? "var(--sp-text-primary)" : "var(--sp-text-secondary)",
                      borderRadius: "12px",
                      fontSize: "14px",
                      fontWeight: active ? 600 : 400,
                      border: "none",
                      cursor: "pointer",
                    }}
                  >
                    <tab.Icon
                      size={16}
                      style={{ color: active ? "var(--sp-blue)" : "var(--sp-text-muted)" }}
                    />
                    <span className="hidden sm:inline">{tab.label}</span>
                    <span className="sm:hidden text-[12px]">
                      {tab.id === "orders"
                        ? "Заказы"
                        : tab.id === "profile"
                          ? "Профиль"
                          : tab.id === "support"
                            ? "Поддержка"
                            : "Реф."}
                    </span>
                  </button>
                );
              })}
            </div>
          </nav>
        </aside>

        <main className="flex-1 min-w-0 w-full overflow-x-hidden">
          {activeTab === "orders" && (
            <div className="space-y-3 w-full min-w-0">
              <h2 className="text-[20px] font-semibold mb-5 m-0" style={{ color: "var(--sp-text-primary)" }}>
                История заказов
              </h2>
              <OrdersList variant="account" pageSize={10} paginated />
            </div>
          )}

          {activeTab === "profile" && (
            <div className="w-full min-w-0">
              <h2 className="text-[20px] font-semibold mb-5 m-0" style={{ color: "var(--sp-text-primary)" }}>
                Личная информация
              </h2>
              <AccountIdentitiesCard
                user={user ?? null}
                onUpdated={() => void invalidateUserQuery(queryClient)}
              />
              {canBeReferred ? (
              <div className="mt-6">
                <h3
                  className="text-[16px] font-semibold mb-3 m-0"
                  style={{ color: "var(--sp-text-primary)" }}
                >
                  Реферал
                </h3>
                {referrerLoading ? (
                  <p className="text-[13px] m-0" style={{ color: "var(--sp-text-muted)" }}>
                    Загрузка…
                  </p>
                ) : myReferrer?.referrer_id ? (
                  <div
                    style={{
                      background: "var(--sp-surface)",
                      border: "1px solid var(--sp-border)",
                      borderRadius: "18px",
                      padding: "20px 24px",
                    }}
                  >
                    <p className="text-[14px] m-0" style={{ color: "var(--sp-text-primary)" }}>
                      Сейчас привязан:{" "}
                      <strong>{myReferrer.referrer_name ?? `#${myReferrer.referrer_id}`}</strong>
                    </p>
                    <p className="text-[13px] m-0 mt-3" style={{ color: "var(--sp-text-muted)" }}>
                      Смена реферера — только через поддержку.
                    </p>
                    <button
                      type="button"
                      onClick={() => setTab("support", { topic: "referrer_change" })}
                      className="mt-4 px-4 py-2 text-[13px] font-medium sp-transition hover:opacity-80"
                      style={{
                        border: "1px solid var(--sp-border)",
                        borderRadius: "var(--sp-radius-pill)",
                        background: "var(--sp-bg)",
                        color: "var(--sp-text-secondary)",
                        cursor: "pointer",
                      }}
                    >
                      Написать в поддержку
                    </button>
                  </div>
                ) : referrerError ? (
                  <p className="text-[13px] m-0" style={{ color: "#ff8b8b" }}>
                    {referrerError}
                  </p>
                ) : (
                  <div
                    style={{
                      background: "var(--sp-surface)",
                      border: "1px solid var(--sp-border)",
                      borderRadius: "18px",
                      padding: "20px 24px",
                    }}
                  >
                    <p className="text-[14px] m-0" style={{ color: "var(--sp-text-secondary)" }}>
                      Реферал не привязан. Перейдите по ссылке приглашения — привязка сохранится
                      автоматически при входе.
                    </p>
                  </div>
                )}
              </div>
              ) : null}
              {surface === "miniapp" ? <AccountLegalSection /> : null}
            </div>
          )}

          {activeTab === "support" && <SupportSection />}

          {activeTab === "referrals" && (
            <div className="space-y-5 w-full min-w-0">
              <h2 className="text-[20px] font-semibold m-0" style={{ color: "var(--sp-text-primary)" }}>
                Реферальная программа
              </h2>

              {referralLoading ? (
                <div style={{ color: "var(--sp-text-secondary)" }}>Загрузка…</div>
              ) : referralError ? (
                <div style={{ color: "#ff8b8b" }}>{referralError}</div>
              ) : referral ? (
                <>
                  <div
                    style={{
                      background:
                        "linear-gradient(135deg, rgba(41,151,255,0.08) 0%, rgba(90,200,250,0.08) 100%)",
                      border: "1px solid rgba(41,151,255,0.2)",
                      borderRadius: "18px",
                      padding: "24px",
                    }}
                  >
                    <div className="mb-3 space-y-3">
                      {referral.commission_percent_source === "disabled" ? (
                        <p
                          className="text-[13px] m-0"
                          style={{ color: "var(--sp-text-secondary)" }}
                        >
                          Реферальные начисления для вашего аккаунта отключены.
                        </p>
                      ) : (
                        <>
                          <p
                            className="text-[13px] m-0"
                            style={{ color: "var(--sp-text-secondary)" }}
                          >
                            Приглашайте друзей и получайте бонусы за их завершённые заказы.
                            Бонус начисляется только за пользователей, приглашённых вами
                            напрямую.
                          </p>
                          <p
                            className="text-[13px] m-0"
                            style={{ color: "var(--sp-text-secondary)" }}
                          >
                            Ваша персональная ссылка и условия —{" "}
                            <strong>
                              {formatReferralPercent(referral.commission_percent)}%
                            </strong>
                            .
                          </p>
                          <p className="text-[13px] m-0">
                            <Link
                              to="/referral-rules"
                              className="font-medium text-sp-blue no-underline sp-transition hover:opacity-80"
                            >
                              Правила программы
                            </Link>
                          </p>
                        </>
                      )}
                    </div>
                    {referral.referral_alias ? (
                      <p className="text-[12px] mb-3 m-0" style={{ color: "var(--sp-text-muted)" }}>
                        Короткая ссылка: <span className="font-mono">/ref/{referral.referral_alias}</span>
                      </p>
                    ) : null}
                    <div
                      className="flex items-center gap-3 px-4 py-3 min-w-0 overflow-hidden"
                      style={{
                        background: "var(--sp-surface)",
                        border: "1px solid var(--sp-border)",
                        borderRadius: "12px",
                      }}
                    >
                      <span
                        className="flex-1 text-[14px] font-mono truncate"
                        style={{ color: "var(--sp-text-primary)" }}
                      >
                        {referral.referral_link}
                      </span>
                      <button
                        type="button"
                        onClick={() => void copyReferralLink()}
                        className="flex items-center gap-1.5 px-3 py-1.5 sp-transition"
                        style={{
                          background: copied ? "rgba(48,209,88,0.1)" : "rgba(41,151,255,0.1)",
                          color: copied ? "#30D158" : "var(--sp-blue)",
                          borderRadius: "8px",
                          fontSize: "13px",
                          fontWeight: 500,
                          whiteSpace: "nowrap",
                          border: "none",
                          cursor: "pointer",
                        }}
                      >
                        {copied ? <Check size={14} /> : <Copy size={14} />}
                        {copied ? "Скопировано" : "Копировать"}
                      </button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: "Приглашено", value: referral.invited_count, suffix: "чел." },
                      { label: "Заказов", value: referral.orders_count, suffix: "шт." },
                      { label: "Конверсия", value: `${convRate}`, suffix: "%" },
                      {
                        label: "Начислено",
                        value: moneyRub(referral.total_earned_rub).replace(" ₽", ""),
                        suffix: "₽",
                      },
                    ].map((stat) => (
                      <div
                        key={stat.label}
                        className="text-center px-4 py-5"
                        style={{
                          background: "var(--sp-surface)",
                          border: "1px solid var(--sp-border)",
                          borderRadius: "16px",
                        }}
                      >
                        <div className="text-[24px] font-semibold" style={{ color: "var(--sp-text-primary)" }}>
                          {stat.value}
                          <span
                            className="text-[13px] font-normal ml-1"
                            style={{ color: "var(--sp-text-muted)" }}
                          >
                            {stat.suffix}
                          </span>
                        </div>
                        <div className="text-[12px] mt-1" style={{ color: "var(--sp-text-muted)" }}>
                          {stat.label}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div
                    style={{
                      background: "var(--sp-surface)",
                      border: "1px solid var(--sp-border)",
                      borderRadius: "18px",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      className="px-6 py-4 flex items-center gap-2"
                      style={{ borderBottom: "1px solid var(--sp-border)" }}
                    >
                      <TrendingUp size={16} style={{ color: "var(--sp-blue)" }} />
                      <span className="text-[14px] font-semibold" style={{ color: "var(--sp-text-primary)" }}>
                        Начисления
                      </span>
                    </div>
                    {referral.recent_earnings.length > 0 ? (
                      <div className="px-6 pb-5 overflow-x-auto">
                        <table className="w-full text-[13px]" style={{ borderCollapse: "collapse" }}>
                          <thead>
                            <tr style={{ color: "var(--sp-text-muted)" }}>
                              <th className="text-left font-medium py-2 pr-3">Заказ</th>
                              <th className="text-left font-medium py-2 pr-3">Дата</th>
                              <th className="text-right font-medium py-2 pr-3">Сумма заказа</th>
                              <th className="text-right font-medium py-2 pr-3">%</th>
                              <th className="text-right font-medium py-2">Сумма</th>
                            </tr>
                          </thead>
                          <tbody>
                            {referral.recent_earnings.map((row) => (
                              <tr
                                key={row.order_id}
                                style={{ borderTop: "1px solid var(--sp-border)" }}
                              >
                                <td className="py-3 pr-3" style={{ color: "var(--sp-text-primary)" }}>
                                  {maskReferralOrderLabel(row.order_id)}
                                </td>
                                <td className="py-3 pr-3" style={{ color: "var(--sp-text-secondary)" }}>
                                  {formatDateTime(row.created_at)}
                                </td>
                                <td className="py-3 pr-3 text-right" style={{ color: "var(--sp-text-secondary)" }}>
                                  {moneyRub(row.order_amount_rub)}
                                </td>
                                <td className="py-3 pr-3 text-right" style={{ color: "var(--sp-text-secondary)" }}>
                                  {formatReferralPercent(row.commission_percent)}%
                                </td>
                                <td className="py-3 text-right font-medium" style={{ color: "var(--sp-text-primary)" }}>
                                  {moneyRub(row.commission_amount_rub)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="px-6 pb-5 m-0 text-[13px]" style={{ color: "var(--sp-text-muted)" }}>
                        Пока нет начислений. Бонус появится после выполнения заказа приглашённого клиента.
                      </p>
                    )}
                  </div>
                </>
              ) : null}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export function AccountPage() {
  return (
    <RequireAuth>
      <AccountContent />
    </RequireAuth>
  );
}
