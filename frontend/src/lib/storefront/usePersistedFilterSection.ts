import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router";
import {
  loadFilterSectionsState,
  saveFilterSectionsState,
  type CatalogFilterSectionKey,
} from "./catalogFilterUi";

export function usePersistedFilterSection(section: CatalogFilterSectionKey, resetToken = "") {
  const location = useLocation();
  const readOpen = useCallback(
    () => loadFilterSectionsState(location.pathname)[section],
    [location.pathname, section],
  );
  const [open, setOpenState] = useState(readOpen);

  useEffect(() => {
    setOpenState(readOpen());
  }, [readOpen, resetToken]);

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next);
      saveFilterSectionsState(location.pathname, { [section]: next });
    },
    [location.pathname, section],
  );

  const toggle = useCallback(() => {
    setOpen(!open);
  }, [open, setOpen]);

  return { open, setOpen, toggle };
}
