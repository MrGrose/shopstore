import { useEffect } from "react";

// Перезапрашивает данные, когда пользователь возвращается на вкладку.
export function useRefreshOnPageActive(
  refresh: () => void | Promise<void>,
  enabled = true,
) {
  useEffect(() => {
    if (!enabled) return;

    const run = () => {
      if (document.visibilityState === "visible") void refresh();
    };

    document.addEventListener("visibilitychange", run);
    window.addEventListener("focus", run);
    return () => {
      document.removeEventListener("visibilitychange", run);
      window.removeEventListener("focus", run);
    };
  }, [refresh, enabled]);
}
