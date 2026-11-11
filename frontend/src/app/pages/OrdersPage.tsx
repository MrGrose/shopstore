import { useEffect } from "react";
import { useNavigate } from "react-router";
import { RequireAuth } from "../auth/RequireAuth";

/** Shortcut: /orders → /account?tab=orders */
function OrdersRedirect() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate("/account?tab=orders", { replace: true });
  }, [navigate]);

  return null;
}

export function OrdersPage() {
  return (
    <RequireAuth>
      <OrdersRedirect />
    </RequireAuth>
  );
}
