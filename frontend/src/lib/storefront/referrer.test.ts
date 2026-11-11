import { describe, expect, it } from "vitest";

import { formatReferralPercent } from "./referrer";

describe("formatReferralPercent", () => {
  it("formats decimals without trailing zeros", () => {
    expect(formatReferralPercent("5.00")).toBe("5");
    expect(formatReferralPercent("7.50")).toBe("7,5");
  });
});
