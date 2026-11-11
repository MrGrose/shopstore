import { useState, useEffect, useCallback, useRef, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ShoppingBag, Menu, X, Search, User, LogOut } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useAuth } from "../auth/AuthContext";
import {
  buildCatalogSearchNavigateTarget,
  readCatalogSearchQuery,
} from "../../lib/storefront/catalogFilterParams";
import {
  catalogAllPath,
  catalogSportPath,
  storefrontHomePath,
} from "../../lib/storefront/catalogNavigation";
import { CartContents } from "./cart/CartContents";
import { broadcastCartCount, cartTotalQty, changeCartQty } from "../../lib/storefront/cart";
import { cartHasUnavailableItems, type ApiCart } from "../../lib/storefront/checkoutUi";
import { useRefreshOnPageActive } from "../../lib/storefront/useRefreshOnPageActive";
import { userInitials } from "../../lib/storefront/userDisplay";
import { userFacingApiErrorMessage } from "../../lib/apiErrorMapper";
import { mapApiErrorToUserMessage } from "../../lib/errorMessages";
import { useStorefrontCompact } from "../../lib/storefront/useStorefrontSurface";
import { useCatalogReferencePrefetch } from "../../lib/storefront/prefetchCatalogReference";
import { cartQueryKey, invalidateCartQuery, syncCartQueryCache, useCart } from "../../hooks/useCart";

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const [cartActionError, setCartActionError] = useState<string | null>(null);
  const [cartMutating, setCartMutating] = useState(false);
  const queryClient = useQueryClient();
  const { cart, isFetching, error: cartQueryError } = useCart();
  const cartCount = cartTotalQty(cart?.items);
  const cartForDrawer = (cart as ApiCart | undefined) ?? null;
  const cartLoading = cartOpen && isFetching;
  const cartError = cartQueryError
    ? mapApiErrorToUserMessage(cartQueryError, {
        fallback: "Не удалось загрузить корзину",
      })
    : null;
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, user, logout } = useAuth();
  const compact = useStorefrontCompact();
  const prefetchCatalogReference = useCatalogReferencePrefetch();
  const isHomeCatalog = location.pathname === "/";
  const navTransparent = isHomeCatalog && !scrolled;

  const isNavActive = (path: string) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`);

  const sportNavLinks = [
    { label: "Каталог", path: catalogAllPath(), exact: true },
    { label: "Падел", path: catalogSportPath("Padel") },
    { label: "Теннис", path: catalogSportPath("Tennis") },
    { label: "Бег", path: catalogSportPath("Running") },
  ] as const;
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const goLogin = useCallback(
    (nextPath: string) => {
      navigate(`/login?next=${encodeURIComponent(nextPath)}`);
    },
    [navigate],
  );

  const handleLogout = useCallback(async () => {
    await logout();
    navigate(catalogAllPath(), { replace: true });
  }, [logout, navigate]);

  const refreshCart = useCallback(async (): Promise<ApiCart | null> => {
    await invalidateCartQuery(queryClient);
    const next = queryClient.getQueryData<ApiCart>(cartQueryKey);
    return next ?? null;
  }, [queryClient]);

  useRefreshOnPageActive(refreshCart, cartOpen);

  async function changeQty(
    productId: number,
    nextQty: number,
    variantId?: number | null
  ) {
    if (cartMutating) return;
    const pid = Number(productId);
    if (!Number.isFinite(pid) || pid <= 0) return;
    setCartMutating(true);
    setCartActionError(null);
    try {
      const updated = await changeCartQty(pid, nextQty, variantId ?? null);
      if (updated) {
        syncCartQueryCache(queryClient, updated);
      } else {
        await refreshCart();
      }
    } catch (e) {
      setCartActionError(
        userFacingApiErrorMessage(e, "Не удалось изменить количество"),
      );
      await refreshCart();
    } finally {
      setCartMutating(false);
    }
  }

  async function openCart() {
    setCartOpen(true);
    await refreshCart();
  }

  const beginCheckout = useCallback(async () => {
    const next = await refreshCart();
    if (cartHasUnavailableItems(next)) return;

    setCartOpen(false);
    if (!isAuthenticated) {
      goLogin("/checkout");
      return;
    }
    navigate("/checkout");
  }, [isAuthenticated, goLogin, navigate, refreshCart]);

  useEffect(() => {
    const handler = () => {
      if (!isAuthenticated) {
        goLogin("/checkout");
        return;
      }
      navigate("/checkout");
    };
    window.addEventListener("store:checkout:open", handler);
    return () => window.removeEventListener("store:checkout:open", handler);
  }, [isAuthenticated, goLogin, navigate]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!searchOpen) return;
    const t = window.setTimeout(() => searchInputRef.current?.focus(), 120);
    return () => window.clearTimeout(t);
  }, [searchOpen]);

  useEffect(() => {
    if (!searchOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [searchOpen]);

  useEffect(() => {
    setSearchOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    setSearchQuery(readCatalogSearchQuery(new URLSearchParams(location.search)));
  }, [location.search]);

  function submitSearch(e?: FormEvent) {
    e?.preventDefault();
    const q = searchQuery.trim();
    if (!q) {
      clearSearchNav();
      return;
    }
    setSearchOpen(false);
    const target = buildCatalogSearchNavigateTarget(
      location.pathname,
      location.search,
      q,
    );
    navigate(`${target.pathname}${target.search}`);
  }

  function clearSearchNav() {
    setSearchQuery("");
    setSearchOpen(false);
    if (!readCatalogSearchQuery(new URLSearchParams(location.search)) && !searchQuery.trim()) {
      return;
    }
    const target = buildCatalogSearchNavigateTarget(
      location.pathname,
      location.search,
      "",
    );
    navigate(`${target.pathname}${target.search}`);
  }

  useEffect(() => {
    const modalOpen = cartOpen || menuOpen;
    if (!modalOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [cartOpen, menuOpen]);

  return (
    <>
      <nav
        className={`fixed top-0 left-0 right-0 z-50 sp-transition ${
          navTransparent && !searchOpen
            ? "glass-navbar-transparent"
            : "glass-navbar shadow-[0_1px_0_rgba(0,0,0,0.05)]"
        }`}
      >
        <div style={{ height: "64px" }}>
        <div className="max-w-[1400px] mx-auto px-6 h-full flex items-center justify-between">
          <Link to={storefrontHomePath()} className="flex items-center gap-0 text-[20px] tracking-tight no-underline">
            <span style={{ color: navTransparent ? "#FFFFFF" : "var(--sp-text-primary)", fontWeight: 600 }}>
              SHOP
            </span>
            <span style={{ color: "var(--sp-cyan)", fontWeight: 600 }}>STORE</span>
          </Link>

          {!isHomeCatalog ? (
          <div className="hidden md:flex items-center gap-8">
            {sportNavLinks.map(({ label, path, ...rest }) => {
              const exact = "exact" in rest && rest.exact;
              const active = exact
                ? location.pathname === path
                : isNavActive(path);
              const linkColor = navTransparent
                ? active
                  ? "#FFFFFF"
                  : "rgba(255,255,255,0.75)"
                : active
                  ? "var(--sp-text-primary)"
                  : "var(--sp-text-secondary)";
              return (
                <Link
                  key={path}
                  to={path}
                  onMouseEnter={prefetchCatalogReference}
                  onFocus={prefetchCatalogReference}
                  className={`text-[14px] sp-transition ${active ? "font-medium" : ""}`}
                  style={{ color: linkColor }}
                >
                  {label}
                </Link>
              );
            })}
          </div>
          ) : null}

          <div className="flex items-center gap-3">
            {isAuthenticated ? (
              <div className="flex items-center gap-0.5">
                <Link
                  to="/account"
                  title="Личный кабинет"
                  aria-label="Личный кабинет"
                  className="flex items-center gap-2 px-5 py-2 text-[14px] font-medium sp-transition hover:opacity-90 no-underline"
                  style={{
                    borderRadius: "var(--sp-radius-pill)",
                    color: navTransparent ? "#FFFFFF" : "var(--sp-text-primary)",
                  }}
                >
                  <span
                    className="w-6 h-6 shrink-0 flex items-center justify-center text-[10px] font-semibold"
                    style={{
                      background: "linear-gradient(135deg, var(--sp-blue), var(--sp-cyan))",
                      color: "#fff",
                      borderRadius: "50%",
                    }}
                  >
                    {userInitials(user?.name)}
                  </span>
                </Link>
                <button
                  type="button"
                  title="Выйти"
                  aria-label="Выйти"
                  onClick={() => void handleLogout()}
                  className="p-2 hover:opacity-70 sp-transition"
                  style={{
                    color: navTransparent ? "rgba(255,255,255,0.75)" : "var(--sp-text-muted)",
                  }}
                >
                  <LogOut size={18} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                title="Войти"
                aria-label="Войти"
                onClick={() => goLogin("/account")}
                className="p-2 hover:opacity-70 sp-transition"
                style={{
                  color: navTransparent ? "rgba(255,255,255,0.85)" : "var(--sp-text-secondary)",
                }}
              >
                <User size={20} />
              </button>
            )}

            <button
              type="button"
              aria-label="Поиск"
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen((v) => !v)}
              className="p-2 hover:opacity-70 sp-transition"
              style={{
                color:
                  searchOpen || !navTransparent
                    ? "var(--sp-text-secondary)"
                    : "rgba(255,255,255,0.85)",
              }}
            >
              {searchOpen ? <X size={18} /> : <Search size={20} />}
            </button>

            <button
              type="button"
              onClick={() => void openCart()}
              aria-label={cartCount > 0 ? `Корзина, ${cartCount} товаров` : "Корзина"}
              className={
                compact
                  ? "relative flex size-8 shrink-0 items-center justify-center sp-transition hover:opacity-90"
                  : "relative flex items-center gap-2 px-5 py-2 text-[14px] font-medium sp-transition hover:opacity-90"
              }
              style={{
                background: compact && navTransparent ? "rgba(255, 255, 255, 0.2)" : "var(--sp-blue)",
                color: "#FFFFFF",
                borderRadius: "var(--sp-radius-pill)",
                backdropFilter: compact && navTransparent ? "blur(10px)" : undefined,
              }}
            >
              <span className="relative inline-flex">
                <ShoppingBag size={compact ? 16 : 18} />
                {cartCount > 0 ? (
                  <span
                    className={`absolute rounded-full bg-white px-0.5 text-center font-semibold text-sp-blue ${
                      compact
                        ? "-right-1.5 -top-1 min-w-[14px] text-[9px] leading-[14px]"
                        : "-right-2 -top-1.5 min-w-[16px] text-[10px] leading-4"
                    }`}
                  >
                    {cartCount > 99 ? "99+" : cartCount}
                  </span>
                ) : null}
              </span>
              {!compact ? <span className="hidden sm:inline">Корзина</span> : null}
            </button>

            {!isHomeCatalog ? (
            <button
              className="md:hidden p-2"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label="Menu"
              style={{ color: navTransparent ? "#FFFFFF" : "var(--sp-text-primary)" }}
            >
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            ) : null}
          </div>
        </div>
        </div>

        <AnimatePresence>
          {searchOpen ? (
            <motion.div
              key="search-panel"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="overflow-hidden border-t border-sp-border glass-navbar"
            >
              <div className="max-w-[1400px] mx-auto px-6 py-4">
                <form onSubmit={submitSearch} className="flex gap-2 items-center">
                  <input
                    ref={searchInputRef}
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Название, бренд, категория, ID или SKU"
                    className="w-full px-6 py-3 outline-none sp-transition focus:shadow-[0_0_0_3px_rgba(41,151,255,0.1)]"
                    style={{
                      background: "var(--sp-surface)",
                      border: "1px solid var(--sp-border)",
                      borderRadius: "var(--sp-radius-input)",
                      color: "var(--sp-text-primary)",
                    }}
                  />
                  {(searchQuery.trim() || new URLSearchParams(location.search).get("q")) ? (
                    <button
                      type="button"
                      onClick={clearSearchNav}
                      className="shrink-0 px-3 py-3 text-[13px] font-medium text-sp-blue bg-transparent border-0 cursor-pointer"
                    >
                      Сбросить
                    </button>
                  ) : null}
                </form>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </nav>

      {/* Mobile menu */}
      <AnimatePresence>
        {menuOpen && !isHomeCatalog && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.25 }}
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "var(--sp-surface)",
              zIndex: 40,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              gap: "2rem",
            }}
          >
            {sportNavLinks.map(({ label, path }, i) => (
              <motion.div
                key={path}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06 }}
              >
                <Link
                  to={path}
                  onClick={() => setMenuOpen(false)}
                  onMouseEnter={prefetchCatalogReference}
                  onFocus={prefetchCatalogReference}
                  className="font-semibold no-underline sp-transition hover:text-sp-blue"
                  style={{
                    fontSize: "clamp(2rem, 6vw, 3rem)",
                    letterSpacing: "-0.02em",
                    color: "var(--sp-text-primary)",
                  }}
                >
                  {label}
                </Link>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Cart drawer */}
      <AnimatePresence>
        {cartOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 60,
              backgroundColor: "rgba(0,0,0,0.6)",
              backdropFilter: "blur(10px)",
            }}
            onClick={() => setCartOpen(false)}
          >
            <motion.div
              className={compact ? "flex min-h-0 flex-col" : undefined}
              initial={compact ? { y: "100%", opacity: 0 } : { x: 40, opacity: 0 }}
              animate={compact ? { y: 0, opacity: 1 } : { x: 0, opacity: 1 }}
              exit={compact ? { y: "100%", opacity: 0 } : { x: 40, opacity: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              style={
                compact
                  ? {
                      position: "absolute",
                      left: 0,
                      right: 0,
                      bottom: 0,
                      maxHeight: "min(88dvh, calc(100dvh - env(safe-area-inset-bottom, 0px)))",
                      backgroundColor: "var(--sp-surface)",
                      borderTop: "1px solid var(--sp-border)",
                      borderTopLeftRadius: "16px",
                      borderTopRightRadius: "16px",
                      display: "flex",
                      flexDirection: "column",
                      overflow: "hidden",
                      paddingBottom: "env(safe-area-inset-bottom, 0px)",
                    }
                  : {
                      position: "absolute",
                      top: 0,
                      right: 0,
                      height: "100%",
                      width: "min(460px, 92vw)",
                      backgroundColor: "var(--sp-surface)",
                      borderLeft: "1px solid var(--sp-border)",
                      display: "flex",
                      flexDirection: "column",
                    }
              }
              onClick={(e) => e.stopPropagation()}
            >
              {compact ? (
                <div className="shrink-0 border-b border-sp-border px-4 pb-3 pt-3">
                  <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-sp-border" aria-hidden />
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="m-0 text-[14px] font-semibold text-sp-text-primary">Корзина</h2>
                    <button
                      type="button"
                      onClick={() => setCartOpen(false)}
                      className="flex size-8 shrink-0 items-center justify-center rounded-full border border-sp-border bg-white text-sp-text-primary shadow-sm sp-transition hover:opacity-80"
                      aria-label="Закрыть"
                    >
                      <X size={16} />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between px-6 py-5 border-b border-sp-border">
                  <h2 className="text-[20px] font-semibold text-sp-text-primary m-0">Корзина</h2>
                  <button
                    type="button"
                    onClick={() => setCartOpen(false)}
                    className="p-1 text-sp-text-muted hover:opacity-70 sp-transition"
                    aria-label="Закрыть"
                  >
                    <X size={20} />
                  </button>
                </div>
              )}

              <CartContents
                cart={cartForDrawer}
                loading={cartLoading}
                error={cartError}
                actionError={cartActionError}
                isMutating={cartMutating}
                compact={compact}
                onChangeQty={changeQty}
                onCheckout={beginCheckout}
                showContinueShopping
                onContinueShopping={() => setCartOpen(false)}
                onProductLinkClick={() => setCartOpen(false)}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </>
  );
}
