import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const indexHtml = readFileSync(join(here, "../../index.html"), "utf8");
const miniAppLayout = readFileSync(join(here, "layouts/MiniAppLayout.tsx"), "utf8");
const mainSource = readFileSync(join(here, "../main.tsx"), "utf8");

describe("Telegram SDK platform boundary", () => {
  it("does not load telegram-web-app.js from index.html", () => {
    expect(indexHtml).not.toContain("telegram.org/js/telegram-web-app.js");
    expect(indexHtml).not.toContain("tg.ready()");
    expect(indexHtml).not.toContain("tg.expand()");
  });

  it("loads the SDK from MiniAppLayout via the adapter", () => {
    expect(miniAppLayout).toContain("loadTelegramWebAppScript");
    expect(miniAppLayout).toContain("initTelegramWebAppChrome");
  });

  it("snapshots Telegram launch hash before createRoot/Router", () => {
    const persistAt = mainSource.indexOf("persistTelegramLaunchParams();");
    const renderAt = mainSource.indexOf("createRoot(");
    expect(persistAt).toBeGreaterThanOrEqual(0);
    expect(renderAt).toBeGreaterThan(persistAt);
  });
});
