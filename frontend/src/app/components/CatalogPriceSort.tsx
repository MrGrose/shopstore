import { CatalogFilterSectionShell } from "./CatalogFilterSectionShell";
import { usePersistedFilterSection } from "../../lib/storefront/usePersistedFilterSection";

export type SortPrice = "" | "asc" | "desc";

const SORT_OPTIONS = [
  { value: "asc" as const, label: "Недорогие" },
  { value: "desc" as const, label: "Дорогие" },
];

export function CatalogPriceSort({
  sortPrice,
  onSortPriceChange,
  resetToken = "",
}: {
  sortPrice: SortPrice;
  onSortPriceChange: (value: SortPrice) => void;
  resetToken?: string;
}) {
  const { open, toggle, setOpen } = usePersistedFilterSection("sort", resetToken);

  const handleSortChange = (value: SortPrice) => {
    onSortPriceChange(value);
    if (value) setOpen(true);
  };

  return (
    <CatalogFilterSectionShell title="По цене" open={open} onToggle={toggle}>
      <div className="space-y-2">
        {SORT_OPTIONS.map(({ value, label }) => (
          <label key={value} className="flex items-center gap-2 group cursor-pointer">
            <input
              type="checkbox"
              checked={sortPrice === value}
              onChange={() => handleSortChange(sortPrice === value ? "" : value)}
              className="w-4 h-4 sp-transition cursor-pointer"
              style={{ accentColor: "var(--sp-blue)" }}
            />
            <span className="text-[14px] text-sp-text-primary group-hover:opacity-70 sp-transition">
              {label}
            </span>
          </label>
        ))}
      </div>
    </CatalogFilterSectionShell>
  );
}
