import { afterEach, describe, expect, it } from "vitest";
import {
  captureReferralFromSearch,
  clearReferralCookie,
  readReferralCookie,
} from "./referral";

describe("referral cookie", () => {
  afterEach(() => {
    clearReferralCookie();
  });

  it("captures ?ref= from search on any path", () => {
    captureReferralFromSearch("?ref=partner42");
    expect(readReferralCookie()).toBe("partner42");
  });

  it("ignores empty ref", () => {
    captureReferralFromSearch("?ref=");
    expect(readReferralCookie()).toBeNull();
  });

  it("overwrites previous ref (last touch)", () => {
    captureReferralFromSearch("?ref=first");
    captureReferralFromSearch("?ref=second");
    expect(readReferralCookie()).toBe("second");
  });
});
