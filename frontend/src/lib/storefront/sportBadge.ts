const SPORT_BADGE_COLORS: Record<string, { text: string; pillBg: string; cardBg: string }> = {
  Tennis: { text: "text-sp-warm", pillBg: "bg-sp-warm-soft", cardBg: "bg-sp-warm-soft-md" },
  Padel: { text: "text-sp-green", pillBg: "bg-sp-green-soft", cardBg: "bg-sp-green-soft-md" },
  Running: { text: "text-sp-cyan", pillBg: "bg-sp-cyan-soft", cardBg: "bg-sp-cyan-soft-md" },
};

export function resolveSportCategory(input: {
  sport_type?: string | null;
  sport_type_label_ru?: string | null;
  category_l1?: string | null;
  category_l2?: string | null;
  category_l3?: string | null;
}): string {
  const raw = (input.sport_type || input.category_l1 || input.category_l2 || input.category_l3 || "").trim();
  if (raw) {
    const v = raw.toLowerCase();
    if (v.includes("padel")) return "Padel";
    if (v.includes("tennis")) return "Tennis";
    if (v.includes("running")) return "Running";
    return raw;
  }
  const label = (input.sport_type_label_ru || "").trim().toLowerCase();
  if (label.includes("padel") || label.includes("падел")) return "Padel";
  if (label.includes("tennis") || label.includes("теннис")) return "Tennis";
  if (label.includes("running") || label.includes("бег")) return "Running";
  return "Product";
}

function sportBadgeColors(category: string, variant: "card" | "pill") {
  const colors = SPORT_BADGE_COLORS[category];
  if (!colors) {
    return variant === "pill"
      ? { text: "text-sp-cyan", pillBg: "bg-sp-cyan-soft", cardBg: "bg-sp-cyan-soft-md" }
      : { text: "text-white", pillBg: "bg-black/20", cardBg: "bg-black/20" };
  }
  return colors;
}

/** Бейдж на карточке каталога — заливка 15% + blur как раньше. */
export function sportBadgeCardClass(category: string, compact = false): string {
  const { text, cardBg } = sportBadgeColors(category, "card");
  const base = compact
    ? "absolute top-2 left-2 px-2 py-0.5 text-[9px] font-semibold leading-none tracking-[0.07em] uppercase rounded backdrop-blur-sm"
    : "absolute top-2.5 left-2.5 px-2.5 py-1 text-[10px] font-semibold leading-none tracking-[0.08em] uppercase rounded backdrop-blur-sm";
  return `${base} ${cardBg} ${text}`;
}

/** Бейдж на PDP — pill, заливка 10% как было у cyan. */
export function sportBadgePillClass(category: string, compact = false): string {
  const { text, pillBg } = sportBadgeColors(category, "pill");
  const size = compact ? "px-2.5 py-1 text-[10px]" : "px-3 py-1.5 text-[11px]";
  return `rounded-full ${pillBg} font-semibold uppercase tracking-[0.1em] ${text} ${size}`;
}
