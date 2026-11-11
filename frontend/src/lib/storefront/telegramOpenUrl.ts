/** t.me deep link для открытия Mini App в Telegram, не HTTPS WebApp URL в браузере. */
export function resolveTelegramOpenUrl(telegramUrl: string): string {
  const raw = telegramUrl.trim();
  if (!raw) return "";

  try {
    const url = new URL(raw);
    const host = url.hostname.toLowerCase();

    if (host.endsWith(".telegram.me")) {
      const bot = host.slice(0, -".telegram.me".length);
      const segments = url.pathname.replace(/^\/+|\/+$/g, "").split("/");
      const short = segments.filter(Boolean).pop() || "app";
      return `https://t.me/${bot}/${short}`;
    }

    if (host === "t.me" || host === "telegram.me" || host === "www.t.me") {
      const path = url.pathname.replace(/^\/+|\/+$/g, "");
      return path ? `https://t.me/${path}` : raw;
    }
  } catch {
    return raw;
  }

  return raw;
}
