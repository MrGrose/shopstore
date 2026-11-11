export type CatalogSectionHeaderProps = {
  eyebrow: string;
  title: string;
};

export function CatalogSectionHeader({ eyebrow, title }: CatalogSectionHeaderProps) {
  return (
    <div className="mb-10">
      <div className="text-[11px] font-semibold tracking-[0.1em] uppercase text-sp-text-muted mb-2">
        {eyebrow}
      </div>
      <h2 className="text-[40px] font-semibold text-sp-text-primary leading-tight tracking-tight">
        {title}
      </h2>
    </div>
  );
}
