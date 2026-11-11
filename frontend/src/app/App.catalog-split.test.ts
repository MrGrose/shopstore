import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "App.tsx"),
  "utf8",
);

describe("App catalog route split", () => {
  it("lazy-loads catalog pages from CatalogRoutes instead of a static import", () => {
    expect(appSource).not.toMatch(/from ["']\.\/pages\/CatalogPage["']/);
    expect(appSource).not.toMatch(/from ["']\.\/pages\/SportCatalogPage["']/);
    expect(appSource).toContain('import("./catalog/CatalogRoutes")');
  });
});
