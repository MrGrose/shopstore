import { afterEach, describe, expect, it } from "vitest";
import {
  hasAuthToken,
  loginHintForNext,
  resolvePhonePostLogin,
  resolvePostLoginNavigation,
  safeLoginNext,
} from "./session";

describe("safeLoginNext", () => {
  it("defaults to /catalog", () => {
    expect(safeLoginNext(null)).toBe("/catalog");
    expect(safeLoginNext("")).toBe("/catalog");
  });

  it("keeps safe relative paths", () => {
    expect(safeLoginNext("/account?tab=orders")).toBe("/account?tab=orders");
    expect(safeLoginNext("/")).toBe("/");
  });

  it("rejects protocol-relative and external paths", () => {
    expect(safeLoginNext("//evil.example")).toBe("/catalog");
    expect(safeLoginNext("https://evil.example")).toBe("/catalog");
  });
});

describe("resolvePostLoginNavigation", () => {
  it("maps /orders to account orders tab", () => {
    expect(resolvePostLoginNavigation("/orders")).toEqual({
      path: "/account?tab=orders",
    });
  });

  it("opens checkout via catalog + cart effect", () => {
    expect(resolvePostLoginNavigation("/checkout")).toEqual({
      path: "/catalog",
      effect: "checkout",
    });
  });

  it("preserves account next with query", () => {
    expect(resolvePostLoginNavigation("/account?tab=profile")).toEqual({
      path: "/account?tab=profile",
    });
  });
});

describe("resolvePhonePostLogin", () => {
  it("defaults to /account when next is omitted", () => {
    expect(resolvePhonePostLogin(null)).toEqual({ path: "/account" });
    expect(resolvePhonePostLogin("")).toEqual({ path: "/account" });
  });

  it("honours explicit next", () => {
    expect(resolvePhonePostLogin("/")).toEqual({ path: "/" });
  });
});

describe("loginHintForNext", () => {
  it("returns contextual hints", () => {
    expect(loginHintForNext("/checkout")).toContain("оформить");
    expect(loginHintForNext("/account")).toContain("личный кабинет");
    expect(loginHintForNext("/internal/admin")).toContain("администратор");
  });
});

describe("hasAuthToken", () => {
  afterEach(() => {
    localStorage.clear();
    document.cookie = "access_token=; max-age=0; path=/";
  });

  it("detects localStorage token", () => {
    localStorage.setItem("access_token", "abc");
    expect(hasAuthToken()).toBe(true);
  });

  it("detects cookie token", () => {
    document.cookie = "access_token=abc; path=/";
    expect(hasAuthToken()).toBe(true);
  });

  it("is false without token", () => {
    expect(hasAuthToken()).toBe(false);
  });
});
