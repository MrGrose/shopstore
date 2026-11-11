import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";

import { CatalogProductList } from "./CatalogProductList";
import type { CatalogProductCardData } from "./catalogProductTypes";
import {
  clearCatalogScrollSnapshot,
  clearSkipCatalogEnterAnimation,
  saveCatalogScrollSnapshot,
  shouldSkipCatalogEnterAnimation,
} from "../../../lib/storefront/catalogScrollRestore";

const product: CatalogProductCardData = {
  id: 11,
  title: "Air Veron",
  brand: "Babolat",
  sale_price: 18000,
  regular_price: 20000,
};

function ListProbe() {
  return (
    <CatalogProductList
      items={[product]}
      pageSize={20}
      compact
      loading={false}
      loadingMore={false}
      hasMore={false}
      showStaleGrid={false}
      productsErrorMessage={null}
      productsFetched
      searchQ=""
      cartItems={[]}
      cartRefreshing={false}
      onOpen={() => undefined}
      onAddToCart={async () => undefined}
      onChangeCartQty={() => undefined}
      onLoadMore={() => undefined}
    />
  );
}

function PushCatalogButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/catalog")}>
      open-catalog
    </button>
  );
}

function enterMode(): string | null {
  return document.querySelector("[data-catalog-enter]")?.getAttribute("data-catalog-enter") ?? null;
}

function saveSkipFlag(): void {
  saveCatalogScrollSnapshot({
    url: "/catalog",
    top: 640,
    productId: 11,
    itemCount: 1,
  });
}

describe("CatalogProductList enter animation", () => {
  afterEach(() => {
    cleanup();
    clearCatalogScrollSnapshot();
    clearSkipCatalogEnterAnimation();
  });

  it("skips enter animation on POP when the skip flag is set", async () => {
    saveSkipFlag();

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<ListProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(enterMode()).toBe("skip");
    await waitFor(() => {
      expect(shouldSkipCatalogEnterAnimation()).toBe(false);
    });
  });

  it("plays enter animation on PUSH and clears a leftover skip flag", async () => {
    saveSkipFlag();

    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<ListProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("Air Veron")).toBeTruthy();
    expect(enterMode()).toBe("play");
    await waitFor(() => {
      expect(shouldSkipCatalogEnterAnimation()).toBe(false);
    });
  });

  it("plays enter animation on a normal PUSH without a skip flag", async () => {
    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<ListProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("Air Veron")).toBeTruthy();
    expect(enterMode()).toBe("play");
    expect(shouldSkipCatalogEnterAnimation()).toBe(false);
  });

  it("keeps POP skip across a StrictMode remount and clears the flag once", async () => {
    saveSkipFlag();

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/catalog"]}>
          <Routes>
            <Route path="/catalog" element={<ListProbe />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    expect(enterMode()).toBe("skip");
    await waitFor(() => {
      expect(shouldSkipCatalogEnterAnimation()).toBe(false);
    });
    expect(enterMode()).toBe("skip");
  });
});
