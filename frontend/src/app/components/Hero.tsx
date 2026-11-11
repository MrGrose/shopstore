import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Link } from "react-router";
import { catalogAllPath, catalogSportPath } from "../../lib/storefront/catalogNavigation";
import { useCatalogReferencePrefetch } from "../../lib/storefront/prefetchCatalogReference";
import { useStorefrontCompact } from "../../lib/storefront/useStorefrontSurface";

// CDN: локальные /hero/* в git не попадают (*.png в .gitignore).
const categoryChips = [
  { label: "Каталог", to: catalogAllPath() },
  { label: "Падел", to: catalogSportPath("Padel") },
  { label: "Теннис", to: catalogSportPath("Tennis") },
  { label: "Бег", to: catalogSportPath("Running") },
];

const heroImages = [
  {
    id: "brand",
    url: "https://images.unsplash.com/photo-1689942963385-f5bd03f3b270?auto=format&fit=crop&w=1600&q=80",
    titleLead: "ИГРАЙ",
    titleAccent: "БЕЗ",
    titleRest: "ПРЕДЕЛОВ.",
    subtitle:
      "Премиальная экипировка для падела, тенниса и бега. Создана для результата и лидерства.",
    productsTo: catalogAllPath(),
  },
  {
    id: "padel",
    url: "https://images.unsplash.com/photo-1689942963385-f5bd03f3b270?auto=format&fit=crop&w=1600&q=80",
    title: "Падел",
    subtitle: "Спорт, который выбирают первым.",
    productsTo: catalogSportPath("Padel"),
  },
  {
    id: "tennis",
    url: "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?auto=format&fit=crop&w=1600&q=80",
    title: "Теннис",
    subtitle: "Когда стиль встречает характер.",
    productsTo: catalogSportPath("Tennis"),
  },
  {
    id: "running",
    url: "https://images.unsplash.com/photo-1571008887538-b36bb32f4571?auto=format&fit=crop&w=1600&q=80",
    title: "Бег",
    subtitle: "Беги туда, где заканчиваются пределы.",
    productsTo: catalogSportPath("Running"),
  },
];

export function Hero() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const compact = useStorefrontCompact();
  const prefetchCatalogReference = useCatalogReferencePrefetch();

  useEffect(() => {
    const interval = window.setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % heroImages.length);
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  const currentHero = heroImages[currentIndex]!;

  return (
    <section className="relative h-full min-h-0 overflow-hidden">
      {heroImages.map((hero, index) => (
        <motion.div
          key={hero.id}
          className="absolute inset-0"
          initial={{ opacity: 0 }}
          animate={{ opacity: index === currentIndex ? 1 : 0 }}
          transition={{ duration: 1 }}
        >
          <div
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${hero.url})` }}
          />
          <div
            className="absolute inset-0"
            style={{
              background: "linear-gradient(180deg, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.5) 100%)",
            }}
          />
        </motion.div>
      ))}

      <div className="relative z-10 h-full flex flex-col items-center justify-center text-center px-6">
        <motion.div
          key={currentIndex}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="space-y-6"
        >
          <h1 className="text-[48px] sm:text-[64px] md:text-[80px] lg:text-[96px] leading-[0.95] tracking-tight font-semibold text-white m-0 max-w-[18ch] md:max-w-none mx-auto">
            {"titleAccent" in currentHero ? (
              <>
                {currentHero.titleLead}{" "}
                <span style={{ color: "var(--sp-cyan)" }}>{currentHero.titleAccent}</span>{" "}
                {currentHero.titleRest}
              </>
            ) : (
              currentHero.title
            )}
          </h1>

          <p
            className="text-[17px] md:text-[22px] lg:text-[24px] m-0 max-w-[42rem] mx-auto leading-snug"
            style={{ color: "rgba(255,255,255,0.9)" }}
          >
            {currentHero.subtitle}
          </p>

          <div className="flex justify-center pt-6">
            <Link
              to={currentHero.productsTo}
              onMouseEnter={prefetchCatalogReference}
              onFocus={prefetchCatalogReference}
              className="px-8 py-4 text-[16px] font-medium sp-transition no-underline"
              style={{
                background: "rgba(255, 255, 255, 0.2)",
                color: "#FFFFFF",
                borderRadius: "var(--sp-radius-pill)",
                backdropFilter: "blur(10px)",
              }}
            >
              Открыть товары
            </Link>
          </div>
        </motion.div>
      </div>

      <div
        className={
          compact
            ? "absolute inset-x-0 bottom-4 z-20 flex flex-wrap justify-center gap-2 px-4"
            : "absolute bottom-8 left-6 md:left-8 z-20 flex flex-wrap gap-2 max-w-[min(100%,28rem)]"
        }
      >
        {categoryChips.map((chip) => (
          <Link
            key={chip.to}
            to={chip.to}
            onMouseEnter={prefetchCatalogReference}
            onFocus={prefetchCatalogReference}
            className="px-4 py-2 text-[13px] font-medium sp-transition hover:opacity-90 no-underline"
            style={{
              background: "rgba(255, 255, 255, 0.2)",
              color: "#FFFFFF",
              borderRadius: "var(--sp-radius-pill)",
              backdropFilter: "blur(10px)",
            }}
          >
            {chip.label}
          </Link>
        ))}
      </div>

      {!compact ? (
      <div className="absolute bottom-12 left-1/2 -translate-x-1/2 flex gap-2 z-20">
        {heroImages.map((_, index) => (
          <button
            key={index}
            type="button"
            aria-label={`Слайд ${index + 1}`}
            onClick={() => setCurrentIndex(index)}
            className="w-2 h-2 rounded-full sp-transition"
            style={{
              background: index === currentIndex ? "#FFFFFF" : "rgba(255, 255, 255, 0.4)",
            }}
          />
        ))}
      </div>
      ) : null}
    </section>
  );
}
