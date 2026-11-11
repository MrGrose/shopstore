import { useEffect, useState } from "react";

const DESKTOP_SIDEBAR_MQL = "(min-width: 1024px)";

export function useDesktopSidebar(): boolean {
  const [isDesktopSidebar, setIsDesktopSidebar] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(DESKTOP_SIDEBAR_MQL).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_SIDEBAR_MQL);
    const onChange = () => setIsDesktopSidebar(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isDesktopSidebar;
}
