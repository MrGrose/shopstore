import { AnimatePresence } from "motion/react";
import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";
import {
  fetchLegalFragment,
  legalTitleForPath,
  resolveLegalFromHref,
} from "../../../lib/storefront/legal";
import { StorefrontModalFrame } from "../StorefrontModalFrame";
import "../../../styles/legal-doc.css";

export function LegalModal() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("Документы");
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (path: string, docTitle: string) => {
    setOpen(true);
    setTitle(docTitle);
    setHtml("");
    setError(null);
    setLoading(true);
    try {
      setHtml(await fetchLegalFragment(path));
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось загрузить документ"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ path?: string; title?: string }>;
      const path = String(ce?.detail?.path || "").trim();
      if (!path) return;
      const docTitle = String(ce?.detail?.title || legalTitleForPath(path));
      void load(path, docTitle);
    };
    window.addEventListener("store:legal:open", handler);
    return () => window.removeEventListener("store:legal:open", handler);
  }, [load]);

  const onContentClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const a = (e.target as HTMLElement | null)?.closest?.("a") as HTMLAnchorElement | null;
      if (!a) return;
      const href = String(a.getAttribute("href") || "").trim();
      if (!href || href.startsWith("#")) return;
      const resolved = resolveLegalFromHref(href);
      if (!resolved) return;
      e.preventDefault();
      e.stopPropagation();
      void load(resolved.path, resolved.title);
    },
    [load],
  );

  return (
    <AnimatePresence>
      {open ? (
        <StorefrontModalFrame title={title} onClose={() => setOpen(false)}>
          {loading ? (
            <p className="text-[14px] text-sp-text-muted">Загрузка…</p>
          ) : error ? (
            <p className="text-[14px] text-red-500">Не удалось загрузить: {error}</p>
          ) : (
            <div dangerouslySetInnerHTML={{ __html: html }} onClick={onContentClick} />
          )}
        </StorefrontModalFrame>
      ) : null}
    </AnimatePresence>
  );
}
