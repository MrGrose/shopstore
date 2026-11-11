import { NavLink, useLocation, useNavigate } from "react-router";
import { BookOpen, HelpCircle, ShoppingBag, User } from "lucide-react";
import { cartTotalQty } from "../../lib/storefront/cart";
import { catalogAllPath } from "../../lib/storefront/catalogNavigation";
import { useCart } from "../../hooks/useCart";

const navItemClass = ({ isActive }: { isActive: boolean }) =>
  [
    "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition-colors",
    isActive ? "text-sp-blue" : "text-sp-text-muted",
  ].join(" ");

export function MiniAppBottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { cart } = useCart();
  const cartCount = cartTotalQty(cart?.items);

  const catalogActive =
    location.pathname === "/catalog" ||
    (location.pathname.startsWith("/catalog/") &&
      !location.pathname.includes("/product/"));

  const profileActive =
    (location.pathname.startsWith("/account") ||
      location.pathname.startsWith("/orders")) &&
    !location.search.includes("tab=support");

  const supportActive =
    location.pathname.startsWith("/account") && location.search.includes("tab=support");

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-[60] border-t border-sp-border bg-sp-surface/95 backdrop-blur-md"
      style={{ paddingBottom: "max(env(safe-area-inset-bottom, 0px), 4px)" }}
      aria-label="Навигация Mini App"
    >
      <div className="mx-auto flex max-w-lg items-stretch px-1">
        <NavLink to={catalogAllPath()} className={() => navItemClass({ isActive: catalogActive })}>
          <BookOpen className="size-5" strokeWidth={1.75} />
          <span>Каталог</span>
        </NavLink>

        <NavLink to="/cart" className={navItemClass}>
          <span className="relative">
            <ShoppingBag className="size-5" strokeWidth={1.75} />
            {cartCount > 0 ? (
              <span className="absolute -right-2 -top-1.5 min-w-[16px] rounded-full bg-sp-blue px-1 text-center text-[10px] font-semibold leading-4 text-white">
                {cartCount > 99 ? "99+" : cartCount}
              </span>
            ) : null}
          </span>
          <span>Корзина</span>
        </NavLink>

        <button
          type="button"
          className={navItemClass({ isActive: profileActive })}
          onClick={() => navigate("/account?tab=profile")}
        >
          <User className="size-5" strokeWidth={1.75} />
          <span>Профиль</span>
        </button>

        <button
          type="button"
          className={navItemClass({ isActive: supportActive })}
          onClick={() => navigate("/account?tab=support")}
        >
          <HelpCircle className="size-5" strokeWidth={1.75} />
          <span>Поддержка</span>
        </button>
      </div>
    </nav>
  );
}
