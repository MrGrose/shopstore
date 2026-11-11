import { useEffect } from "react";
import { useNavigate } from "react-router";
import { RequireAuth } from "../auth/RequireAuth";

/** Shortcut: /support → /account?tab=support */
function SupportRedirect() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate("/account?tab=support", { replace: true });
  }, [navigate]);

  return null;
}

export function SupportPage() {
  return (
    <RequireAuth>
      <SupportRedirect />
    </RequireAuth>
  );
}
