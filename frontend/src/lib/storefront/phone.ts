const PHONE_MSG = "Укажите российский мобильный номер (+79991234567)";

export function normalizeRuMobilePhone(value: string): string | null {
  const digits = String(value || "").replace(/\D/g, "");
  let normalized = digits;
  if (normalized.length === 11 && normalized.startsWith("8")) {
    normalized = `7${normalized.slice(1)}`;
  } else if (normalized.length === 10) {
    normalized = `7${normalized}`;
  }
  if (normalized.length !== 11 || !normalized.startsWith("79")) {
    return null;
  }
  return `+${normalized}`;
}

export function validateRuMobilePhone(value: string): string | null {
  return normalizeRuMobilePhone(value) ? null : PHONE_MSG;
}
