import { FileText, ShieldCheck } from "lucide-react";
import { openStoreLegal } from "../../../lib/storefront/legal";

const itemClass =
  "flex items-center gap-3 px-5 py-4 w-full text-left bg-transparent border-0 cursor-pointer sp-transition hover:bg-sp-bg";

const titleClass = "text-[14px] font-medium";
const subtitleClass = "text-[12px] text-sp-text-muted";

export function AccountLegalSection() {
  return (
    <div className="mt-6">
      <h3
        className="text-[16px] font-semibold mb-3 m-0"
        style={{ color: "var(--sp-text-primary)" }}
      >
        Правовая информация
      </h3>
      <div
        style={{
          background: "var(--sp-surface)",
          border: "1px solid var(--sp-border)",
          borderRadius: "18px",
          overflow: "hidden",
        }}
      >
        <button
          type="button"
          className={itemClass}
          onClick={() => openStoreLegal("/terms", "Публичная оферта")}
          style={{ borderBottom: "1px solid var(--sp-border)" }}
        >
          <FileText size={18} style={{ color: "var(--sp-text-muted)" }} />
          <div className="min-w-0 flex-1">
            <div className={titleClass} style={{ color: "var(--sp-text-primary)" }}>
              Договор-оферта
            </div>
            <div className={subtitleClass}>
              Условия покупки, доставки и возврата
            </div>
          </div>
        </button>
        <button
          type="button"
          className={itemClass}
          onClick={() => openStoreLegal("/privacy", "Политика конфиденциальности")}
        >
          <ShieldCheck size={18} style={{ color: "var(--sp-text-muted)" }} />
          <div className="min-w-0 flex-1">
            <div className={titleClass} style={{ color: "var(--sp-text-primary)" }}>
              Политика конфиденциальности
            </div>
            <div className={subtitleClass}>
              Обработка персональных данных
            </div>
          </div>
        </button>
      </div>
    </div>
  );
}
