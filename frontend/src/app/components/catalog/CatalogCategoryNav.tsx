import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { CatalogSubCategoryItem, CatalogTaxonomy } from "../../../lib/storefront/catalog";
import {
  pruneCatalogSubcategories,
  sportLabelFromTaxonomy,
  type SubCategorySlug,
} from "../../../lib/storefront/catalogCategoryFilter";
import {
  CATALOG_ALL_TOP,
  CATALOG_SPORTS,
  type CatalogSport,
  type CatalogTopScope,
} from "../../../lib/storefront/catalogNavigation";
import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";
import { labelSportType, type CatalogLabelsConfig } from "../../../lib/storefront/catalogLabels";

export type CatalogCategoryNavProps = {
  topCategory: CatalogTopScope | null;
  subCategories: CatalogSubCategoryItem[];
  subCategory: SubCategorySlug | "";
  productType: string;
  onCategorySelect: (subCategory: SubCategorySlug | "", productType: string) => void;
  onSportChange: (sport: CatalogSport | typeof CATALOG_ALL_TOP) => void;
  catalogLabels: CatalogLabelsConfig | null;
  catalogTaxonomy?: CatalogTaxonomy | null;
  onSubcategoryHover: (sub: SubCategorySlug) => void;
  /** miniapp — горизонтальные pill-фильтры вместо hover-меню */
  variant?: "default" | "miniapp";
};

function sportLabel(
  sport: CatalogSport,
  taxonomy: CatalogTaxonomy | null | undefined,
  labels: CatalogLabelsConfig,
): string {
  return sportLabelFromTaxonomy(taxonomy, sport) || labelSportType(labels, sport);
}

function sportTabClass(active: boolean): string {
  const base = "text-[13px] uppercase tracking-[0.12em] sp-transition whitespace-nowrap";
  return active
    ? `${base} font-bold text-sp-text-primary`
    : `${base} font-medium text-sp-text-muted hover:text-sp-text-primary`;
}

function subTabClass(active: boolean): string {
  const base =
    "text-[14px] font-medium pb-2 border-b-2 sp-transition whitespace-nowrap outline-none";
  return active
    ? `${base} text-sp-text-primary border-sp-text-primary`
    : `${base} text-sp-text-muted border-transparent hover:text-sp-text-primary`;
}

// Горизонтальная лента pill-фильтров для свайпа.
function MiniappPillStrip({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-2 overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {children}
    </div>
  );
}

const catalogSubMenuItemClass =
  "block w-full px-3 py-2 text-left text-[14px] font-medium sp-transition text-sp-text-primary rounded-lg hover:bg-sp-blue hover:text-white hover:rounded-[var(--sp-radius-pill)]";

// Подсветка выбранного типа в desktop submenu.
function catalogSubMenuItemActiveClass(active: boolean): string {
  return active ? `${catalogSubMenuItemClass} catalog-sub-menu-item--active` : catalogSubMenuItemClass;
}

const SUBMENU_VIEWPORT_BOTTOM_GAP_PX = 24;
const SUBMENU_MAX_HEIGHT_CAP_PX = 560;
const SUBMENU_MIN_HEIGHT_PX = 120;

// Ограничивает высоту submenu по фактической позиции panel во viewport.
function applySubMenuMaxHeight(panel: HTMLElement) {
  const panelTop = panel.getBoundingClientRect().top;
  const available = Math.floor(window.innerHeight - panelTop - SUBMENU_VIEWPORT_BOTTOM_GAP_PX);
  const maxHeight = Math.max(
    SUBMENU_MIN_HEIGHT_PX,
    Math.min(SUBMENU_MAX_HEIGHT_CAP_PX, available),
  );
  panel.style.setProperty("--catalog-submenu-max-height", `${maxHeight}px`);
  void panel.offsetHeight;
}

// Обновляет fade-hint при прокрутке длинного submenu.
function updateSubMenuScrollHints(panel: HTMLElement) {
  const scrollable = panel.scrollHeight > panel.clientHeight + 2;
  const fadeTop = panel.scrollTop > 4;
  const fadeBottom = panel.scrollTop + panel.clientHeight < panel.scrollHeight - 4;
  panel.classList.toggle("catalog-sub-menu-panel--scrollable", scrollable);
  panel.classList.toggle("catalog-sub-menu-panel--fade-top", scrollable && fadeTop);
  panel.classList.toggle("catalog-sub-menu-panel--fade-bottom", scrollable && fadeBottom);
}

// max-height + fade-hints без сброса scrollTop.
function layoutSubMenuPanel(panel: HTMLElement) {
  applySubMenuMaxHeight(panel);
  updateSubMenuScrollHints(panel);
}

// Прокручивает panel к выбранному типу (работает и до открытия hover-menu).
function scrollActiveTypeIntoView(panel: HTMLElement, productType: string) {
  if (!productType) {
    panel.scrollTop = 0;
    return;
  }
  const activeEl = panel.querySelector<HTMLElement>(
    `[data-catalog-type="${CSS.escape(productType)}"]`,
  );
  if (!activeEl) return;
  const elTop = activeEl.offsetTop;
  const elBottom = elTop + activeEl.offsetHeight;
  if (elBottom > panel.scrollTop + panel.clientHeight) {
    panel.scrollTop = elBottom - panel.clientHeight;
  } else if (elTop < panel.scrollTop) {
    panel.scrollTop = elTop;
  }
}

type SubHoverTabProps = {
  sub: CatalogSubCategoryItem;
  isActive: boolean;
  productType: string;
  onCategorySelect: (sub: SubCategorySlug, type: string) => void;
  onSubcategoryHover: (sub: SubCategorySlug) => void;
};

function SubHoverTab({
  sub,
  isActive,
  productType,
  onCategorySelect,
  onSubcategoryHover,
}: SubHoverTabProps) {
  const slug = sub.slug as SubCategorySlug;
  const panelRef = useRef<HTMLLIElement>(null);
  const [hovered, setHovered] = useState(false);
  const userScrolledRef = useRef(false);
  const hasTypes = sub.types.length > 1;
  const typesKey = sub.types.map((type) => type.key).join("|");

  useLayoutEffect(() => {
    userScrolledRef.current = false;
  }, [productType, typesKey]);

  const scrollActiveIfNeeded = useCallback(
    (panel: HTMLElement) => {
      if (!isActive || !productType || userScrolledRef.current) return;
      scrollActiveTypeIntoView(panel, productType);
      updateSubMenuScrollHints(panel);
    },
    [isActive, productType],
  );

  const handleMouseEnter = useCallback(() => {
    setHovered(true);
    onSubcategoryHover(slug);
    const panel = panelRef.current;
    if (!panel) return;
    layoutSubMenuPanel(panel);
    scrollActiveIfNeeded(panel);
  }, [onSubcategoryHover, scrollActiveIfNeeded, slug]);

  useLayoutEffect(() => {
    if (!isActive) return;
    const panel = panelRef.current;
    if (!panel) return;
    layoutSubMenuPanel(panel);
    scrollActiveTypeIntoView(panel, productType);
    updateSubMenuScrollHints(panel);
  }, [isActive, productType, typesKey]);

  useLayoutEffect(() => {
    if (!isActive && !hovered) return;
    const panel = panelRef.current;
    if (!panel) return;
    const onViewportChange = (event: Event) => {
      if (event.type === "scroll" && (event.target === panel || panel.contains(event.target as Node))) {
        return;
      }
      layoutSubMenuPanel(panel);
    };
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [hovered, isActive]);

  const handlePanelScroll = useCallback(() => {
    userScrolledRef.current = true;
    const panel = panelRef.current;
    if (panel) updateSubMenuScrollHints(panel);
  }, []);

  if (!hasTypes) {
    return (
      <li className="catalog-menu-item">
        <button
          type="button"
          className={subTabClass(isActive)}
          onClick={() => onCategorySelect(slug, "")}
        >
          {sub.label}
        </button>
      </li>
    );
  }

  return (
    <li
      className="catalog-menu-item"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className={subTabClass(isActive)}
        onClick={() => onCategorySelect(slug, "")}
      >
        {sub.label}
      </button>
      <ul className="catalog-sub-menu" role="menu">
        <li
          ref={panelRef}
          className="catalog-sub-menu-panel"
          role="none"
          onScroll={handlePanelScroll}
        >
          <button
            type="button"
            role="menuitem"
            className={catalogSubMenuItemActiveClass(isActive && !productType)}
            aria-current={isActive && !productType ? "true" : undefined}
            onClick={() => onCategorySelect(slug, "")}
          >
            Все
          </button>
          {sub.types.map((type) => {
            const typeActive = isActive && productType === type.key;
            return (
              <button
                key={type.key}
                type="button"
                role="menuitem"
                data-catalog-type={type.key}
                className={catalogSubMenuItemActiveClass(typeActive)}
                aria-current={typeActive ? "true" : undefined}
                onClick={() => onCategorySelect(slug, type.key)}
              >
                {type.label_ru}
              </button>
            );
          })}
        </li>
      </ul>
    </li>
  );
}

function MiniappSubPills({
  subCategories,
  subCategory,
  productType,
  onCategorySelect,
  onSubcategoryPrefetch,
}: {
  subCategories: CatalogSubCategoryItem[];
  subCategory: SubCategorySlug | "";
  productType: string;
  onCategorySelect: (sub: SubCategorySlug | "", type: string) => void;
  onSubcategoryPrefetch?: (sub: SubCategorySlug) => void;
}) {
  const activeSub = subCategories.find((s) => s.slug === subCategory);

  return (
    <div className="space-y-2">
      <MiniappPillStrip>
        {subCategories.map((sub) => {
          const slug = sub.slug as SubCategorySlug;
          const isActive = subCategory === slug;
          return (
            <button
              key={sub.slug}
              type="button"
              className={`shrink-0 ${miniAppPillClass(isActive)}`}
              onPointerDown={() => onSubcategoryPrefetch?.(slug)}
              onClick={() => onCategorySelect(slug, "")}
            >
              {sub.label}
            </button>
          );
        })}
      </MiniappPillStrip>
      {activeSub && activeSub.types.length > 1 ? (
        <MiniappPillStrip>
          <button
            type="button"
            className={`shrink-0 ${miniAppPillClass(!productType)}`}
            onClick={() => onCategorySelect(subCategory, "")}
          >
            Все
          </button>
          {activeSub.types.map((type) => (
            <button
              key={type.key}
              type="button"
              className={`shrink-0 ${miniAppPillClass(productType === type.key)}`}
              onClick={() => onCategorySelect(subCategory, type.key)}
            >
              {type.label_ru}
            </button>
          ))}
        </MiniappPillStrip>
      ) : null}
    </div>
  );
}

export function CatalogCategoryNav({
  topCategory,
  subCategories,
  subCategory,
  productType,
  onCategorySelect,
  onSportChange,
  onSubcategoryHover,
  catalogLabels,
  catalogTaxonomy = null,
  variant = "default",
}: CatalogCategoryNavProps) {
  const labels =
    catalogLabels ??
    ({
      sport_types: { Padel: "Падел", Tennis: "Теннис", Running: "Бег" },
      category_l2: {},
      genders: {},
      filter_all: "Все",
      product_fallback: "Товар",
    } satisfies CatalogLabelsConfig);

  const isAllView = topCategory === CATALOG_ALL_TOP;
  const activeSport =
    topCategory && CATALOG_SPORTS.includes(topCategory as CatalogSport)
      ? (topCategory as CatalogSport)
      : null;

  const availableSubCategories = pruneCatalogSubcategories(subCategories);

  if (!isAllView && !activeSport) return null;

  if (variant === "miniapp") {
    return (
      <div className="mb-4">
        {isAllView ? (
          <MiniappPillStrip>
            {CATALOG_SPORTS.map((sport) => (
              <button
                key={sport}
                type="button"
                className={`shrink-0 ${miniAppPillClass(false)}`}
                onClick={() => onSportChange(sport)}
              >
                {sportLabel(sport, catalogTaxonomy, labels)}
              </button>
            ))}
          </MiniappPillStrip>
        ) : (
          <MiniappSubPills
            subCategories={availableSubCategories}
            subCategory={subCategory}
            productType={productType}
            onCategorySelect={onCategorySelect}
            onSubcategoryPrefetch={onSubcategoryHover}
          />
        )}
      </div>
    );
  }

  return (
    <div className="mb-6 border-b border-sp-border pb-3">
      {isAllView ? (
        <div className="flex items-center gap-6 flex-wrap">
          {CATALOG_SPORTS.map((sport) => (
            <button
              key={sport}
              type="button"
              className={sportTabClass(false)}
              onClick={() => onSportChange(sport)}
            >
              {sportLabel(sport, catalogTaxonomy, labels)}
            </button>
          ))}
        </div>
      ) : (
        <nav className="catalog-main-menu" aria-label="Подкатегории">
          <ul className="flex items-center gap-6 flex-wrap">
            {subCategories.map((sub) => (
              <SubHoverTab
                key={sub.slug}
                sub={sub}
                isActive={subCategory === sub.slug}
                productType={subCategory === sub.slug ? productType : ""}
                onCategorySelect={onCategorySelect}
                onSubcategoryHover={onSubcategoryHover}
              />
            ))}
          </ul>
        </nav>
      )}
    </div>
  );
}
