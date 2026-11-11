import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImageWithFallback } from "./ImageWithFallback";

afterEach(() => {
  cleanup();
});

describe("ImageWithFallback", () => {
  it("renders the primary src", () => {
    const { getByAltText } = render(
      <ImageWithFallback src="/media/products/a.jpg" alt="racket" />,
    );
    expect(getByAltText("racket").getAttribute("src")).toBe("/media/products/a.jpg");
  });

  it("falls back to CDN then unmounts when placeholderSrc is omitted", () => {
    const { getByAltText, container } = render(
      <ImageWithFallback
        src="/media/products/a.jpg"
        fallbackSrc="https://cdn.shopify.com/s/files/1/p.jpg"
        alt="racket"
      />,
    );
    fireEvent.error(getByAltText("racket"));
    expect(getByAltText("racket").getAttribute("src")).toBe(
      "https://cdn.shopify.com/s/files/1/p.jpg",
    );
    fireEvent.error(getByAltText("racket"));
    expect(container.firstChild).toBeNull();
  });

  it("calls onLoad after primary src loads", () => {
    const onLoad = vi.fn();
    const { getByAltText } = render(
      <ImageWithFallback src="/media/products/a.jpg" alt="racket" onLoad={onLoad} />,
    );
    fireEvent.load(getByAltText("racket"));
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("calls onLoad after fallback src loads", () => {
    const onLoad = vi.fn();
    const { getByAltText } = render(
      <ImageWithFallback
        src="/media/products/a.jpg"
        fallbackSrc="https://cdn.shopify.com/s/files/1/p.jpg"
        alt="racket"
        onLoad={onLoad}
      />,
    );
    fireEvent.error(getByAltText("racket"));
    fireEvent.load(getByAltText("racket"));
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("reports exhaustion only after the fallback also fails", () => {
    const onExhausted = vi.fn();
    const { getByAltText, container } = render(
      <ImageWithFallback
        src="/media/products/a.jpg"
        fallbackSrc="https://cdn.shopify.com/s/files/1/p.jpg"
        alt="racket"
        onExhausted={onExhausted}
      />,
    );
    fireEvent.error(getByAltText("racket"));
    expect(onExhausted).not.toHaveBeenCalled();
    expect(getByAltText("racket").getAttribute("src")).toBe(
      "https://cdn.shopify.com/s/files/1/p.jpg",
    );
    fireEvent.error(getByAltText("racket"));
    expect(onExhausted).toHaveBeenCalledTimes(1);
    expect(container.firstChild).toBeNull();
  });

  it("uses placeholderSrc instead of the gray svg after fallback fails", () => {
    const { getByAltText, queryByAltText } = render(
      <ImageWithFallback
        src="/media/products/a.jpg"
        fallbackSrc="https://cdn.shopify.com/s/files/1/p.jpg"
        placeholderSrc="/brand/placeholder.jpg"
        alt="racket"
      />,
    );
    fireEvent.error(getByAltText("racket"));
    expect(getByAltText("racket").getAttribute("src")).toBe(
      "https://cdn.shopify.com/s/files/1/p.jpg",
    );
    fireEvent.error(getByAltText("racket"));
    expect(getByAltText("racket").getAttribute("src")).toBe("/brand/placeholder.jpg");
    expect(queryByAltText("Error loading image")).toBeNull();
  });
});
