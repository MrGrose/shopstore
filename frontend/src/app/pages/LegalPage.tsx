import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ArrowLeft } from "lucide-react";
import { catalogAllPath } from "../../lib/storefront/catalogNavigation";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import {
  fetchLegalFragment,
  pathToLegalSlug,
  resolveLegalFromHref,
} from "../../lib/storefront/legal";
import { useStorefrontCompact, useStorefrontCompactPagePad } from "../../lib/storefront/useStorefrontSurface";
import "../../styles/legal-doc.css";

export function LegalPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const compact = useStorefrontCompact();
  const pagePad = useStorefrontCompactPagePad("pb-2");
  const slug = pathToLegalSlug(pathname);

  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) {
      setLoading(false);
      setError("Документ не найден");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchLegalFragment(`/${slug}`)
      .then((fragment) => {
        if (!cancelled) setHtml(fragment);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(userFacingApiErrorMessage(e, "Не удалось загрузить документ"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

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
      navigate(resolved.path);
    },
    [navigate],
  );

  if (!slug) {
    return <Navigate to={catalogAllPath()} replace />;
  }

  return (
    <div className={compact ? `px-3 ${pagePad}` : "mx-auto max-w-[720px] px-6 py-8 lg:px-8"}>
      <button
        type="button"
        onClick={() => navigate(-1)}
        className={
          compact
            ? "mb-3 inline-flex items-center gap-1.5 border-0 bg-transparent p-0 text-[12px] font-medium text-sp-blue sp-transition hover:opacity-80"
            : "mb-6 inline-flex items-center gap-2 border-0 bg-transparent p-0 text-[14px] font-medium text-sp-blue sp-transition hover:opacity-80"
        }
      >
        <ArrowLeft className={compact ? "size-3.5" : "size-4"} />
        Назад
      </button>

      {loading ? (
        <p className="text-[14px] text-sp-text-secondary">Загрузка…</p>
      ) : error ? (
        <p className="text-[14px] text-red-500">{error}</p>
      ) : (
        <div dangerouslySetInnerHTML={{ __html: html }} onClick={onContentClick} />
      )}

      {!compact ? (
        <p className="mt-8 text-[13px] text-sp-text-muted">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="border-0 bg-transparent p-0 text-sp-blue no-underline hover:underline"
          >
            Назад
          </button>
        </p>
      ) : null}
    </div>
  );
}
