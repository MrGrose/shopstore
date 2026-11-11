import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

// Tab return: invalidate catalog navigation/subcategories via React Query.
export function useCatalogWindowFocusInvalidation(enabled = true): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      void queryClient.invalidateQueries({ queryKey: ["catalog", "navigation"] });
      void queryClient.invalidateQueries({ queryKey: ["catalog", "subcategories"] });
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [enabled, queryClient]);
}
