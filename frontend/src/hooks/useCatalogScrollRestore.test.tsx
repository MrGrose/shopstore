import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { useState } from "react";

import { useCatalogScrollRestore } from "./useCatalogScrollRestore";
import {
  catalogScrollRestoreApplied,
  clearCatalogScrollSnapshot,
  peekCatalogScrollSnapshot,
  restoreCatalogScroll,
  clearSkipCatalogEnterAnimation,
  saveCatalogScrollSnapshot,
  shouldSkipCatalogEnterAnimation,
  writeCatalogScrollTop,
} from "../lib/storefront/catalogScrollRestore";

vi.mock("../lib/storefront/catalogScrollRestore", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../lib/storefront/catalogScrollRestore")>();
  return {
    ...actual,
    restoreCatalogScroll: vi.fn(),
    writeCatalogScrollTop: vi.fn(),
    catalogScrollRestoreApplied: vi.fn(() => true),
  };
});

function RestoreProbe(props: {
  items: { id: number }[];
  hasMore?: boolean;
  loading?: boolean;
  loadingMore?: boolean;
  productsFetched?: boolean;
  fetchNextPage?: () => void;
}) {
  useCatalogScrollRestore({
    items: props.items,
    hasMore: props.hasMore ?? false,
    loading: props.loading ?? false,
    loadingMore: props.loadingMore ?? false,
    productsFetched: props.productsFetched ?? true,
    fetchNextPage: props.fetchNextPage ?? (() => undefined),
  });
  return <section id="products">catalog</section>;
}

function PushCatalogButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/catalog")}>
      open-catalog
    </button>
  );
}

function OpenProductButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => {
        saveCatalogScrollSnapshot({
          url: "/catalog",
          top: 640,
          productId: 15,
          itemCount: 24,
        });
        navigate("/catalog/product/15");
      }}
    >
      open-product
    </button>
  );
}

function InternalBackButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      internal-back
    </button>
  );
}

/** Stays mounted after PUSH so data/identity churn cannot remount the router. */
function ControllablePushCatalog() {
  const [items, setItems] = useState([{ id: 1 }]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [fetchNextPage, setFetchNextPage] = useState<() => void>(() => () => undefined);

  return (
    <>
      <RestoreProbe
        items={items}
        loading={loading}
        loadingMore={loadingMore}
        fetchNextPage={fetchNextPage}
      />
      <button
        type="button"
        onClick={() =>
          setItems(Array.from({ length: 48 }, (_, i) => ({ id: i + 1 })))
        }
      >
        bump-items
      </button>
      <button type="button" onClick={() => setLoading(true)}>
        set-loading
      </button>
      <button type="button" onClick={() => setLoadingMore(true)}>
        set-loading-more
      </button>
      <button
        type="button"
        onClick={() => setFetchNextPage(() => () => undefined)}
      >
        new-fetch-fn
      </button>
      <button
        type="button"
        onClick={() => {
          setFetchNextPage(() => () => undefined);
          setItems((prev) => [...prev]);
        }}
      >
        cart-rerender
      </button>
    </>
  );
}

/** POP listing that can churn data after restore without remounting the router. */
function ControllablePopCatalog() {
  const [items, setItems] = useState(
    Array.from({ length: 24 }, (_, i) => ({ id: i + 1 })),
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [fetchNextPage, setFetchNextPage] = useState<() => void>(() => () => undefined);

  return (
    <>
      <RestoreProbe
        items={items}
        loadingMore={loadingMore}
        fetchNextPage={fetchNextPage}
      />
      <button
        type="button"
        onClick={() =>
          setItems(Array.from({ length: 48 }, (_, i) => ({ id: i + 1 })))
        }
      >
        bump-items
      </button>
      <button type="button" onClick={() => setLoadingMore((v) => !v)}>
        toggle-loading-more
      </button>
      <button
        type="button"
        onClick={() => setFetchNextPage(() => () => undefined)}
      >
        new-fetch-fn
      </button>
      <button
        type="button"
        onClick={() => {
          setFetchNextPage(() => () => undefined);
          setItems((prev) => [...prev]);
        }}
      >
        unrelated-rerender
      </button>
    </>
  );
}

function zeroWriteCount(): number {
  return vi
    .mocked(writeCatalogScrollTop)
    .mock.calls.filter((call) => call[1] === 0).length;
}

describe("useCatalogScrollRestore", () => {
  afterEach(() => {
    cleanup();
    clearCatalogScrollSnapshot();
    clearSkipCatalogEnterAnimation();
    vi.mocked(restoreCatalogScroll).mockClear();
    vi.mocked(writeCatalogScrollTop).mockClear();
    vi.mocked(catalogScrollRestoreApplied).mockReset();
    vi.mocked(catalogScrollRestoreApplied).mockReturnValue(true);
    vi.unstubAllGlobals();
  });

  it("restores scroll on POP back to the same catalog URL", () => {
    saveCatalogScrollSnapshot({
      url: "/catalog?brand=babolat",
      top: 720,
      productId: 15,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/catalog?brand=babolat"]}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <RestoreProbe items={Array.from({ length: 24 }, (_, i) => ({ id: i + 1 }))} />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(restoreCatalogScroll).toHaveBeenCalled();
    expect(vi.mocked(restoreCatalogScroll).mock.calls[0]?.[1]).toMatchObject({
      url: "/catalog?brand=babolat",
      top: 720,
      productId: 15,
      itemCount: 24,
    });
    expect(peekCatalogScrollSnapshot()).toBeNull();
  });

  it("does not restore a pending snapshot on a PUSH catalog visit", async () => {
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 900,
      productId: 4,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<RestoreProbe items={[{ id: 4 }]} />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("catalog")).toBeTruthy();
    await waitFor(() => {
      expect(peekCatalogScrollSnapshot()).toBeNull();
    });
    expect(restoreCatalogScroll).not.toHaveBeenCalled();
  });

  it("on PUSH catalog mount clears snapshot and writes scroll 0", async () => {
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 900,
      productId: 4,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<RestoreProbe items={[{ id: 4 }]} />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("catalog")).toBeTruthy();
    await waitFor(() => {
      expect(peekCatalogScrollSnapshot()).toBeNull();
      expect(writeCatalogScrollTop).toHaveBeenCalledWith(expect.anything(), 0);
    });
  });

  it("does not re-zero scroll when PUSH catalog data or fetchNextPage identity changes", async () => {
    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<ControllablePushCatalog />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("catalog")).toBeTruthy();
    await waitFor(() => {
      expect(zeroWriteCount()).toBeGreaterThanOrEqual(1);
    });
    const zerosAfterPush = zeroWriteCount();

    screen.getByText("bump-items").click();
    screen.getByText("set-loading").click();
    screen.getByText("set-loading-more").click();
    screen.getByText("new-fetch-fn").click();

    expect(zeroWriteCount()).toBe(zerosAfterPush);
  });

  it("does not re-zero scroll on add-to-cart-like parent rerender after PUSH", async () => {
    render(
      <MemoryRouter initialEntries={["/cart"]}>
        <Routes>
          <Route path="/cart" element={<PushCatalogButton />} />
          <Route path="/catalog" element={<ControllablePushCatalog />} />
        </Routes>
      </MemoryRouter>,
    );

    screen.getByText("open-catalog").click();
    expect(await screen.findByText("catalog")).toBeTruthy();
    await waitFor(() => {
      expect(zeroWriteCount()).toBeGreaterThanOrEqual(1);
    });
    const zerosAfterPush = zeroWriteCount();

    screen.getByText("cart-rerender").click();
    expect(zeroWriteCount()).toBe(zerosAfterPush);
  });

  it("loads more pages until the saved item count is on screen", () => {
    const fetchNextPage = vi.fn();
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 1200,
      productId: 40,
      itemCount: 48,
    });

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <RestoreProbe
                items={Array.from({ length: 24 }, (_, i) => ({ id: i + 1 }))}
                hasMore
                fetchNextPage={fetchNextPage}
              />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(fetchNextPage).toHaveBeenCalled();
    expect(restoreCatalogScroll).not.toHaveBeenCalled();
    expect(peekCatalogScrollSnapshot()).not.toBeNull();
  });

  it("restores scroll after catalog → product → internal navigate(-1)", async () => {
    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <>
                <RestoreProbe items={Array.from({ length: 24 }, (_, i) => ({ id: i + 1 }))} />
                <OpenProductButton />
              </>
            }
          />
          <Route path="/catalog/product/:id" element={<InternalBackButton />} />
        </Routes>
      </MemoryRouter>,
    );

    vi.mocked(restoreCatalogScroll).mockClear();
    screen.getByText("open-product").click();
    expect(await screen.findByText("internal-back")).toBeTruthy();
    screen.getByText("internal-back").click();
    expect(await screen.findByText("catalog")).toBeTruthy();
    await waitFor(() => {
      expect(restoreCatalogScroll).toHaveBeenCalled();
    });
    expect(vi.mocked(restoreCatalogScroll).mock.calls.at(-1)?.[1]).toMatchObject({
      url: "/catalog",
      top: 640,
      productId: 15,
      itemCount: 24,
    });
    expect(peekCatalogScrollSnapshot()).toBeNull();
  });

  it("clears snapshot after successful restore and ignores later data churn", async () => {
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 640,
      productId: 15,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<ControllablePopCatalog />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(restoreCatalogScroll).toHaveBeenCalledTimes(1);
      expect(peekCatalogScrollSnapshot()).toBeNull();
    });

    vi.mocked(restoreCatalogScroll).mockClear();

    screen.getByText("bump-items").click();
    screen.getByText("toggle-loading-more").click();
    screen.getByText("new-fetch-fn").click();
    screen.getByText("unrelated-rerender").click();

    expect(restoreCatalogScroll).not.toHaveBeenCalled();
    expect(peekCatalogScrollSnapshot()).toBeNull();
  });

  it("does not clear snapshot when restore has not applied yet", () => {
    vi.mocked(catalogScrollRestoreApplied).mockReturnValue(false);

    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 1200,
      productId: 40,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <RestoreProbe items={Array.from({ length: 24 }, (_, i) => ({ id: i + 1 }))} />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(restoreCatalogScroll).toHaveBeenCalled();
    expect(peekCatalogScrollSnapshot()).toMatchObject({
      url: "/catalog",
      top: 1200,
      productId: 40,
      itemCount: 24,
    });
  });

  it("clears snapshot when ResizeObserver apply succeeds later", async () => {
    vi.mocked(catalogScrollRestoreApplied).mockReturnValueOnce(false).mockReturnValue(true);

    type RoCallback = ResizeObserverCallback;
    let roCallback: RoCallback | null = null;
    class FakeResizeObserver {
      constructor(cb: RoCallback) {
        roCallback = cb;
      }
      observe(): void {}
      disconnect(): void {}
      unobserve(): void {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);

    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 900,
      productId: 12,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <RestoreProbe items={Array.from({ length: 24 }, (_, i) => ({ id: i + 1 }))} />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(restoreCatalogScroll).toHaveBeenCalledTimes(1);
    expect(peekCatalogScrollSnapshot()).not.toBeNull();
    expect(roCallback).toBeTypeOf("function");

    roCallback?.(
      [{ target: document.getElementById("products")! } as ResizeObserverEntry],
      {} as ResizeObserver,
    );

    await waitFor(() => {
      expect(restoreCatalogScroll).toHaveBeenCalledTimes(2);
      expect(peekCatalogScrollSnapshot()).toBeNull();
    });
  });

  it("does not zero shared main on catalog unmount when opening PDP", () => {
    const main = document.createElement("main");
    main.style.overflowY = "auto";
    document.body.appendChild(main);
    window.history.replaceState({}, "", "/catalog");

    const { unmount } = render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<RestoreProbe items={[{ id: 1 }]} />} />
        </Routes>
      </MemoryRouter>,
    );

    window.history.replaceState({}, "", "/catalog/product/9");
    vi.mocked(writeCatalogScrollTop).mockClear();
    unmount();

    expect(writeCatalogScrollTop).not.toHaveBeenCalled();
    main.remove();
    window.history.replaceState({}, "", "/");
  });

  it("save snapshot for PDP marks skip-enter animation for next catalog mount", () => {
    expect(shouldSkipCatalogEnterAnimation()).toBe(false);
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 640,
      productId: 15,
      itemCount: 24,
    });
    expect(shouldSkipCatalogEnterAnimation()).toBe(true);
  });

    it("does not restore when the pending URL belongs to another catalog", () => {
    saveCatalogScrollSnapshot({
      url: "/catalog/padel?sort_price=asc",
      top: 400,
      productId: 8,
      itemCount: 24,
    });

    render(
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<RestoreProbe items={[{ id: 8 }]} />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(restoreCatalogScroll).not.toHaveBeenCalled();
  });
});
