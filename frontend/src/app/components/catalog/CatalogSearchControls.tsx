import { miniAppInputClass, miniAppPillClass } from "../../../lib/storefront/miniAppUi";

export type CatalogMiniAppSearchBarProps = {
  searchQ: string;
  onSubmitSearch: (raw: string) => void;
  onClearSearch: () => void;
};

export function CatalogMiniAppSearchBar({
  searchQ,
  onSubmitSearch,
  onClearSearch,
}: CatalogMiniAppSearchBarProps) {
  return (
    <form
      className="mb-3 flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        onSubmitSearch(String(fd.get("q") ?? ""));
      }}
    >
      <input
        name="q"
        type="search"
        key={searchQ}
        defaultValue={searchQ}
        placeholder="Поиск: бренд, название…"
        className={miniAppInputClass()}
      />
      {searchQ.trim() ? (
        <button
          type="button"
          onClick={onClearSearch}
          className={miniAppPillClass(false)}
          aria-label="Сбросить поиск"
        >
          ✕
        </button>
      ) : null}
    </form>
  );
}

export type CatalogSearchBannerProps = {
  compact: boolean;
  searchQ: string;
  onClearSearch: () => void;
};

export function CatalogSearchBanner({ compact, searchQ, onClearSearch }: CatalogSearchBannerProps) {
  if (!searchQ.trim()) return null;

  return (
    <div className={`mb-3 flex flex-wrap items-center gap-2 ${compact ? "text-[12px]" : ""}`}>
      <span className={compact ? "text-sp-text-secondary" : "text-[14px] text-sp-text-secondary"}>
        Поиск: <strong className="text-sp-text-primary">{searchQ.trim()}</strong>
      </span>
      <button
        type="button"
        onClick={onClearSearch}
        className={
          compact
            ? miniAppPillClass(true)
            : "inline-flex items-center gap-1 rounded-full border border-sp-border bg-sp-surface px-3 py-1.5 text-[13px] font-medium text-sp-blue sp-transition hover:border-sp-blue"
        }
      >
        ✕ Сбросить
      </button>
    </div>
  );
}
