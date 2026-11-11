import { AnimatePresence } from "motion/react";
import { useEffect, useState } from "react";
import { AboutCompanyContent } from "./AboutCompanyContent";
import { StorefrontModalFrame } from "../StorefrontModalFrame";
import "../../../styles/company-about.css";

export function CompanyModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener("store:company:open", handler);
    return () => window.removeEventListener("store:company:open", handler);
  }, []);

  return (
    <AnimatePresence>
      {open ? (
        <StorefrontModalFrame
          title="О компании"
          onClose={() => setOpen(false)}
          zIndex={91}
          width="min(720px, 94vw)"
          height="min(82vh, 760px)"
          margin="9vh auto"
        >
          <AboutCompanyContent />
        </StorefrontModalFrame>
      ) : null}
    </AnimatePresence>
  );
}
