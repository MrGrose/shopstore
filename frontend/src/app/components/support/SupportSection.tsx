import { MessageCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { useSearchParams } from "react-router";
import { storefrontApiFetch, storefrontApiFetchBlob } from "../../../lib/storefront/api";

type SupportAttachment = {
  id: number;
  content_type: string;
  byte_size: number;
};

type SupportTicketListItem = {
  id: number;
  topic: string;
  topic_label: string;
  status: string;
  order_id: number | null;
  created_at: string;
  updated_at: string;
  last_message_preview: string | null;
};

type SupportMessage = {
  id: number;
  author_type: "customer" | "staff";
  body: string;
  created_at: string;
  attachments?: SupportAttachment[];
};

type SupportTicketDetail = SupportTicketListItem & {
  closed_at: string | null;
  messages: SupportMessage[];
};

type LinkableOrder = {
  id: number;
  status: string;
  total_amount: string;
  created_at: string;
};

type SupportTicketListPage = {
  items: SupportTicketListItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

const TOPIC_OPTIONS = [
  { value: "order_question", label: "Вопрос по заказу" },
  { value: "delivery_question", label: "Вопрос по доставке" },
  { value: "product_problem", label: "Проблема с товаром" },
  { value: "referrer_change", label: "Смена реферера" },
  { value: "general", label: "Общий вопрос" },
] as const;

const STATUS_LABELS: Record<string, string> = {
  waiting_staff: "Ожидает ответа",
  waiting_customer: "Ответ получен",
  closed: "Закрыто",
};

const ACCEPT_IMAGES = "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp";
const ACCEPT_TYPES = new Set(["image/jpeg", "image/jpg", "image/png", "image/webp"]);
// Mirrors backend SUPPORT_ATTACHMENT_MAX_FILES default; API remains the source of truth.
const MAX_FILES = 10;

type PhotoUploadStatus = "idle" | "uploading" | "error";

function formatDateTime(raw: string) {
  const date = new Date(raw.includes("T") ? raw : `${raw}Z`);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function takeImageFiles(list: FileList | null): File[] {
  if (!list) return [];
  return Array.from(list).filter((file) => {
    const type = (file.type || "").toLowerCase();
    if (ACCEPT_TYPES.has(type)) return true;
    if (!type) return /\.(jpe?g|png|webp)$/i.test(file.name);
    return false;
  });
}

const COMPRESS_MAX_EDGE = 1920;
const COMPRESS_QUALITY = 0.82;

async function compressSupportPhoto(file: File): Promise<File> {
  if (typeof createImageBitmap !== "function") return file;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return file;
  }
  try {
    const scale = Math.min(1, COMPRESS_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", COMPRESS_QUALITY);
    });
    if (!blob) return file;
    const base = file.name.replace(/\.[^.]+$/, "") || "photo";
    return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
  } finally {
    bitmap.close();
  }
}

function PhotoPicker({
  inputRef,
  inputId,
  files,
  onChange,
  onLimitExceeded,
  onBusy,
  status,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  inputId: string;
  files: File[];
  onChange: (files: File[]) => void;
  onLimitExceeded: () => void;
  onBusy: (busy: boolean) => void;
  status: PhotoUploadStatus;
}) {
  const [previews, setPreviews] = useState<string[]>([]);
  const uploading = status === "uploading";
  const atLimit = files.length >= MAX_FILES;

  useEffect(() => {
    const urls = files.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);

  return (
    <div className="min-w-0 space-y-2">
      <input
        id={inputId}
        ref={inputRef}
        type="file"
        accept={ACCEPT_IMAGES}
        multiple
        className="sr-only"
        aria-label="Прикрепить фото"
        disabled={uploading}
        onChange={(e) => {
          const picked = takeImageFiles(e.target.files);
          e.target.value = "";
          if (files.length + picked.length > MAX_FILES) {
            onLimitExceeded();
            return;
          }
          return (async () => {
            onBusy(true);
            try {
              const compressed: File[] = [];
              for (const file of picked) {
                compressed.push(await compressSupportPhoto(file));
              }
              onChange([...files, ...compressed]);
            } finally {
              onBusy(false);
            }
          })();
        }}
      />
      <ul className="m-0 flex list-none flex-wrap gap-2.5 p-0">
        {files.map((file, index) => (
          <li
            key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
            className="relative size-20 shrink-0"
          >
            <div
              className={[
                "size-20 overflow-hidden rounded-2xl",
                status === "error" ? "ring-1 ring-red-300" : "",
              ].join(" ")}
            >
              {previews[index] ? (
                <img
                  src={previews[index]}
                  alt={`Фото ${index + 1}`}
                  className="size-20 object-cover"
                />
              ) : (
                <span className="block size-20 bg-sp-bg" />
              )}
              {uploading ? (
                <div className="absolute inset-0 rounded-2xl bg-black/30" aria-hidden="true" />
              ) : null}
            </div>
            {uploading ? null : (
              <button
                type="button"
                onClick={() => onChange(files.filter((_, i) => i !== index))}
                aria-label={`Удалить фото ${index + 1}`}
                className="absolute -right-1 -top-1 z-10 flex size-5 items-center justify-center rounded-full border border-sp-border bg-white text-[13px] leading-none text-sp-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sp-blue"
              >
                ×
              </button>
            )}
            {status === "error" ? (
              <span className="sr-only">Не удалось загрузить</span>
            ) : null}
          </li>
        ))}
        {atLimit ? null : (
          <li className="size-20 shrink-0">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
              aria-label={`Добавить фото, выбрано ${files.length} из ${MAX_FILES}`}
              className="flex size-20 flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-neutral-300 bg-transparent text-neutral-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sp-blue disabled:opacity-50"
            >
              <span className="text-[28px] leading-none" aria-hidden="true">
                +
              </span>
              <span className="text-[12px] leading-none text-neutral-400">
                {files.length}/{MAX_FILES}
              </span>
            </button>
          </li>
        )}
      </ul>
      {uploading ? (
        <div
          role="progressbar"
          aria-label="Загрузка фото"
          aria-valuetext="Загрузка"
          className="h-1.5 w-full overflow-hidden rounded-full bg-sp-border"
        >
          <div className="sp-support-liquid h-full w-1/3 rounded-full bg-sp-blue" />
        </div>
      ) : null}
    </div>
  );
}

export function SupportSection() {
  const [searchParams] = useSearchParams();
  const [tickets, setTickets] = useState<SupportTicketListItem[]>([]);
  const [linkableOrders, setLinkableOrders] = useState<LinkableOrder[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SupportTicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topic, setTopic] = useState<string>(TOPIC_OPTIONS[0].value);
  const [orderId, setOrderId] = useState<string>("");
  const [newBody, setNewBody] = useState("");
  const [newFiles, setNewFiles] = useState<File[]>([]);
  const [replyBody, setReplyBody] = useState("");
  const [replyFiles, setReplyFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [compressing, setCompressing] = useState(false);
  const [createStatus, setCreateStatus] = useState<PhotoUploadStatus>("idle");
  const [replyStatus, setReplyStatus] = useState<PhotoUploadStatus>("idle");
  const [ticketPage, setTicketPage] = useState(1);
  const [ticketTotalPages, setTicketTotalPages] = useState(1);
  const [attachmentUrls, setAttachmentUrls] = useState<Record<number, string>>({});
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const newFileRef = useRef<HTMLInputElement>(null);
  const replyFileRef = useRef<HTMLInputElement>(null);

  const loadTickets = useCallback(async (page = 1) => {
    setLoading(true);
    setError(null);
    try {
      const [list, orders] = await Promise.all([
        storefrontApiFetch<SupportTicketListPage>(
          `/support/tickets?page=${page}&page_size=20`,
        ),
        storefrontApiFetch<LinkableOrder[]>("/support/linkable-orders"),
      ]);
      setTickets(list.items);
      setTicketPage(list.page);
      setTicketTotalPages(list.total_pages);
      setLinkableOrders(orders);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить обращения");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (ticketId: number) => {
    setError(null);
    try {
      const data = await storefrontApiFetch<SupportTicketDetail>(`/support/tickets/${ticketId}`);
      setDetail(data);
      setSelectedId(ticketId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть обращение");
    }
  }, []);

  useEffect(() => {
    void loadTickets(1);
  }, [loadTickets]);

  useEffect(() => {
    const topicFromUrl = searchParams.get("topic");
    if (!topicFromUrl) return;
    const valid = TOPIC_OPTIONS.some((opt) => opt.value === topicFromUrl);
    if (valid) setTopic(topicFromUrl);
  }, [searchParams]);

  useEffect(() => {
    if (!detail) {
      setAttachmentUrls({});
      setPreviewUrl(null);
      return;
    }
    let cancelled = false;
    const created: string[] = [];
    async function loadBlobs() {
      const next: Record<number, string> = {};
      for (const msg of detail.messages) {
        for (const att of msg.attachments ?? []) {
          try {
            const blob = await storefrontApiFetchBlob(
              `/support/tickets/${detail.id}/attachments/${att.id}/file`,
            );
            if (cancelled) return;
            const url = URL.createObjectURL(blob);
            created.push(url);
            next[att.id] = url;
          } catch {
            /* broken attachment stays hidden */
          }
        }
      }
      if (!cancelled) setAttachmentUrls(next);
    }
    void loadBlobs();
    return () => {
      cancelled = true;
      created.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [detail]);

  useEffect(() => {
    if (!previewUrl) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewUrl(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewUrl]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const text = newBody.trim();
    if (!text && newFiles.length === 0) return;
    setSubmitting(true);
    setError(null);
    if (newFiles.length > 0) setCreateStatus("uploading");
    try {
      let created: SupportTicketDetail;
      if (newFiles.length > 0) {
        const form = new FormData();
        form.append("topic", topic);
        form.append("body", text);
        if (orderId) form.append("order_id", orderId);
        newFiles.forEach((file) => form.append("files", file));
        created = (await storefrontApiFetch<SupportTicketDetail>("/support/tickets", {
          method: "POST",
          body: form,
        })) as SupportTicketDetail;
      } else {
        created = (await storefrontApiFetch<SupportTicketDetail>("/support/tickets", {
          method: "POST",
          body: JSON.stringify({
            topic,
            body: text,
            order_id: orderId ? Number(orderId) : null,
          }),
        })) as SupportTicketDetail;
      }
      setNewBody("");
      setNewFiles([]);
      setCreateStatus("idle");
      if (newFileRef.current) newFileRef.current.value = "";
      setOrderId("");
      await loadTickets(ticketPage);
      await loadDetail(created.id);
    } catch (e) {
      setCreateStatus(newFiles.length > 0 ? "error" : "idle");
      setError(e instanceof Error ? e.message : "Не удалось создать обращение");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReply(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || detail?.status === "closed") return;
    const text = replyBody.trim();
    if (!text && replyFiles.length === 0) return;
    setSubmitting(true);
    setError(null);
    if (replyFiles.length > 0) setReplyStatus("uploading");
    try {
      let updated: SupportTicketDetail;
      if (replyFiles.length > 0) {
        const form = new FormData();
        form.append("body", text);
        replyFiles.forEach((file) => form.append("files", file));
        updated = (await storefrontApiFetch<SupportTicketDetail>(
          `/support/tickets/${selectedId}/messages`,
          { method: "POST", body: form },
        )) as SupportTicketDetail;
      } else {
        updated = (await storefrontApiFetch<SupportTicketDetail>(
          `/support/tickets/${selectedId}/messages`,
          {
            method: "POST",
            body: JSON.stringify({ body: text }),
          },
        )) as SupportTicketDetail;
      }
      setReplyBody("");
      setReplyFiles([]);
      setReplyStatus("idle");
      if (replyFileRef.current) replyFileRef.current.value = "";
      setDetail(updated);
      await loadTickets(ticketPage);
    } catch (e) {
      setReplyStatus(replyFiles.length > 0 ? "error" : "idle");
      setError(e instanceof Error ? e.message : "Не удалось отправить сообщение");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleClose() {
    if (!selectedId || detail?.status === "closed") return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await storefrontApiFetch<SupportTicketDetail>(
        `/support/tickets/${selectedId}/close`,
        { method: "POST" },
      );
      setDetail(updated);
      await loadTickets(ticketPage);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось закрыть обращение");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6 w-full min-w-0">
      <div>
        <h2 className="text-[20px] font-semibold mb-2 m-0 text-sp-text-primary">Поддержка</h2>
        <p className="text-[14px] text-sp-text-secondary m-0">
          Вопросы по заказам, доставке и товарам.
        </p>
      </div>

      {compressing ? (
        <p className="m-0 text-[13px] text-sp-text-secondary">Сжимаем фото…</p>
      ) : null}
      {error ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[14px] text-red-700">
          {error}
        </div>
      ) : null}

      <form onSubmit={(e) => void handleCreate(e)} className="space-y-3 rounded-[18px] border border-sp-border bg-sp-surface p-4">
        <h3 className="text-[15px] font-semibold m-0 text-sp-text-primary">Новое обращение</h3>
        <label className="block text-[13px] text-sp-text-secondary">
          Тема
          <select
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="mt-1 w-full rounded-xl border border-sp-border bg-sp-bg px-3 py-2 text-[14px]"
          >
            {TOPIC_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[13px] text-sp-text-secondary">
          Заказ (необязательно)
          <select
            value={orderId}
            onChange={(e) => setOrderId(e.target.value)}
            className="mt-1 w-full rounded-xl border border-sp-border bg-sp-bg px-3 py-2 text-[14px]"
          >
            <option value="">Без привязки к заказу</option>
            {linkableOrders.map((order) => (
              <option key={order.id} value={String(order.id)}>
                #{order.id} · {order.total_amount} ₽ · {order.status}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[13px] text-sp-text-secondary">
          Сообщение
          <textarea
            value={newBody}
            onChange={(e) => setNewBody(e.target.value)}
            rows={4}
            className="mt-1 w-full rounded-xl border border-sp-border bg-sp-bg px-3 py-2 text-[14px]"
            placeholder="Опишите вопрос или проблему"
          />
        </label>
        <PhotoPicker
          inputId="support-new-photos"
          inputRef={newFileRef}
          files={newFiles}
          onChange={(picked) => {
            setError(null);
            setCreateStatus("idle");
            setNewFiles(picked);
          }}
          onLimitExceeded={() =>
            setError(`Можно прикрепить не больше ${MAX_FILES} фото.`)
          }
          onBusy={setCompressing}
          status={createStatus}
        />
        <button
          type="submit"
          disabled={submitting || compressing}
          className="rounded-full bg-sp-blue px-5 py-2 text-[14px] font-medium text-white disabled:opacity-60"
        >
          Отправить
        </button>
      </form>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section className="rounded-[18px] border border-sp-border bg-sp-surface p-4">
          <h3 className="text-[15px] font-semibold m-0 mb-3 text-sp-text-primary">Мои обращения</h3>
          {loading ? (
            <p className="text-[14px] text-sp-text-muted">Загрузка…</p>
          ) : tickets.length === 0 ? (
            <p className="text-[14px] text-sp-text-muted">Обращений пока нет</p>
          ) : (
            <ul className="space-y-2 m-0 p-0 list-none">
              {tickets.map((ticket) => (
                <li key={ticket.id}>
                  <button
                    type="button"
                    onClick={() => void loadDetail(ticket.id)}
                    className={[
                      "w-full text-left rounded-xl border px-3 py-2 sp-transition",
                      selectedId === ticket.id
                        ? "border-sp-blue bg-sp-bg"
                        : "border-sp-border bg-transparent hover:bg-sp-bg",
                    ].join(" ")}
                  >
                    <div className="text-[14px] font-medium text-sp-text-primary">
                      #{ticket.id} · {ticket.topic_label}
                    </div>
                    <div className="text-[12px] text-sp-text-muted mt-0.5">
                      {STATUS_LABELS[ticket.status] || ticket.status}
                      {ticket.order_id ? ` · заказ #${ticket.order_id}` : ""}
                    </div>
                    {ticket.last_message_preview ? (
                      <div className="text-[12px] text-sp-text-secondary mt-1 line-clamp-2">
                        {ticket.last_message_preview}
                      </div>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {ticketTotalPages > 1 ? (
            <div className="mt-3 flex items-center justify-between gap-2 text-[13px] text-sp-text-muted">
              <button
                type="button"
                disabled={ticketPage <= 1 || loading}
                onClick={() => void loadTickets(ticketPage - 1)}
                className="rounded-full border border-sp-border px-3 py-1 disabled:opacity-50"
              >
                ←
              </button>
              <span>
                {ticketPage} / {ticketTotalPages}
              </span>
              <button
                type="button"
                disabled={ticketPage >= ticketTotalPages || loading}
                onClick={() => void loadTickets(ticketPage + 1)}
                className="rounded-full border border-sp-border px-3 py-1 disabled:opacity-50"
              >
                →
              </button>
            </div>
          ) : null}
        </section>

        <section className="rounded-[18px] border border-sp-border bg-sp-surface p-4 min-h-[240px]">
          {!detail ? (
            <div className="flex h-full min-h-[200px] items-center justify-center text-[14px] text-sp-text-muted">
              <MessageCircle className="mr-2 size-4" />
              Выберите обращение или создайте новое
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <h3 className="text-[15px] font-semibold m-0 text-sp-text-primary">
                  Обращение #{detail.id}
                </h3>
                <p className="text-[13px] text-sp-text-muted m-0 mt-1">
                  {detail.topic_label} · {STATUS_LABELS[detail.status] || detail.status}
                </p>
              </div>
              <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
                {detail.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={[
                      "rounded-xl px-3 py-2 text-[14px]",
                      msg.author_type === "staff"
                        ? "bg-sp-bg border border-sp-border"
                        : "bg-sp-blue/5 border border-sp-blue/20",
                    ].join(" ")}
                  >
                    <div className="text-[11px] text-sp-text-muted mb-1">
                      {msg.author_type === "staff" ? "Поддержка" : "Вы"} ·{" "}
                      {formatDateTime(msg.created_at)}
                    </div>
                    {msg.body ? (
                      <div className="whitespace-pre-wrap text-sp-text-primary">{msg.body}</div>
                    ) : null}
                    {(msg.attachments ?? []).length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(msg.attachments ?? []).map((att) =>
                          attachmentUrls[att.id] ? (
                            <button
                              key={att.id}
                              type="button"
                              onClick={() => setPreviewUrl(attachmentUrls[att.id])}
                              aria-label="Открыть фото"
                              className="block max-h-36 max-w-36 overflow-hidden rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sp-blue"
                            >
                              <img
                                src={attachmentUrls[att.id]}
                                alt=""
                                className="max-h-36 max-w-36 object-cover"
                              />
                            </button>
                          ) : null,
                        )}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              {detail.status !== "closed" ? (
                <form onSubmit={(e) => void handleReply(e)} className="space-y-2">
                  <textarea
                    value={replyBody}
                    onChange={(e) => setReplyBody(e.target.value)}
                    rows={3}
                    className="w-full rounded-xl border border-sp-border bg-sp-bg px-3 py-2 text-[14px]"
                    placeholder="Новое сообщение"
                  />
                  <PhotoPicker
                    inputId="support-reply-photos"
                    inputRef={replyFileRef}
                    files={replyFiles}
                    onChange={(picked) => {
                      setError(null);
                      setReplyStatus("idle");
                      setReplyFiles(picked);
                    }}
                    onLimitExceeded={() =>
                      setError(`Можно прикрепить не больше ${MAX_FILES} фото.`)
                    }
                    onBusy={setCompressing}
                    status={replyStatus}
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="submit"
                      disabled={submitting || compressing}
                      className="rounded-full bg-sp-blue px-4 py-2 text-[13px] font-medium text-white disabled:opacity-60"
                    >
                      Отправить
                    </button>
                    <button
                      type="button"
                      disabled={submitting || compressing}
                      onClick={() => void handleClose()}
                      className="rounded-full border border-sp-border px-4 py-2 text-[13px] text-sp-text-secondary disabled:opacity-60"
                    >
                      Закрыть обращение
                    </button>
                  </div>
                </form>
              ) : (
                <p className="text-[13px] text-sp-text-muted m-0">
                  Обращение закрыто. Чтобы задать новый вопрос — создайте новое обращение выше.
                </p>
              )}
            </div>
          )}
        </section>
      </div>
      {previewUrl ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Фото"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setPreviewUrl(null)}
        >
          <button
            type="button"
            aria-label="Закрыть фото"
            className="absolute right-4 top-4 rounded-full bg-white px-3 py-1.5 text-[13px] text-sp-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sp-blue"
            onClick={() => setPreviewUrl(null)}
          >
            Закрыть
          </button>
          <img
            src={previewUrl}
            alt="Фото в обращении"
            className="max-h-[90vh] max-w-full rounded-xl object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}
    </div>
  );
}
