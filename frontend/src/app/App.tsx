import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router";
import { CompanyModal } from "./components/company/CompanyModal";
import { LegalModal } from "./components/legal/LegalModal";
import { ShoeSizeGuideModal } from "./components/size/ShoeSizeGuideModal";
import { MiniAppLayout } from "./layouts/MiniAppLayout";
import { StorefrontLayout } from "./layouts/StorefrontLayout";
import { isTelegramMiniAppRoute } from "../lib/storefront/miniApp";
import { HomePage } from "./pages/HomePage";
import { CartPage } from "./pages/CartPage";
import { LoginPage } from "./pages/LoginPage";
import { LegalPage } from "./pages/LegalPage";
import { MiniAppPhoneLinkPrompt } from "./components/auth/MiniAppPhoneLinkPrompt";
import { WebTelegramLinkPrompt } from "./components/auth/WebTelegramLinkPrompt";
import { PageRouteFallback } from "./components/PageRouteFallback";

const CheckoutPage = lazy(() =>
  import("./pages/CheckoutPage").then((module) => ({ default: module.CheckoutPage })),
);
const AccountPage = lazy(() =>
  import("./pages/AccountPage").then((module) => ({ default: module.AccountPage })),
);
const OrdersPage = lazy(() =>
  import("./pages/OrdersPage").then((module) => ({ default: module.OrdersPage })),
);
const SupportPage = lazy(() =>
  import("./pages/SupportPage").then((module) => ({ default: module.SupportPage })),
);
const ProductPage = lazy(() =>
  import("./pages/ProductPage").then((module) => ({ default: module.ProductPage })),
);
const CatalogPage = lazy(() =>
  import("./catalog/CatalogRoutes").then((module) => ({ default: module.CatalogPage })),
);
const SportCatalogPage = lazy(() =>
  import("./catalog/CatalogRoutes").then((module) => ({
    default: module.SportCatalogPage,
  })),
);

function lazyPage(element: ReactNode, fallback?: ReactNode) {
  return <Suspense fallback={fallback ?? <PageRouteFallback />}>{element}</Suspense>;
}

const productPage = lazyPage(<ProductPage />, <PageRouteFallback variant="pdp" />);

const legalRoutes = (
  <>
    <Route path="/privacy" element={<LegalPage />} />
    <Route path="/terms" element={<LegalPage />} />
    <Route path="/consent" element={<LegalPage />} />
    <Route path="/returns" element={<LegalPage />} />
    <Route path="/referral-rules" element={<LegalPage />} />
  </>
);

const storefrontRoutes = (
  <>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/support" element={lazyPage(<SupportPage />)} />
    {legalRoutes}
    <Route element={<StorefrontLayout />}>
      <Route path="/" element={<HomePage />} />
      <Route path="/catalog" element={lazyPage(<CatalogPage />)} />
      <Route path="/catalog/product/:productId" element={productPage} />
      <Route path="/catalog/:sport" element={lazyPage(<SportCatalogPage />)} />
      <Route path="/cart" element={<CartPage />} />
      <Route path="/account" element={lazyPage(<AccountPage />)} />
      <Route path="/orders" element={lazyPage(<OrdersPage />)} />
      <Route path="/checkout" element={lazyPage(<CheckoutPage />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>
  </>
);

const miniAppRoutes = (
  <Route element={<MiniAppLayout />}>
    <Route index element={<Navigate to="/catalog" replace />} />
    <Route path="support" element={lazyPage(<SupportPage />)} />
    {legalRoutes}
    <Route path="catalog" element={lazyPage(<CatalogPage />)} />
    <Route path="catalog/all" element={<Navigate to="/catalog" replace />} />
    <Route path="catalog/product/:productId" element={productPage} />
    <Route path="catalog/:sport" element={lazyPage(<SportCatalogPage />)} />
    <Route path="cart" element={<CartPage />} />
    <Route path="account" element={lazyPage(<AccountPage />)} />
    <Route path="orders" element={lazyPage(<OrdersPage />)} />
    <Route path="checkout" element={lazyPage(<CheckoutPage />)} />
    <Route path="*" element={<Navigate to="/catalog" replace />} />
  </Route>
);

export default function App() {
  const miniApp = isTelegramMiniAppRoute();

  return (
    <>
      <LegalModal />
      <ShoeSizeGuideModal />
      <CompanyModal />
      {miniApp ? <MiniAppPhoneLinkPrompt /> : null}
      {!miniApp ? <WebTelegramLinkPrompt /> : null}
      <Routes>{miniApp ? miniAppRoutes : storefrontRoutes}</Routes>
    </>
  );
}
