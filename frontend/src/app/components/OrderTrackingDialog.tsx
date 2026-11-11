import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  Check,
  Clock,
  Info,
  Mail,
  Package,
  PackageCheck,
  PackageSearch,
  Truck,
  XIcon,
} from "lucide-react";
import type {
  OrderShipment,
  OrderShipmentItem,
  OrderShipmentTrackingLink,
} from "./OrdersList";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import { storefrontApiFetch } from "../../lib/storefront/api";
import { resolveLineItemThumbUrl } from "../../lib/storefront/imageResolver";
import { StorefrontModalFrame } from "./StorefrontModalFrame";

type TrackingEvent = {
  key: string;
  at?: string | null;
  stage: string;
  title: string;
  description?: string | null;
};

type TrackingData = {
  available: boolean;
  current_status?: string | null;
  current_description?: string | null;
  current_stage?: string | null;
  carrier_label?: string | null;
  last_updated_at?: string | null;
  events: TrackingEvent[];
};

type TimelineVisualState = "current" | "completed" | "muted";

const STATUS_DESCRIPTION_FALLBACKS: Record<string, string> = {
  created: "Мы приняли заказ в обработку.",
  availability: "Наличие товара подтверждено.",
  paid: "Оплата получена, готовим заказ.",
  assembling: "Оформлен на Supplier-Demo.",
  delivery_started: "Посылка у перевозчика.",
  pick_up_scheduled: "Перевозчик ожидает посылку.",
  dispatched: "Посылка передана в доставку.",
  delivery_is_being_prepared: "Готовится к передаче получателю.",
  in_transit: "Посылка движется к вам.",
  border_crossing: "Посылка прибыла в страну назначения.",
  delivered: "Заказ успешно доставлен.",
  completed: "Заказ завершён.",
};

function isTerminalStage(stage?: string | null) {
  return stage === "delivered" || stage === "completed";
}

function resolveCurrentDescription(data: TrackingData) {
  const fromApi = data.current_description?.trim();
  if (fromApi) return fromApi;
  const stage = data.current_stage || "";
  return STATUS_DESCRIPTION_FALLBACKS[stage] || "Статус обновится автоматически.";
}

function resolveTimelineState(
  index: number,
  event: TrackingEvent,
  terminal: boolean,
): TimelineVisualState {
  if (!event.at) return "muted";
  if (index === 0 && !terminal) return "current";
  return "completed";
}

function formatEventTime(value?: string | null) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatLastUpdated(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const now = new Date();
  const sameDay =
    parsed.getFullYear() === now.getFullYear() &&
    parsed.getMonth() === now.getMonth() &&
    parsed.getDate() === now.getDate();
  const time = new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
  if (sameDay) return `Обновлено сегодня в ${time}`;
  return `Обновлено ${formatEventTime(value)}`;
}

function statusHeaderIcon(stage?: string | null, terminal?: boolean) {
  if (terminal) return PackageCheck;
  if (stage === "assembling" || stage === "paid" || stage === "created") return PackageSearch;
  return Truck;
}

function TrackingLoading() {
  return (
    <div
      className="animate-pulse rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg p-5 sm:p-6 shadow-[var(--sp-shadow-soft)]"
      aria-busy="true"
      aria-label="Загрузка движения заказа"
    >
      <div className="flex gap-3">
        <div className="size-12 shrink-0 rounded-full bg-sp-border" />
        <div className="flex-1 space-y-2">
          <div className="h-7 w-40 rounded-full bg-sp-border" />
          <div className="h-4 w-full max-w-sm rounded-full bg-sp-border" />
          <div className="h-3 w-48 rounded-full bg-sp-border" />
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <div className="h-7 w-40 rounded-full bg-sp-border" />
      </div>
      <div className="mt-4 border-t border-sp-border pt-4">
        <div className="mb-4 h-3 w-28 rounded-full bg-sp-border" />
        <div className="space-y-4 pl-10">
          {[0, 1, 2].map((row) => (
            <div key={row} className="space-y-2">
              <div className="h-4 w-44 rounded-full bg-sp-border" />
              <div className="h-3 w-32 rounded-full bg-sp-border" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TrackingError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg px-5 py-8 text-center">
      <p className="m-0 text-[15px] leading-relaxed text-sp-text-secondary">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex items-center justify-center rounded-full border border-sp-border px-5 py-2.5 text-[14px] font-medium text-sp-text-primary sp-transition hover:border-sp-blue hover:text-sp-blue"
      >
        Повторить
      </button>
    </div>
  );
}

function TrackingEmpty() {
  return (
    <div className="rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg px-5 py-10 text-center">
      <PackageSearch className="mx-auto mb-3 size-8 text-sp-text-muted" aria-hidden />
      <p className="m-0 text-[15px] font-medium text-sp-text-primary">Этапы появятся здесь</p>
      <p className="m-0 mt-2 text-[14px] leading-relaxed text-sp-text-secondary">
        Как только поставщик передаст посылку в доставку, мы обновим статус.
      </p>
    </div>
  );
}

function TimelineItem({
  event,
  state,
  index,
  showConnector,
}: {
  event: TrackingEvent;
  state: TimelineVisualState;
  index: number;
  showConnector: boolean;
}) {
  const isCurrent = state === "current";
  const isMuted = state === "muted";
  const hasTime = Boolean(event.at);

  return (
    <motion.li
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: 0.12 + index * 0.05, ease: [0.22, 1, 0.36, 1] }}
      className="relative pl-10 pb-4 last:pb-0"
    >
      {showConnector ? (
        <motion.span
          aria-hidden
          className="absolute left-[13px] top-7 w-px origin-top bg-sp-border"
          style={{ height: "calc(100% - 0.5rem)" }}
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.45, delay: 0.18 + index * 0.05, ease: [0.22, 1, 0.36, 1] }}
        />
      ) : null}

      {isCurrent ? (
        <motion.span
          aria-hidden
          className="absolute left-0 top-0 flex size-7 items-center justify-center rounded-full text-white"
          style={{ background: "var(--sp-blue)" }}
          animate={{
            boxShadow: [
              "0 0 0 0 color-mix(in srgb, var(--sp-blue) 35%, transparent)",
              "0 0 0 8px color-mix(in srgb, var(--sp-blue) 0%, transparent)",
              "0 0 0 0 color-mix(in srgb, var(--sp-blue) 0%, transparent)",
            ],
          }}
          transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }}
        >
          <Truck className="size-3.5" />
        </motion.span>
      ) : (
        <span
          aria-hidden
          className={`absolute left-0 top-0 flex size-7 items-center justify-center rounded-full ${
            isMuted
              ? "border-2 border-sp-border bg-sp-surface"
              : "bg-sp-text-primary text-white"
          }`}
        >
          {isMuted ? (
            <span className="size-1.5 rounded-full bg-sp-border" />
          ) : (
            <Check className="size-3.5" strokeWidth={2.5} />
          )}
        </span>
      )}

      <div className="flex items-baseline justify-between gap-3">
        <p
          className={`m-0 min-w-0 flex-1 text-[15px] font-semibold ${
            isCurrent
              ? "text-[color:var(--sp-blue)]"
              : isMuted
                ? "font-medium text-sp-text-muted"
                : "text-sp-text-primary"
          }`}
        >
          {event.title}
        </p>
        {hasTime ? (
          <time
            className="shrink-0 text-[11px] leading-none text-sp-text-muted whitespace-nowrap sm:text-[12px]"
            dateTime={event.at ?? undefined}
          >
            {formatEventTime(event.at)}
          </time>
        ) : null}
      </div>
      {event.description ? (
        <p
          className={`m-0 mt-0.5 text-[13px] leading-snug ${
            isMuted ? "text-sp-text-muted" : "text-sp-text-primary/75"
          }`}
        >
          {event.description}
        </p>
      ) : null}
    </motion.li>
  );
}

function TrackingCard({ data }: { data: TrackingData }) {
  const terminal = isTerminalStage(data.current_stage);
  const HeaderIcon = statusHeaderIcon(data.current_stage, terminal);
  const updatedLabel = formatLastUpdated(data.last_updated_at);
  const description = resolveCurrentDescription(data);

  return (
    <motion.section
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
      className="rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg p-5 sm:p-6 shadow-[var(--sp-shadow-soft)]"
      aria-label="Движение заказа"
    >
      <div className="flex items-start gap-3">
        <div className="relative shrink-0">
          <div
            className="flex size-12 items-center justify-center rounded-full sm:size-14"
            style={{
              background: terminal
                ? "var(--sp-green-soft-md)"
                : "color-mix(in srgb, var(--sp-blue) 12%, var(--sp-surface))",
              color: terminal ? "var(--sp-green)" : "var(--sp-blue)",
            }}
          >
            <HeaderIcon className="size-5 sm:size-6" aria-hidden />
          </div>
          {!terminal ? (
            <motion.span
              aria-hidden
              className="absolute -bottom-0.5 -right-0.5 flex size-3.5 items-center justify-center rounded-full bg-sp-surface"
              animate={{
                boxShadow: [
                  "0 0 0 0 color-mix(in srgb, var(--sp-blue) 35%, transparent)",
                  "0 0 0 8px color-mix(in srgb, var(--sp-blue) 0%, transparent)",
                  "0 0 0 0 color-mix(in srgb, var(--sp-blue) 0%, transparent)",
                ],
              }}
              transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }}
            >
              <span
                className="size-2.5 rounded-full"
                style={{ background: "var(--sp-blue)" }}
              />
            </motion.span>
          ) : null}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-[22px] font-bold leading-tight text-sp-text-primary sm:text-[24px]">
            {data.current_status || "Заказ обрабатывается"}
          </h3>
          <p className="m-0 mt-1 text-[14px] leading-snug text-sp-text-primary/80 sm:text-[15px]">
            {description}
          </p>
        </div>
      </div>

      {updatedLabel ? (
        <div className="mt-3">
          <span className="inline-flex items-center gap-1.5 text-[12px] text-sp-text-muted sm:text-[13px]">
            <Clock className="size-3.5" aria-hidden />
            {updatedLabel}
          </span>
        </div>
      ) : null}

      <div className="mt-4 border-t border-sp-border pt-4">
        <h4 className="m-0 mb-4 text-[12px] font-semibold uppercase tracking-[0.12em] text-sp-text-muted">
          История заказа
        </h4>
        <ol className="m-0 list-none p-0">
          {data.events.map((event, index) => {
            const state = resolveTimelineState(index, event, terminal);
            const showConnector = index < data.events.length - 1;
            return (
              <TimelineItem
                key={event.key}
                event={event}
                state={state}
                index={index}
                showConnector={showConnector}
              />
            );
          })}
        </ol>
      </div>
    </motion.section>
  );
}


const TRACKING_LINK_LABELS: Record<string, string> = {
  DHL: "DHL",
  Pochta: "Почта России",
};

function trackingLinkLabel(carrier: string): string {
  return TRACKING_LINK_LABELS[carrier] || carrier.trim() || "Отследить";
}

function trackingLinkIcon(carrier: string) {
  if (carrier === "Pochta") return Mail;
  return Truck;
}

function trackingLinkIconClass(carrier: string): string {
  if (carrier === "Pochta") return "size-3.5 shrink-0 text-sp-blue";
  return "size-3.5 shrink-0 text-sp-warm";
}

function shipmentStatusClass(status: string): string {
  if (status === "delivered") return "text-sp-green";
  if (status === "in_transit") return "text-sp-blue";
  return "text-sp-text-secondary";
}

function shipmentCj(shipment: OrderShipment): string {
  return shipment.supplier_tracking?.tracking_number?.trim() || "";
}

function shipmentTrackingLinks(shipment: OrderShipment): OrderShipmentTrackingLink[] {
  const rows = shipment.customer_tracking?.links;
  if (!Array.isArray(rows)) return [];
  return rows.filter((link) => Boolean(link?.url?.trim()));
}

function shipmentItemTitle(item: OrderShipmentItem): string {
  return item.display_title?.trim() || item.product_title?.trim() || "Товар";
}

function TrackingLinks({ links }: { links: OrderShipmentTrackingLink[] }) {
  if (links.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
      {links.map((link) => {
        const label = trackingLinkLabel(link.carrier);
        const Icon = trackingLinkIcon(link.carrier);
        return (
          <a
            key={`${link.carrier}:${link.url}`}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-sp-border px-3 py-1.5 text-[13px] font-medium text-sp-text-primary sp-transition hover:border-sp-blue hover:text-sp-blue sm:w-auto"
          >
            <Icon className={trackingLinkIconClass(link.carrier)} aria-hidden />
            {label}
          </a>
        );
      })}
    </div>
  );
}

function ShipmentItems({ items }: { items: OrderShipmentItem[] }) {
  if (items.length === 0) {
    return (
      <p className="m-0 text-[13px] text-sp-text-secondary">
        Состав посылки пока недоступен
      </p>
    );
  }
  return (
    <div>
      <p className="m-0 text-[12px] text-sp-text-secondary">Товары · {items.length}</p>
      <ul className="m-0 mt-2 list-none space-y-2 p-0">
        {items.map((item, index) => {
          const title = shipmentItemTitle(item);
          const thumb = item.product_image_url
            ? resolveLineItemThumbUrl(item.product_image_url)
            : null;
          return (
            <li
              key={`${item.order_item_id}:${index}`}
              className="m-0 flex items-center gap-2.5"
            >
              <div className="size-10 shrink-0 overflow-hidden rounded-[10px] bg-sp-bg">
                {thumb ? (
                  <img src={thumb} alt="" className="size-full object-cover" />
                ) : null}
              </div>
              <p className="m-0 min-w-0 flex-1 truncate text-[13px] text-sp-text-primary">
                {title}
              </p>
              <span className="shrink-0 text-[13px] text-sp-text-secondary">
                × {item.quantity}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}


export const SHIPMENT_INFO_DISMISSED_KEY = "storefront_shipment_info_dismissed";

function readShipmentInfoDismissed(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(SHIPMENT_INFO_DISMISSED_KEY) === "true";
}

function persistShipmentInfoDismissed(): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(SHIPMENT_INFO_DISMISSED_KEY, "true");
  }
}

function MultiShipmentInfoHint() {
  const [expanded, setExpanded] = useState(() => !readShipmentInfoDismissed());

  const dismiss = () => {
    persistShipmentInfoDismissed();
    setExpanded(false);
  };

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-transparent px-1 py-0.5 text-[13px] font-medium text-sp-text-secondary sp-transition hover:text-sp-blue"
      >
        <Info className="size-3.5 shrink-0" aria-hidden />
        Как доставляются посылки
      </button>
    );
  }

  return (
    <div
      className="rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg p-4 sm:p-5"
      role="note"
      aria-label="Информация о доставке посылок"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sp-blue/10">
          <Package className="size-4 text-sp-blue" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="m-0 text-[14px] font-semibold leading-snug text-sp-text-primary sm:text-[15px]">
              Информация
            </p>
            <button
              type="button"
              aria-label="Скрыть подсказку"
              onClick={dismiss}
              className="flex size-7 shrink-0 items-center justify-center rounded-full text-sp-text-secondary sp-transition hover:text-sp-text-primary"
            >
              <XIcon className="size-4" aria-hidden />
            </button>
          </div>
          <p className="m-0 mt-2 text-[13px] leading-relaxed text-sp-text-secondary">
            В некоторых случаях товары из одного заказа могут отправляться отдельно. Это позволяет
            оптимально организовать доставку и прохождение отправления. Если заказ будет разделён,
            для каждой посылки будет предоставлен отдельный трек-номер.
          </p>
        </div>
      </div>
    </div>
  );
}

function ShipmentCard({ shipment }: { shipment: OrderShipment }) {
  const cj = shipmentCj(shipment);
  const links = cj ? shipmentTrackingLinks(shipment) : [];

  return (
    <section
      className="rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-bg p-4 sm:p-5"
      aria-label={`Посылка ${shipment.seq}`}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 flex min-w-0 items-center gap-2.5 text-[15px] font-semibold text-sp-text-primary">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sp-blue/10">
            <Package className="size-4 text-sp-blue" aria-hidden />
          </span>
          Посылка {shipment.seq}
        </h3>
        <p
          className={`m-0 flex shrink-0 items-center gap-1.5 text-[13px] ${shipmentStatusClass(shipment.status)}`}
        >
          <span className="size-1.5 rounded-full bg-current" aria-hidden />
          {shipment.status_label}
        </p>
      </div>
      <div className="mt-3 space-y-3">
        {cj ? (
          <div>
            <p className="m-0 text-[12px] text-sp-text-secondary">Трек-номер</p>
            <p className="m-0 mt-0.5 truncate text-[15px] font-semibold text-sp-text-primary">
              {cj}
            </p>
          </div>
        ) : (
          <p className="m-0 text-[13px] text-sp-text-secondary">
            Трек-номер ещё не получен
          </p>
        )}
        <TrackingLinks links={links} />
        <ShipmentItems items={shipment.items ?? []} />
      </div>
    </section>
  );
}

export function OrderTrackingDialog({
  orderId,
  shipments = [],
  onClose,
}: {
  orderId: number;
  shipments?: OrderShipment[];
  onClose: () => void;
}) {
  const hasShipments = shipments.length > 0;
  const [data, setData] = useState<TrackingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!hasShipments);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (hasShipments) {
      setLoading(false);
      setError(null);
      setData(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    storefrontApiFetch<TrackingData>(`/orders/${orderId}/tracking`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((reason) => {
        if (active) {
          setData(null);
          setError(userFacingApiErrorMessage(reason, "Не удалось загрузить движение заказа"));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [orderId, reloadToken, hasShipments]);

  const retry = () => setReloadToken((value) => value + 1);

  const showEmpty = Boolean(data && (!data.available || data.events.length === 0));

  const orderBadge = (
    <span className="shrink-0 rounded-full border border-sp-border bg-sp-bg px-2.5 py-0.5 text-[12px] font-medium text-sp-text-secondary sm:text-[13px]">
      №{orderId}
    </span>
  );

  return (
    <StorefrontModalFrame
      title="Движение заказа"
      titleAddon={orderBadge}
      onClose={onClose}
      width="min(640px, 94vw)"
      height="min(86vh, 720px)"
      margin="max(3vh, 1rem) auto"
    >
      {hasShipments ? (
        <div className="space-y-3">
          {shipments.length > 1 ? <MultiShipmentInfoHint /> : null}
          {shipments.map((shipment) => (
            <ShipmentCard key={shipment.id} shipment={shipment} />
          ))}
        </div>
      ) : null}
      {!hasShipments && loading ? <TrackingLoading /> : null}
      {!hasShipments && !loading && error ? <TrackingError message={error} onRetry={retry} /> : null}
      {!hasShipments && !loading && !error && data && showEmpty ? <TrackingEmpty /> : null}
      {!hasShipments && !loading && !error && data && !showEmpty ? (
        <TrackingCard data={data} />
      ) : null}
    </StorefrontModalFrame>
  );
}

export const orderTrackingUi = {
  isTerminalStage,
  resolveTimelineState,
  resolveCurrentDescription,
  formatLastUpdated,
};
