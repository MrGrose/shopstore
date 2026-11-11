import { Link } from "react-router";

const legalLinkClass =
  "text-[11px] no-underline sp-transition hover:text-sp-text-primary text-sp-text-secondary";

export function MobileLegalFooter() {
  return (
    <section
      className="mt-auto w-full shrink-0 border-t border-sp-border bg-sp-surface px-4 py-3"
      aria-label="Правовая информация"
    >
      <div className="mx-auto flex max-w-lg flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[11px] text-sp-text-secondary">
        <span className="font-semibold uppercase tracking-[0.08em] text-sp-text-muted">
          Правовая информация:
        </span>
        <Link to="/terms" className={legalLinkClass}>
          Договор-оферта
        </Link>
        <span className="text-sp-border select-none" aria-hidden>
          ·
        </span>
        <Link to="/privacy" className={legalLinkClass}>
          Политика конфиденциальности
        </Link>
      </div>
    </section>
  );
}
