import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "../..");
const fontsCss = readFileSync(join(frontendRoot, "src/styles/fonts.css"), "utf8");
const indexCss = readFileSync(join(frontendRoot, "src/styles/index.css"), "utf8");
const indexHtml = readFileSync(join(frontendRoot, "index.html"), "utf8");
const appSource = readFileSync(join(here, "App.tsx"), "utf8");

describe("Font loading boundary", () => {
  it("does not request Google Fonts CSS", () => {
    for (const source of [fontsCss, indexCss, indexHtml, appSource]) {
      expect(source).not.toContain("fonts.googleapis.com");
      expect(source).not.toContain("fonts.gstatic.com");
    }
  });

  it("self-hosts DM Sans with font-display swap from index.css", () => {
    expect(fontsCss).toContain("font-display: swap");
    expect(fontsCss).toContain("/fonts/dm-sans-latin-wght-normal.woff2");
    expect(indexCss).toContain("fonts.css");
    expect(appSource).not.toContain("fonts.css");
    expect(
      existsSync(
        join(frontendRoot, "public/fonts/dm-sans-latin-wght-normal.woff2"),
      ),
    ).toBe(true);
  });
});
