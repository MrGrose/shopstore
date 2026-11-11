import { describe, expect, it, vi } from "vitest";

import { prefetchCatalogReferenceData } from "./prefetchCatalogReference";

describe("prefetchCatalogReferenceData", () => {
  it("prefetches labels and taxonomy queries once", () => {
    const prefetchQuery = vi.fn();
    const queryClient = { prefetchQuery } as never;

    prefetchCatalogReferenceData(queryClient);

    expect(prefetchQuery).toHaveBeenCalledTimes(2);
    expect(prefetchQuery.mock.calls[0]?.[0]?.queryKey).toEqual(["catalog", "labels"]);
    expect(prefetchQuery.mock.calls[1]?.[0]?.queryKey).toEqual(["catalog", "taxonomy"]);
  });
});
