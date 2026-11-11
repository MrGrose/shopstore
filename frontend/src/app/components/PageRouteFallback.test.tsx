import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { PageRouteFallback } from "./PageRouteFallback";

function renderPdpFallback(state?: { previewImageUrl?: string | null }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/catalog/product/1", state }]}>
      <PageRouteFallback variant="pdp" />
    </MemoryRouter>,
  );
}

describe("PageRouteFallback", () => {
  it("renders loading skeleton with accessible label", () => {
    render(<PageRouteFallback />);
    const root = screen.getByLabelText("Загрузка страницы");
    expect(root.getAttribute("aria-busy")).toBe("true");
  });

  it("uses the PDP hero frame instead of the generic 640 skeleton", () => {
    const { container } = renderPdpFallback();
    const root = screen.getByLabelText("Загрузка товара");
    expect(root.getAttribute("aria-busy")).toBe("true");
    expect(root.querySelector("[data-pdp-hero='frame']")).not.toBeNull();
    expect(root.className.includes("max-w-[640px]")).toBe(false);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("paints catalog preview in the PDP frame instead of the gray pulse", () => {
    const src = "https://cdn.shopify.com/s/files/x.jpg?width=560";
    const { container } = renderPdpFallback({ previewImageUrl: src });
    const preview = container.querySelector("[data-pdp-hero='preview']");
    expect(preview).not.toBeNull();
    expect(preview?.getAttribute("src")).toBe(src);
    expect(container.querySelector(".animate-pulse")).toBeNull();
  });
});
