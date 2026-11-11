import { gzipSync } from "node:zlib";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const KB = 1000;

/** CI caps (kB = 1000 bytes). PR3 ≤550 kB is historical, not a gate. */
const CAPS = {
  "entry JS": { minified: 630, gzip: 200 },
  "entry CSS": { minified: 140, gzip: 25 },
  "catalog JS": { minified: 160, gzip: 50 },
};

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const distDir = join(frontendRoot, "dist");

// kB as Vite prints them (SI, not KiB).
function kb(bytes) {
  return bytes / KB;
}

function gzipSize(buf) {
  return gzipSync(buf).length;
}

function firstMatch(html, re, label) {
  const match = html.match(re);
  if (!match) {
    throw new Error(`dist/index.html: missing ${label}`);
  }
  return match[1];
}

function stylesheetHref(html) {
  for (const tag of html.matchAll(/<link\b[^>]*>/gi)) {
    if (!/\brel=["']stylesheet["']/i.test(tag[0])) continue;
    const href = tag[0].match(/\bhref=["']([^"']+\.css)["']/i);
    if (href) return href[1];
  }
  throw new Error("dist/index.html: missing entry stylesheet");
}

function resolveAsset(href) {
  const rel = href.replace(/^\//, "");
  return join(distDir, rel);
}

function measureFile(path) {
  const buf = readFileSync(path);
  return { minified: buf.length, gzip: gzipSize(buf) };
}

function findCatalogChunk() {
  const assetsDir = join(distDir, "assets");
  const names = readdirSync(assetsDir).filter((name) =>
    /^CatalogRoutes-.*\.js$/.test(name),
  );
  if (names.length !== 1) {
    throw new Error(
      `expected one CatalogRoutes-*.js in dist/assets, found ${names.length}`,
    );
  }
  return join(assetsDir, names[0]);
}

function fmt(bytes) {
  return `${kb(bytes).toFixed(2)} kB`;
}

function check(label, sizes, caps) {
  const failures = [];
  if (sizes.minified > caps.minified * KB) {
    failures.push(
      `${label} minified ${fmt(sizes.minified)} > ${caps.minified} kB`,
    );
  }
  if (sizes.gzip > caps.gzip * KB) {
    failures.push(`${label} gzip ${fmt(sizes.gzip)} > ${caps.gzip} kB`);
  }
  const status = failures.length ? "FAIL" : "ok";
  console.log(
    `${status.padEnd(4)} ${label.padEnd(10)}  ${fmt(sizes.minified).padStart(11)} / ${fmt(sizes.gzip).padStart(10)}  cap ${caps.minified} / ${caps.gzip}`,
  );
  return failures;
}

function main() {
  const indexHtmlPath = join(distDir, "index.html");
  if (!existsSync(indexHtmlPath)) {
    throw new Error("dist/index.html missing — run npm run build first");
  }

  const html = readFileSync(indexHtmlPath, "utf8");
  const entryJs = resolveAsset(
    firstMatch(html, /<script[^>]+src="([^"]+\.js)"/i, "entry script"),
  );
  const entryCss = resolveAsset(stylesheetHref(html));
  const catalogJs = findCatalogChunk();

  console.log("Bundle budgets (kB = 1000 bytes, gzip = zlib default)");
  const failures = [
    ...check("entry JS", measureFile(entryJs), CAPS["entry JS"]),
    ...check("entry CSS", measureFile(entryCss), CAPS["entry CSS"]),
    ...check("catalog JS", measureFile(catalogJs), CAPS["catalog JS"]),
  ];

  if (failures.length) {
    console.error(`\n${failures.join("\n")}`);
    process.exit(1);
  }
}

try {
  main();
} catch (err) {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
}
