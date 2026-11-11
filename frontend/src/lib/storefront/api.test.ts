import { afterEach, describe, expect, it, vi } from "vitest";
import { storefrontApiFetch, storefrontApiFetchBlob } from "./api";

describe("storefront api auth headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does not set JSON Content-Type for FormData", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        json: async () => null,
      }),
    );
    const form = new FormData();
    form.append("body", "");
    form.append("files", new File([new Uint8Array([1])], "a.jpg", { type: "image/jpeg" }));
    await storefrontApiFetch("/support/tickets", { method: "POST", body: form });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("sets JSON Content-Type for string body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        json: async () => null,
      }),
    );
    await storefrontApiFetch("/support/tickets", {
      method: "POST",
      body: JSON.stringify({ topic: "general", body: "hi" }),
    });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("fetches attachment as blob without JSON Content-Type", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: async () => new Blob([new Uint8Array([1, 2])], { type: "image/jpeg" }),
      }),
    );
    const blob = await storefrontApiFetchBlob("/support/tickets/1/attachments/2/file");
    expect(blob.size).toBe(2);
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBeNull();
  });
});
