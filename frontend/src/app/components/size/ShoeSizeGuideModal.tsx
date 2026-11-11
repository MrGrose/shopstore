import { AnimatePresence } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";
import { fetchShoeSizeGuideHtml } from "../../../lib/storefront/shoeSizeGuide";
import { useStorefrontCompact } from "../../../lib/storefront/useStorefrontSurface";
import { StorefrontModalFrame } from "../StorefrontModalFrame";
import "../../../styles/legal-doc.css";
import "../../../styles/size-guide.css";

export function ShoeSizeGuideModal() {
  const compact = useStorefrontCompact();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("Таблица размеров");
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (brand: string, docTitle: string) => {
    setOpen(true);
    setTitle(docTitle);
    setHtml("");
    setError(null);
    setLoading(true);
    try {
      setHtml(await fetchShoeSizeGuideHtml(brand));
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось загрузить таблицу размеров"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ brand?: string; title?: string }>;
      const brand = String(ce?.detail?.brand || "").trim();
      if (!brand) return;
      const docTitle = String(ce?.detail?.title || `Таблица размеров — ${brand}`);
      void load(brand, docTitle);
    };
    window.addEventListener("store:shoe-size-guide:open", handler);
    return () => window.removeEventListener("store:shoe-size-guide:open", handler);
  }, [load]);

  return (
    <AnimatePresence>
      {open ? (
        <StorefrontModalFrame
          title={title}
          onClose={() => setOpen(false)}
          zIndex={compact ? 100 : 90}
          width={compact ? "min(100%, 94vw)" : "min(720px, 94vw)"}
          height={compact ? "min(92dvh, 900px)" : "min(86vh, 900px)"}
          margin={compact ? "0.75rem auto" : "7vh auto"}
        >
          {loading ? (
            <p className="text-[14px] text-sp-text-muted">Загрузка…</p>
          ) : error ? (
            <p className="text-[14px] text-red-500">{error}</p>
          ) : (
            <div dangerouslySetInnerHTML={{ __html: html }} />
          )}
        </StorefrontModalFrame>
      ) : null}
    </AnimatePresence>
  );
}
