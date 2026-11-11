import { ChevronDown } from "lucide-react";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import type { CatalogSubCategoryItem } from "../../../lib/storefront/catalog";
import { pruneCatalogSubcategories, type SubCategorySlug } from "../../../lib/storefront/catalogCategoryFilter";

export type CatalogCategoryDropdownProps = {
  subCategories: CatalogSubCategoryItem[];
  subCategory: SubCategorySlug | "";
  productType: string;
  onSelect: (subCategory: SubCategorySlug | "", productType: string) => void;
  allLabel?: string;
  placeholder?: string;
  className?: string;
};

function resolveTriggerLabel(
  subCategories: CatalogSubCategoryItem[],
  subCategory: SubCategorySlug | "",
  productType: string,
  allLabel: string,
  placeholder: string,
): string {
  if (!subCategory) return placeholder;
  const sub = subCategories.find((item) => item.slug === subCategory);
  if (!sub) return placeholder;
  if (!productType) return sub.label;
  const type = sub.types.find((item) => item.key === productType);
  return type ? `${sub.label} · ${type.label_ru}` : sub.label;
}

export function CatalogCategoryDropdown({
  subCategories,
  subCategory,
  productType,
  onSelect,
  allLabel = "Все товары",
  placeholder = "Категория",
  className = "w-full max-w-sm",
}: CatalogCategoryDropdownProps) {
  const availableSubCategories = pruneCatalogSubcategories(subCategories);
  if (!availableSubCategories.length) return null;

  const triggerLabel = resolveTriggerLabel(
    availableSubCategories,
    subCategory,
    productType,
    allLabel,
    placeholder,
  );

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={`${className} h-11 justify-between rounded-xl border-sp-border bg-white text-sp-text-primary text-[14px] font-normal shadow-none hover:border-sp-blue hover:bg-white`}
        >
          <span className="truncate">{triggerLabel}</span>
          <ChevronDown className="ms-2 size-4 shrink-0 opacity-60" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={6}
        className="z-[120] min-w-[var(--radix-dropdown-menu-trigger-width)] rounded-xl border-sp-border bg-white p-1 text-sp-text-primary shadow-[var(--sp-shadow-soft)]"
      >
        <DropdownMenuItem
          className="rounded-lg text-[14px] cursor-pointer"
          onSelect={() => onSelect("", "")}
        >
          {allLabel}
        </DropdownMenuItem>

        {availableSubCategories.map((sub) =>
          sub.types.length > 1 ? (
            <DropdownMenuSub key={sub.slug}>
              <DropdownMenuSubTrigger className="rounded-lg text-[14px] cursor-pointer">
                {sub.label}
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="z-[120] rounded-xl border-sp-border bg-white p-1 shadow-[var(--sp-shadow-soft)]">
                <DropdownMenuItem
                  className="rounded-lg text-[14px] cursor-pointer"
                  onSelect={() => onSelect(sub.slug as SubCategorySlug, "")}
                >
                  Все
                </DropdownMenuItem>
                {sub.types.map((type) => (
                  <DropdownMenuItem
                    key={type.key}
                    className="rounded-lg text-[14px] cursor-pointer"
                    onSelect={() => onSelect(sub.slug as SubCategorySlug, type.key)}
                  >
                    {type.label_ru}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          ) : (
            <DropdownMenuItem
              key={sub.slug}
              className="rounded-lg text-[14px] cursor-pointer"
              onSelect={() =>
                onSelect(
                  sub.slug as SubCategorySlug,
                  sub.types[0]?.key ?? "",
                )
              }
            >
              {sub.label}
            </DropdownMenuItem>
          ),
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
