import type { StorefrontUser } from "./session";

export function userInitials(name?: string | null) {
  const parts = (name || "А").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return (parts[0]?.slice(0, 2) || "А").toUpperCase();
}

export function accountDisplayLabel(user: StorefrontUser | null | undefined) {
  if (user?.name?.trim()) return user.name.trim();
  const tg = user?.identities?.find((item) => item.provider === "telegram");
  if (tg?.telegram_username) return `@${tg.telegram_username}`;
  if (user?.telegram_username) return `@${user.telegram_username}`;
  if (user?.telegram_id) return `Telegram id ${user.telegram_id}`;
  return "Кабинет";
}
