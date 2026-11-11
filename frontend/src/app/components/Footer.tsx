import { Link } from "react-router";
import { openStoreCompany } from "../../lib/storefront/company";

const footerLinkClass =
  "text-[11px] hover:underline bg-transparent border-0 p-0 cursor-pointer text-sp-text-secondary sp-transition hover:text-sp-text-primary";

const legalLinkClass =
  "text-[11px] no-underline sp-transition hover:text-sp-text-primary text-sp-text-secondary";

export function Footer() {
  return (
    <footer
      id="footer"
      className="shrink-0 py-2.5 px-6 bg-sp-surface border-t border-sp-border"
    >
      <div className="max-w-[1400px] mx-auto flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[11px] text-sp-text-secondary">
        <span>© 2026 SHOPSTORE. Все права защищены.</span>
        <span className="text-sp-border select-none" aria-hidden>
          ·
        </span>
        <nav className="flex items-center gap-4" aria-label="Правовая информация">
          <button type="button" className={footerLinkClass} onClick={() => openStoreCompany()}>
            О нас
          </button>
          <Link to="/terms" className={legalLinkClass}>
            Договор-оферта
          </Link>
          <Link to="/privacy" className={legalLinkClass}>
            Политика конфиденциальности
          </Link>
        </nav>
      </div>
    </footer>
  );
}
