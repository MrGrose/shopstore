import { QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { AuthProvider } from "./app/auth/AuthContext.tsx";
import App from "./app/App.tsx";
import { queryClient } from "./lib/queryClient.ts";
import { installRequestMetrics } from "./lib/requestMetrics.ts";
import { storefrontBasename } from "./lib/storefront/miniApp";
import { persistTelegramLaunchParams } from "./lib/storefront/telegramWebApp";
import "./styles/index.css";

installRequestMetrics();
// До BrowserRouter: RR Navigate/setSearchParams стирают tgWebAppData из hash.
persistTelegramLaunchParams();

createRoot(document.getElementById("root")!).render(
  <BrowserRouter basename={storefrontBasename()}>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </BrowserRouter>,
);
